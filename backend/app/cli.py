"""Run the whole pipeline on a file from the terminal.

    python -m app.cli run FILE --date 2026-11-14 --pack test --events events.json --temperature 28
    python -m app.cli synth OUT_DIR          # write a synthetic recording with a known answer
    python -m app.cli demo                   # install that recording and its flight day for the web app

`events.json` is a list of boxes around the bend of each flyover:
    [{"t_start": 258, "t_end": 358, "f_lo": 92, "f_hi": 170, "harmonics": 1}, ...]
The result JSON (docs/05-architecture.md, section 7) goes to standard output."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _run(a) -> int:
    from . import config
    from .core import geo, media, search, spectro, synth

    data_dir = Path(a.data_dir) if a.data_dir else config.data_dir()
    try:
        info = media.probe(a.file)
        boxes_in = json.loads(Path(a.events).read_text())
        pack = geo.load_pack(a.pack)
    except media.MediaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as e:
        print(f"error: cannot read the events file: {e}", file=sys.stderr)
        return 2
    except geo.PackNotFound:
        print(f"error: no such pack: {a.pack}", file=sys.stderr)
        return 2

    def say(msg):
        if not a.quiet:
            print(msg, file=sys.stderr, flush=True)

    with tempfile.TemporaryDirectory(prefix="trace-cli-") as tmp:
        say(f"decoding {Path(a.file).name} ({info.duration_s:.0f} s)")
        x, sr = media.decode_audio(a.file)
        sp = spectro.build(x, sr, tmp)
        del x
        boxes = [search.Box(id=str(b.get("id", f"box{i + 1}")), t_start=float(b["t_start"]), t_end=float(b["t_end"]),
                            f_lo=float(b["f_lo"]), f_hi=float(b["f_hi"]), harmonics=int(b.get("harmonics", 1)))
                 for i, b in enumerate(boxes_in)]
        case = search.CaseInputs(
            pack=pack, date_local=a.date, duration_s=float(sp.t[-1]),
            time_ranges=[r.split("-") for r in a.time] if a.time else None, region_ids=a.region or None,
            temperature_c=a.temperature, temperature_source="analyst" if a.temperature is not None else None,
            file_sha256=media.sha256_file(a.file))

        def progress(kind, payload):
            if kind == "stage":
                say(f"  {payload['stage']}: {payload['state']}" + (f" ({payload['detail']})" if payload.get("detail") else ""))

        out = search.run(case, sp, boxes, data_dir=data_dir, workers=a.workers, burst=spectro.load_burst(tmp), progress=progress,
                         types=synth.SyntheticTypes() if a.synthetic_types else None, fetch_missing=a.fetch)
    text = json.dumps(out, indent=1)
    if a.out:
        Path(a.out).write_text(text)
    print(text)
    return 0


def _synth(a) -> int:
    from .core import synth

    info = synth.write_case(a.out_dir, temp_c=a.temperature, n_flights=a.flights, decoys=a.decoys)
    t = info["truth"]
    print(f"wrote {info['wav']} ({synth.DURATION_S} s, {a.flights} flyovers at {a.temperature:g} C, {a.decoys} decoy flight pairs)")
    print(f"the microphone is at {t['lat']}, {t['lon']}; the recording starts at unix {t['t0_unix']:.0f}")
    print("run it with:")
    print(f"  uv run python -m app.cli run {info['wav']} --date {synth.DATE_LOCAL} --pack test --events {info['events']} "
          f"--temperature {a.temperature:g} --data-dir {info['data_dir']} --synthetic-types")
    return 0


def _demo(a) -> int:
    """Put the synthetic case where the service will find it: the recording in
    DATA_DIR/demo/, its flight day in DATA_DIR/flights/test/."""
    import shutil
    import tempfile

    from . import config
    from .core import synth

    data = Path(a.data_dir) if a.data_dir else config.data_dir()
    with tempfile.TemporaryDirectory(prefix="trace-demo-") as tmp:
        info = synth.write_case(tmp, temp_c=28.0, n_flights=3, decoys=25)
        (data / "demo").mkdir(parents=True, exist_ok=True)
        (data / "flights" / "test").mkdir(parents=True, exist_ok=True)
        shutil.copy(info["wav"], data / "demo" / "synthetic.wav")
        shutil.copy(info["events"], data / "demo" / "events.json")
        shutil.copy(Path(tmp) / "flights" / "test" / f"{synth.UTC_DAY}-traces.npz", data / "flights" / "test" / f"{synth.UTC_DAY}-traces.npz")
    t = info["truth"]
    print(f"wrote {data / 'demo' / 'synthetic.wav'}: 30 minutes, three flyovers, recorded (in simulation) at {t['lat']}, {t['lon']}")
    print(f"wrote its flight day for the 'Synthetic test pack' ({synth.UTC_DAY}, 153 invented flights)")
    print(f"In the app: choose the region 'Synthetic test pack' (needs SHOW_DEV_PACKS=1), upload the file, date {synth.DATE_LOCAL}.")
    print(f"The boxes to draw are in {data / 'demo' / 'events.json'}; the answer should come out within about 100 m of that point.")
    return 0


def _user(a) -> int:
    """Accounts: there is no sign-up page, so they are made here. The password is typed at
    a prompt (or read from standard input), never given on the command line."""
    import getpass

    from . import config, db
    from .api import auth

    config.load_dotenv()
    db.init()
    conn = db.connect()
    try:
        if a.action == "list":
            for u in db.rows(conn, "SELECT email, role, created_at FROM users ORDER BY id"):
                print(f"{u['email']}\t{u['role']}\tcreated {u['created_at'][:10]}")
            return 0
        email = a.email.strip().lower()
        exists = db.one(conn, "SELECT id FROM users WHERE email = ?", (email,)) is not None
        if a.action == "add" and exists:
            print(f"error: {email} already has an account; use `user passwd` to change its password", file=sys.stderr)
            return 2
        if a.action == "passwd" and not exists:
            print(f"error: no such user: {email}", file=sys.stderr)
            return 2
        if a.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass(f"Password for {email}: ")
            if getpass.getpass("Again: ") != password:
                print("error: the two passwords differ", file=sys.stderr)
                return 2
        try:
            auth.strong_password(password)
        except auth.WeakPassword as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if a.action == "add":
            auth.create_user(conn, email, password, role=a.role)
            db.audit(conn, None, None, "user.create", f"{email} role={a.role}")
            print(f"created {email} ({a.role})")
        else:
            auth.set_password(conn, email, password)
            db.audit(conn, None, None, "user.password", email)
            print(f"password changed for {email}; sessions already open last until they expire")
        return 0
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli", description="TRACE from the terminal.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="search a recording and print the result JSON")
    r.add_argument("file")
    r.add_argument("--date", required=True, help="recording date in the pack's local time, YYYY-MM-DD")
    r.add_argument("--pack", default="uae")
    r.add_argument("--events", required=True, help="JSON list of flyover boxes")
    r.add_argument("--temperature", type=float, help="air temperature in C; default is the pack's monthly figure")
    r.add_argument("--time", action="append", metavar="HH:MM-HH:MM", help="local time-of-day range; repeatable")
    r.add_argument("--region", action="append", help="region id to constrain the area; repeatable")
    r.add_argument("--data-dir", help="folder holding flights/<pack>/<utc-date>-traces.npz (default: DATA_DIR or ./data)")
    r.add_argument("--workers", type=int)
    r.add_argument("--fetch", action="store_true", help="stream missing flight days, about 4 GB each")
    r.add_argument("--synthetic-types", action="store_true", help="use the synthetic case's aircraft types; no type-table download")
    r.add_argument("--out", help="also write the result JSON here")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(fn=_run)

    s = sub.add_parser("synth", help="write a synthetic recording, its boxes and its flight day")
    s.add_argument("out_dir")
    s.add_argument("--temperature", type=float, default=28.0)
    s.add_argument("--flights", type=int, default=3, choices=(2, 3))
    s.add_argument("--decoys", type=int, default=25)
    s.set_defaults(fn=_synth)

    d = sub.add_parser("demo", help="install the synthetic demo case into the data folder the service uses")
    d.add_argument("--data-dir", help="default: DATA_DIR or ./data")
    d.set_defaults(fn=_demo)

    u = sub.add_parser("user", help="add an account, change a password, or list the accounts")
    usub = u.add_subparsers(dest="action", required=True)
    for name, text in (("add", "create an account"), ("passwd", "change an account's password")):
        x = usub.add_parser(name, help=text)
        x.add_argument("email")
        x.add_argument("--password-stdin", action="store_true", help="read the password from standard input instead of asking")
        if name == "add":
            x.add_argument("--role", choices=("analyst", "admin"), default="analyst", help="an admin sees every case; an analyst only their own")
    usub.add_parser("list", help="list the accounts")
    u.set_defaults(fn=_user)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
