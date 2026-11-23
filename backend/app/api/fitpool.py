"""The fit pool: a few warm processes that fit the box an analyst just drew.

A fit takes about two seconds: too slow for the event loop, and it must not queue behind a
triage or search job that runs for minutes. The pool's processes import dopplertrack once
and stay warm; the api process itself never imports it. A fit touches no module-global
state, so reusing the processes is safe."""
from __future__ import annotations

import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from .. import config
from .deps import ApiError

FIT_TIMEOUT_S = 30.0


def _warm() -> bool:
    import dopplertrack.tracks  # noqa: F401
    return True


PHASES_HZ = (0.0, 1.0 / 3.0, 2.0 / 3.0)        # as core.events.PHASES_HZ, which this process must not import


def _preview(case_dir: str, t_start: float, t_end: float, f_lo: float, f_hi: float, harmonics: int, c: float, phase_hz: float) -> dict:
    """Runs in a pool process. Errors come back as data: the pool must outlive a bad box."""
    from ..core import events

    try:
        return events.preview_from_disk(case_dir, t_start, t_end, f_lo, f_hi, harmonics, c, phase_hz)
    except events.BoxTooSmall as e:
        return {"error": e.code, "message": str(e)}
    except events.FitFailed as e:
        return {"error": e.code, "message": str(e)}


def _count(pack_id: str, date_local: str, ranges, region_ids, data_dir: str) -> dict:
    from ..core import flights, geo

    return flights.count(geo.load_pack(pack_id), date_local, ranges, region_ids, data_dir, types=config.aircraft_types())


class FitPool:
    def __init__(self):
        self.pool: ProcessPoolExecutor | None = None

    def start(self) -> None:
        if config.fit_inline():
            return
        self.pool = ProcessPoolExecutor(config.fit_workers(), mp_context=multiprocessing.get_context("spawn"),
                                        initializer=config.exit_with_parent)
        for _ in range(config.fit_workers()):
            self.pool.submit(_warm)

    def stop(self) -> None:
        if self.pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None

    async def _run(self, fn, *args):
        loop = asyncio.get_running_loop()
        if config.fit_inline() or self.pool is None:
            return await loop.run_in_executor(None, fn, *args)       # a thread: fine for tests
        try:
            return await asyncio.wait_for(loop.run_in_executor(self.pool, fn, *args), FIT_TIMEOUT_S)
        except BrokenProcessPool:
            self.stop()
            self.start()
            raise ApiError(503, "fit_unavailable", "The fitting service restarted. Try again.") from None
        except asyncio.TimeoutError:
            raise ApiError(504, "fit_timeout", "The fit took too long. Try a smaller box.") from None

    async def preview(self, case_dir, t_start, t_end, f_lo, f_hi, harmonics, c) -> dict:
        """The quick fit at each grid phase, side by side; the brightest is the one to draw
        (docs/02-dopplertrack.md, behaviour 16)."""
        args = (str(case_dir), float(t_start), float(t_end), float(f_lo), float(f_hi), int(harmonics), float(c))
        outs = await asyncio.gather(*(self._run(_preview, *args, ph) for ph in PHASES_HZ))
        good = [o for o in outs if "error" not in o]
        if not good:
            raise ApiError(422, outs[0]["error"], outs[0]["message"])
        return max(good, key=lambda o: o["fit"]["score"])

    async def count(self, pack_id, date_local, ranges, region_ids) -> dict:
        return await self._run(_count, pack_id, date_local, ranges, region_ids, str(config.data_dir()))
