#!/usr/bin/env bash
# A case from upload to result with curl alone, on the synthetic recording.
#
# 1. Make a data folder with a synthetic recording and its flight day:
#        uv run python -m app.cli synth /tmp/trace-demo
# 2. Start the api and the worker on that folder (see .env.example for the settings):
#        export DATA_DIR=/tmp/trace-demo TRACE_SYNTHETIC_TYPES=1 APP_SECRET=... ADMIN_EMAIL=... ADMIN_PASSWORD=...
#        uv run uvicorn app.api.main:app --port 8000 &
#        uv run python -m app.worker &
# 3. Run this with the same ADMIN_EMAIL and ADMIN_PASSWORD in the environment:
#        scripts/curl_walkthrough.sh /tmp/trace-demo
set -euo pipefail

DEMO="${1:?give the folder written by: python -m app.cli synth DIR}"
BASE="${BASE:-http://127.0.0.1:8000}"
: "${ADMIN_EMAIL:?set ADMIN_EMAIL}" "${ADMIN_PASSWORD:?set ADMIN_PASSWORD}"
JAR="$(mktemp)"; trap 'rm -f "$JAR"' EXIT
api() { curl -sS -b "$JAR" -c "$JAR" "$@"; }
field() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {'d': d}))" "$1"; }

echo "sign in"
api -X POST "$BASE/api/auth/login" -H 'content-type: application/json' \
    --data "$(python3 -c 'import json,os; print(json.dumps({"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]}))')" \
    | field 'd["user"]["email"]'

CASE=$(api -X POST "$BASE/api/cases" -H 'content-type: application/json' --data '{"pack_id": "test"}' | field 'd["id"]')
echo "case $CASE"

echo "upload"
api -X POST "$BASE/api/cases/$CASE/media" -F "file=@$DEMO/synthetic.wav" | field '"sha256 " + d["media"]["sha256"]'

api -X PATCH "$BASE/api/cases/$CASE" -H 'content-type: application/json' \
    --data '{"date_local": "2026-11-14", "temperature_c": 28, "case_ref": "CURL-0001"}' >/dev/null

echo -n "waiting for the spectrogram "
until [ "$(api "$BASE/api/cases/$CASE" | field 'd["media"]["spectrogram_ready"]')" = "True" ]; do echo -n .; sleep 1; done; echo

echo "confirm three flyovers (each answers with a fitted curve)"
python3 -c 'import json,sys; [print(json.dumps(b)) for b in json.load(open(sys.argv[1]))]' "$DEMO/events.json" | while read -r box; do
    api -X POST "$BASE/api/cases/$CASE/events" -H 'content-type: application/json' --data "$box" \
        | field '"  heard at %.1f s, f0 %.1f Hz, score %.1f" % (d["fit"]["t_cpa"], d["fit"]["f0"], d["fit"]["score"])'
done

echo "search"
api -X POST "$BASE/api/cases/$CASE/search" | field '"job " + d["job_id"]'

# the event stream, until the search ends
api -N "$BASE/api/cases/$CASE/stream" 2>/dev/null | while IFS= read -r line; do
    case "$line" in
        "event: stage") read -r data; echo "  ${data#data: }" ;;
        "event: done"|"event: failed"|"event: cancelled") read -r data; echo "$line ${data#data: }"; break ;;
    esac
done || true        # curl ends with a write error once we stop reading; that is expected

echo "result"
api "$BASE/api/cases/$CASE/result" | field '"%s (%s), verdict %s p=%s, estimate %s" % (d["state"], d["band"], d["verdict"]["label"], d["verdict"]["p"], d["estimate"] and (round(d["estimate"]["lat"], 5), round(d["estimate"]["lon"], 5), "within about %d m" % d["estimate"]["radius_m"]))'
echo "report: $BASE/api/cases/$CASE/report"
