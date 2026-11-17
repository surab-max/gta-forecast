# Model notes: how the forecast is built, and why

## The problem, restated

One hour into GTA VI's release day (2026-11-19, UTC) we must give, for each
of hours 2-24, five quantiles (5/25/50/75/95%) of that hour's mean Twitch
viewers in the "Grand Theft Auto VI" category. Scoring is mean pinball loss
on the log scale, so what matters is the *ratio* to the truth, hour by hour,
and an honest spread: a quantile band that is too narrow or too wide both
pay. The only hard anchor at forecast time is hour 1's print, plus the
case's `comparables`: ~40 past big launches with full hourly Twitch curves
(SullyGnome hourly category averages, per the kit's NOTICE.txt).

## What the comparables actually look like

`tools/explore.py` prints the release-day anatomy of every comparable.
Two regimes are mixed together:

- **Rolling midnight-local launches** (most console launches, and all four
  practice launches, and GTA VI itself): by 00:00-01:00 UTC the game has
  unlocked in New Zealand, Japan, Europe and the UK, so hour 1 already
  holds a real audience. Release-day peak / hour-1 is between 1.0 and ~3.6.
  The day's shape is a dip or plateau in the European morning, a climb as
  the US unlocks (04:00-08:00 UTC) and wakes, and a peak around
  18:00-23:00 UTC.
- **Single-time global unlocks** (Black Myth: Wukong 02:00 UTC, Hollow
  Knight: Silksong 14:00 UTC, Baldur's Gate 3, ARC Raiders, ...): hour 1
  UTC is a pre-unlock trickle, peak / hour-1 is 10x-2000x. Their
  hour-1-anchored ratios are meaningless for a rolling launch, and a
  rolling launch's ratios are meaningless for them.

Early-access launches (Starfield, Diablo IV, Hogwarts Legacy) sit between:
their audience partly arrived days earlier, so the release day is flatter.

## The shipped model (`main.py`)

1. For each comparable, extract its release-day hours 1-24 (UTC) and form
   log-ratios `log(viewers_h / viewers_1)`.
2. Pool selection (the regime split): if the target's hour-1 audience is
   at least 15,000, keep only comparables with release-day
   peak / hour-1 <= 6 — the rolling-launch pool. If hour 1 is small the
   target may itself be pre-unlock, so keep every comparable and add a
   second kernel on the *pre-midnight ramp*, `log(p1 / previous hour)`,
   which is computable for the target from `history_hourly` and for each
   comparable from its own hourly curve.
3. Weight each pooled comparable by a Gaussian kernel on log hour-1 size
   (bandwidth 0.75, floor 0.05), times 1.75 if it launched on the same
   weekday (Twitch's weekly cycle).
4. Per forecast hour, take the weighted mean and standard deviation of the
   log-ratios; smooth both curves over a 3-hour window; read the five
   quantiles off the lognormal at the case's levels.
5. If no comparable is usable, fall back to persistence with a
   random-walk spread (the house baseline's shape).

Everything is deterministic (fixed iteration order, no randomness, no
clock), standard-library only, and runs in ~0.04 s per case.

## Validation: leave-one-out over the comparables

The practice launches' answers are not in the kit (each practice case's
comparables exclude all four practice launches), so the honest local
validation is leave-one-out cross-validation over the comparables
themselves: pretend only a comparable's hour 1 is known, forecast its day
from the others, score with the contest's pinball loss (`tools/cv.py`,
`tools/cv2.py`, `tools/cv3.py`). On the subset that resembles the actual
targets — rolling launches with hour-1 >= 20,000 (24 comparables):

| model | LOO pinball loss (log) |
| --- | --- |
| house baseline (persistence, sigma 0.15 sqrt h) | 0.265 |
| unweighted empirical quantiles, all comparables | 0.358 |
| size kernel (bw 1.25), empirical quantiles | 0.210 |
| size kernel (bw 0.75) + peak cap 6 + lognormal quantiles | **0.203** |
| + pre-midnight ramp-shape kernel | 0.203 (no gain on this subset) |
| + weekday boost | 0.203 |

Two lessons the grid taught, both baked into the shipped constants:

- The size kernel is the single biggest win: big launches have flatter
  days, and hour-1 size is the best observable proxy for which shape a
  launch will follow.
- The peak-ratio cap only helps once the kernel is in place; uncapped,
  the global-unlock comparables drag the upper quantiles far too high
  for rolling-launch targets (0.257 vs 0.203 on the clean subset).

The ramp-shape kernel did not help on the clean subset, so in the shipped
program it is used only in the small-target regime, where CV says the
ramp kernel is what rescues the forecast (0.457 vs 0.812 overall when the
cap is off and the ramp kernel is on).

## What this does not use, deliberately

- `streams` / `categories_hourly` (final case only, null in practice):
  no local data exists to validate any use of them, so they are ignored
  rather than fitted blind.
- The target's own pre-release category history: it measures trailer and
  premiere hype, not launch-day shape, and the one comparable that is the
  target's own category is explicitly excluded from the pool.
- Any per-launch narrative adjustments: with ~37 usable comparables,
  hand-tuning to individual titles overfits; the kernel is the narrative,
  expressed as weights.
