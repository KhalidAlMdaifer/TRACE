# Start here

You are picking up a project that was planned in a chat session and has no application
code yet. This file tells you what exists, what is verified, and what to do first.

## What is in this folder

| Path | What it is | Status |
|---|---|---|
| `CLAUDE.md` | rules, commands, status | read every session |
| `docs/01-product.md` | what we are building, for whom, result states, flow | decided |
| `docs/02-dopplertrack.md` | the engine's real CLI and API | verified against source at the pinned commit |
| `docs/03-method-and-evidence.md` | physics, what has been validated, our own experiments | verified; press items marked |
| `docs/04-data.md` | flight archives, trace format, time zones, packs, temperature | formats verified; weather source not |
| `docs/05-architecture.md` | processes, modules, schema, API, stream, orchestration | design, not yet built |
| `docs/06-confidence.md` | verdict, bands, controls | verdict verified; our rules and controls are proposals |
| `docs/07-build-plan.md` | milestones with acceptance tests | plan |
| `docs/08-design.md` | tokens, screens, copy, motion, corrections to the mockups | approved look; unmocked screens are notes |
| `docs/09-risks-and-open-questions.md` | risks, decision log, questions for the user | living |
| `scripts/smoke_dopplertrack.py` | synthetic end-to-end run of the library, plus the temperature, verdict and flyover-editor experiments; holds the reference `fit_box` and `fit_preview` | all modes ran and passed during planning |
| `scripts/coverage_report.py` | step 0 report on a day's traces | self-test passed; ran on a real-format sample trace |
| `design/tokens.css` | design tokens as CSS variables | ready |
| `design/mockups/` | sources of the nine screens: Upload, When, Where, Flyovers, Review, Searching, and the Located, Candidates and Not locatable results | reference only, read as text; brought in line with the engine on 2026-11-21 |
| `design/dot_map_prototype.py` | how the mockups' dot rows were generated | reference only; its polygons are rough placeholders |
| `design/spectrogram_prototype.py` | how the flyover editor's sample spectrogram was generated | reference only; invented data |

## Read in this order

1. `CLAUDE.md`
2. This file
3. `01-product.md`, then `03-method-and-evidence.md` (they explain why the rules exist)
4. `02-dopplertrack.md` before touching the engine
5. `07-build-plan.md` for the task at hand, pulling in `04`, `05`, `06`, `08` as each milestone needs them

## First session

1. Ask the user the open questions in `09-risks-and-open-questions.md` that block you: operating system, permission to stream flight data, deadline.
2. Do milestone M0 in `07-build-plan.md`: project setup, both scripts, then the coverage probe.
3. Report the coverage findings to the user before building anything else.


## Setup, expected to work as written

```
git init
uv init --python 3.12            # then set the package layout from docs/05-architecture.md
uv add "dopplertrack @ git+https://github.com/mjshiggins/dopplertrack@2d899bbfe1529e2b4351f328969bb37776d57cb4"
uv add --dev pytest
ffmpeg -version && ffprobe -version
uv run python scripts/smoke_dopplertrack.py --hot --decoys 25 --editor   # about 5 minutes on one core; ends with SMOKE TEST PASSED
uv run python scripts/coverage_report.py --self-test
```

If `uv add` rejects the git form, check `uv add --help` for the current syntax; the commit hash is what matters.

## The seven facts that most shape the work

1. **Two flyovers give candidates; a third confirms.** Every validated two-flyover search came out ambiguous. Do not let the UI promise more.
2. **The analyst's window is what gets searched.** Automatic detection finds flyovers but its fits are not accurate enough; the flyover editor is a required screen.
3. **Temperature matters.** Pass `c=speed_of_sound(T)` everywhere. The library default is 15 C.
4. **One search per process, one worker off Linux.** The library forks and keeps global state.
5. **Most recordings are not locatable.** Reaching that answer quickly and explaining it is a core feature.
6. **Detection is the slow step, and it is only a hint.** About 2 s per minute of audio with fast settings, 10 s with library defaults, and its proposals are often misplaced. Show the spectrogram first, stream proposals, and let the analyst work without them.
7. **Fits need care.** A narrow box makes the library raise; widen it by the rule in `02-dopplertrack.md`, behaviour 11. A full fit takes 5 to 19 s, so the editor draws a 2 s preview and the search refits in full.

## What changed late in planning

The first version of these notes described an older dopplertrack (commands `extract-region`,
`search-single`; a grid search over a box). The code was then read at the pinned commit and
everything was rewritten against it. If you find any remaining mention of those commands, or
of a "time-shift null test" as the confidence measure, treat it as stale and follow
`02-dopplertrack.md` and `06-confidence.md`. The mockups were then redrawn to match (five
steps, a flyover editor, a Candidates result, the real verdict rows); what is still a
stand-in in them is listed in `08-design.md`, section 5.
