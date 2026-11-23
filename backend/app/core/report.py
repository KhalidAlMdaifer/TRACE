"""The printable report: one self-contained HTML page, no scripts, no outside requests."""
from __future__ import annotations

from html import escape

STATE_TITLES = {"located": "Located", "candidates": "Candidates, unconfirmed", "outside": "Match outside the stated constraints",
                "not_locatable": "Not locatable"}
SUBLABELS = {"unconfirmed": "Unconfirmed", "weak": "Weak: the best match is no better than chance",
             "too_few_flights": "Too few other flights that day to judge this match", "needs_third_flyover": "Unconfirmed: add a third flyover"}


def _row(k, v) -> str:
    return f"<tr><th>{escape(str(k))}</th><td>{escape('not available' if v is None else str(v))}</td></tr>"


def render_html(case: dict, result: dict) -> str:
    """case: {case_ref, id, filename, created_at}. result: the result JSON."""
    inp, v, est = result.get("inputs") or {}, result.get("verdict") or {}, result.get("estimate")
    title = STATE_TITLES.get(result.get("state"), "Result")
    head = [_row("Case reference", case.get("case_ref")), _row("Case id", case.get("id")), _row("File", case.get("filename")),
            _row("File SHA-256", inp.get("file_sha256")), _row("Recording date (local)", inp.get("date_local")),
            _row("Region pack", inp.get("pack"))]
    outcome = [_row("Outcome", title)]
    if result.get("sublabel"):
        outcome.append(_row("Note", SUBLABELS.get(result["sublabel"], result["sublabel"])))
    outcome += [_row("Band", result.get("band")), _row("Match strength (0 to 100, not a probability)", result.get("strength")),
                _row("Verdict", v.get("label")), _row("p value", v.get("p")),
                _row("Wrong flight pairs it was judged against", v.get("n_null")), _row("Flyovers used", inp.get("n_flyovers"))]
    if est:
        # only a located result has an estimate; anything else has a best candidate, and says so
        is_located = result.get("state") == "located"
        outcome += [_row("Estimate (lat, lon)" if is_located else "Best candidate inside the stated area and time (lat, lon), unconfirmed",
                         f"{est['lat']:.6f}, {est['lon']:.6f}"),
                    _row("Uncertainty radius" if is_located else "Sharpness of that candidate", f"within about {est['radius_m']:.0f} m"),
                    _row("Recording start (UTC)" if is_located else "Recording start it implies (UTC)", result.get("clip_start_utc"))]
    nl = result.get("not_locatable")
    why = ""
    if nl:
        why = ("<h2>Why</h2><p>Checked: " + escape("; ".join(nl.get("checked", []))) + ".</p><ul>"
               + "".join(f"<li>{escape(a)}</li>" for a in nl.get("advice", [])) + "</ul>")
    caps = "".join(f"<li>{escape(c)}</li>" for c in result.get("caps") or [])
    ev_rows = "".join(
        f"<tr><td>{escape(str(e.get('role')))}</td><td>{e.get('t_cpa')}</td><td>{e.get('f0')}</td><td>{escape(str(e.get('icao') or 'no match'))}</td>"
        f"<td>{escape(str(e.get('type') or ''))}</td><td>{escape(str(e.get('cpa_time_utc') or ''))}</td><td>{e.get('slant_m', '')}</td><td>{e.get('score', '')}</td></tr>"
        for e in result.get("events") or [])
    cand_rows = "".join(
        f"<tr><td>{c['rank']}</td><td>{c['lat']:.5f}, {c['lon']:.5f}</td><td>{c['score']}</td><td>{escape(' / '.join(c['icao']))}</td>"
        f"<td>{'yes' if c['in_area'] else 'no'}</td><td>{'yes' if c['in_time'] else 'no'}</td></tr>" for c in result.get("candidates") or [])
    om = (result.get("constraints") or {}).get("outside_match")
    outside = ""
    if om:
        outside = (f"<h2>Stronger match outside the stated area or time</h2><p>{om['lat']:.5f}, {om['lon']:.5f}, score {om['score']}, flights "
                   f"{escape(' / '.join(om['icao']))}. {'It passes the located test on its own.' if om.get('confirmed') else 'It is unconfirmed.'}</p>")
    sources = {"analyst": "set by the analyst", "climate_monthly": "monthly average for the region", "auto": "automatic, from the weather archive for that date and time window"}
    method = [_row("Air temperature used", f"{inp.get('temperature_c')} C ({sources.get(inp.get('temperature_source'), inp.get('temperature_source'))})"),
              _row("Flight days searched (UTC)", ", ".join(inp.get("flight_days") or []) or "none"),
              _row("Flight days not on file", ", ".join(inp.get("flight_days_missing") or []) or "none"),
              _row("Propeller-class flights in the search", inp.get("n_flights")),
              _row("Track points dropped by integrity checks", "not measured for these flight days" if inp.get("rows_dropped_pct") is None else f"{inp['rows_dropped_pct']}%"),
              *([_row("Searched at two temperatures", "; ".join(f"{t['c']} C: score {t['score']}, flights {' / '.join(t['pair'] or [])}" for t in inp["temperature_runs"]))] if inp.get("temperature_runs") else []),
              *([_row("Other days searched as a control", "; ".join(f"{d['utc_date']}: best score {d['best_score']}" for d in (result.get("controls") or {}).get("placebo_days") or []))] if (result.get("controls") or {}).get("placebo_days") else []),
              _row("Engine", f"dopplertrack {inp.get('dopplertrack')}"), _row("Search parameters", inp.get("params"))]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>TRACE report {escape(str(case.get('case_ref') or case.get('id')))}</title>
<style>
body{{font:14px/1.5 system-ui,sans-serif;color:#111;max-width:820px;margin:32px auto;padding:0 20px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 8px;border-bottom:1px solid #ccc;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%}} th,td{{text-align:left;padding:4px 10px 4px 0;vertical-align:top;border-bottom:1px solid #eee}}
th{{font-weight:600}} tr>th:first-child:nth-last-child(2){{width:42%}} .lead{{border:2px solid #111;padding:12px 16px;margin:16px 0}} .small{{color:#555;font-size:12px}}
tr{{break-inside:avoid}} h2{{break-after:avoid}}
@media print{{body{{margin:0;font-size:12px}} .noprint{{display:none}}}}
</style></head><body>
<p class="small noprint">To keep this report, print the page and choose "Save as PDF".</p>
<h1>TRACE location report</h1>
<p class="small">Tracking Recordings via Aircraft Curve Estimation · result recorded {escape(str(result.get('created_at') or case.get('created_at') or ''))[:19].replace('T', ' ')} UTC</p>
<div class="lead"><strong>{escape(title)}.</strong> This result is a lead to corroborate, not proof of a location.</div>
<h2>Case</h2><table>{''.join(head)}</table>
<h2>Outcome</h2><table>{''.join(outcome)}</table>
{('<h2>Limits applied</h2><ul>' + caps + '</ul>') if caps else ''}
{why}{outside}
{('<h2>Flyovers</h2><table><tr><th>Role</th><th>Heard at (s)</th><th>f0 (Hz)</th><th>Aircraft</th><th>Type</th><th>Closest approach (UTC)</th><th>Slant (m)</th><th>Score</th></tr>' + ev_rows + '</table>') if ev_rows else ''}
{('<h2>Candidates</h2><table><tr><th>Rank</th><th>Lat, lon</th><th>Score</th><th>Flights</th><th>In area</th><th>In time</th></tr>' + cand_rows + '</table>') if cand_rows else ''}
<h2>Method and inputs</h2><table>{''.join(method)}</table>
<p class="small">The method matches the Doppler curves of propeller aircraft in the recording against public flight tracks.
"Match strength" maps a tested verdict to a number; it is not the probability of being right. Two flyovers give candidates only;
a located result needs three or more flyovers on one clock.</p>
<p class="small">Built on dopplertrack by MacCallister Higgins (MIT licence). Flight tracks from adsb.lol, Open Database License 1.0.
Aircraft types from ICAO Doc 8643 via the OpenSky Network. Elevation from AWS Terrain Tiles. Region boundaries from OpenStreetMap contributors, Open Database License 1.0. Automatic air temperature: weather data by Open-Meteo.com, CC BY 4.0.</p>
</body></html>"""
