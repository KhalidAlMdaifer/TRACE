# Opening prompt for Claude Code

Open a terminal in this folder, start `claude`, and paste everything in the block below as
your first message.

```
This folder holds the full plan for a hackathon MVP. No application code exists yet.

1. Read CLAUDE.md, then docs/00-START-HERE.md, then the docs in the reading order it
   gives. Read docs/02-dopplertrack.md closely: it records how the library really behaves,
   including traps that were found by running it.

2. Before any application code, do milestone M0 from docs/07-build-plan.md:
   - git init; create the uv project on Python 3.12; add dopplertrack pinned to the commit
     named in CLAUDE.md; add pytest.
   - check that ffmpeg and ffprobe run.
   - run  uv run python scripts/smoke_dopplertrack.py --hot --decoys 25 --editor
     and  uv run python scripts/coverage_report.py --self-test
   - show me both results and compare the timings with the table in
     docs/02-dopplertrack.md.

3. Then ask me the open questions in docs/09-risks-and-open-questions.md that block you:
   my operating system, the deadline and team size, the app name, whether you may stream
   flight data (about 4 GB per day), and whether to fetch the Oyster Bay recording.

4. Do not stream flight data, download any recording, or push to GitHub until I say yes.

5. After M0, work through M1 to M6 in order. For each milestone: write its acceptance
   tests first, implement, keep `uv run pytest` green, tick it in CLAUDE.md, add any
   decision to docs/09-risks-and-open-questions.md, and commit. Stop and report to me at
   the end of each milestone before starting the next.

6. Build the interface from design/mockups (nine screens, read them as text), the tokens
   in design/tokens.css and the notes in docs/08-design.md. Values shown in the mockups are
   samples; take real values from the API.

If the dopplertrack source ever disagrees with these docs, the source wins: tell me, then
fix the doc.
```
