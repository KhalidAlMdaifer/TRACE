# Confidence

How a search result becomes a state, a band and a number the analyst can defend.

## Principles

1. **A margin is not a confidence.** Every search returns a winner, including one over an area that cannot contain the answer. Judge the winner against the crowd of wrong answers, not against the runner-up alone.
2. **Use dopplertrack's verdict as the core.** It is the only confidence measure that has been tested against known answers. We add rules around it; we do not replace it.
3. **Say less when the evidence is thin.** Two flyovers produce candidates. "Located" needs a third flyover on the same clock.
4. **Show the working.** p value, number of wrong pairs it was judged against, number of flyovers, temperature used, share of track points dropped.

## The verdict (dopplertrack, as implemented)

- Take the best point of every flight pair. Drop pairs that share a flight with the winner.
- Fit an exponential tail to the top k of the remaining ("wrong") pairs, k = 5% of them, clamped to 15..100. `m` is their mean excess over the k-th.
- `gap` = winner score minus best wrong pair. `p = exp(-gap / m)`: the chance a wrong winner would lead by that much.
- `located` if p < 0.1, `ambiguous` if p < 0.5, else `no match`. `insufficient` if fewer than k + 5 wrong pairs exist (in practice, fewer than 20).

Known behaviour: two-event searches came out `ambiguous` on every validated recording; extras made the right answers `located`; two of twenty searches with no right answer were called `located` at p 0.08 and 0.006. Treat p < 0.1 as weak.

## Our rules on top

Inputs: the result table `R` (whole pack), the constraint flags per pair (`in_area`, `in_time`), the confirmed events, `verdict(R)`.

```
n_events  = number of confirmed flyovers used (pair + extras that matched a flight)
top       = best pair in R
top_in    = best pair in R with in_area and in_time
v         = verdict(R)

if fewer than 2 confirmed flyovers            -> not_locatable (fewer_than_two_flyovers)
if no propeller flights in the archive        -> not_locatable (no_flights)
if R is empty                                 -> not_locatable (no_candidates)
if top_in is None                             -> outside (show top as the outside match)
if top is not top_in                          -> outside (top_in as candidate, top flagged as stronger outside match)
if v.verdict == "located" and n_events >= 3   -> located
otherwise                                     -> candidates, with a sub-label from the verdict:
                                                   ambiguous    "unconfirmed"
                                                   no match     "weak: the best match is no better than chance"
                                                   insufficient "too few other flights that day to judge"
                                                   located on two flyovers only  "unconfirmed: add a third flyover"
```

In the outside state, run the located test on `top` as well. If it passes (three or more flyovers, verdict `located`), the stated area or time was probably wrong: the banner reads "A confirmed match lies outside your area" and the outside match gets the full Located treatment, with its band, when opened. If it does not pass, both are shown as candidates. With two flyovers and a whole-pack search the overall winner will often be a chance match far away, so this state will be common; keep its wording calm.

Why `no match` still yields candidates: in the decoy experiment the two-flyover verdict was `no match` while the truth sat at rank 2, and the third flyover then located it. A weak list the analyst can corroborate by other means is more useful than nothing, as long as it is labelled weak. Show at most five.

### Strength and band

`strength = round(100 * clamp(-log10(p) / 3, 0, 1))`, so p 0.001 or smaller is 100, p 0.01 is 67, p 0.1 is 33, p 0.5 is 10.

| Band | Rule | Wording in the UI |
|---|---|---|
| High | state located, p <= 0.01, 3+ flyovers | "Located" |
| Medium | state located, 0.01 < p < 0.1 | "Located, weak" with the note that one in ten such results is expected to be wrong |
| Low | state candidates or outside | "Candidates, unconfirmed" |
| None | not locatable | "Not locatable" |

Caps, applied after the rule above:

- Verdict `insufficient`: strength is not shown; band Low; say "too few other flights that day to judge this match".
- Any confirmed event with `burst > 0.15`: cap at Medium and flag the event. (`fit_event` does not fill `burst`; `core.events` does, see `05-architecture.md`, section 3.)
- More than 20% of track points dropped by the integrity filter that day: cap at Medium and say so.
- Automatic temperature with a window over six hours: cap at Medium unless both temperature runs agree on the same pair.
- A cut is suspected in the recording between the events used: cap at Low.

These thresholds are starting values. They are a mapping of the tested verdict, not a calibrated probability; the documentation and the report must say "match strength", not "probability of being right".

### Uncertainty radius

From the 50 m refine grid around the estimate: the largest distance from the peak among cells scoring at least 95% of the peak, with a 50 m floor. For candidates, show each one's radius the same way. Report "within about N m" rounded to two significant figures.

## Controls (ours, proposed, untested)

These address the weakness of the verdict when a region has few flights, which is the expected situation in the UAE.

1. **Placebo days.** Search the same audio and events against the same pack on three to five other days. No pair on those days can be right, so their winners are a direct sample of "best wrong score for this recording in this region". Report the real winner's rank among them and require it to beat all of them before allowing High. Cost: one extra search per placebo day, cheap for a small region. This also gives a verdict when `verdict()` says `insufficient`.
2. **Moved-box sanity check.** In tests only: the Oyster Bay audio searched against an area that cannot contain the answer must come out `not_locatable`.
3. **Temperature agreement.** When two temperature runs are made, the same pair must win both.

Implement placebo days in milestone 5 behind a setting; validate it on the New York pack (where the answer is known) before trusting it anywhere.

## Tests that pin this down

- Synthetic case with 25 decoy pairs and three flyovers: located (during planning this gave p 0.043, so Medium; High needs a stronger case, for example a fourth flyover).
- Same with two flyovers: candidates, Low, truth among the top five.
- Same at a 25 C temperature error: must not be High.
- No flyovers: not locatable.
- Constraints that exclude the truth: outside, with the truth shown as the outside match.
- The saved best-per-pair tables in dopplertrack's `docs/results/` (seven searches with known verdicts) fed through `assess`: bands match the table in the evidence file.
