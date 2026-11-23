"""Shapes shared by the api and the jobs. Nothing here may import dopplertrack."""
from __future__ import annotations

import json


def event_public(row: dict) -> dict:
    """An events row in the shape of GET /events."""
    return {"id": row["id"], "source": row["source"], "status": row["status"], "t_start": row["t_start"], "t_end": row["t_end"],
            "f_lo": row["f_lo"], "f_hi": row["f_hi"], "harmonics": row["harmonics"],
            "fit": json.loads(row["fit"]) if row["fit"] else None, "fit_temperature_c": row["fit_temperature_c"],
            "score": row["score"], "burst": row["burst"], "curve": json.loads(row["curve"]) if row["curve"] else []}
