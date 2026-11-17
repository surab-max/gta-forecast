# gta-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/surab-max/gta-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/surab-max/gta-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A forecaster for GTA VI's launch-day Twitch audience. Given everything
recorded up to the end of hour 1 of release day (2026-11-19 UTC), it
predicts, for each of hours 2-24, five quantiles of the mean concurrent
viewers in Twitch's "Grand Theft Auto VI" category.

The method is a kernel-weighted comparable-shape model: each past big
launch in the case's `comparables` contributes its release-day log-ratios
to hour 1, weighted by hour-1 size similarity (and same-weekday), pooled
only over launches that were already unlocked at hour 1, and read off as
a smoothed lognormal per hour. The reasoning, the two launch regimes it
separates, and the leave-one-out cross-validation behind every constant
are in [docs/MODEL.md](docs/MODEL.md); the validation scripts are in
`tools/`.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Standard library only (Python 3.13 in the grader, `python3 -P -s
/bot/main.py`); deterministic; no network. Input and output formats are
the competition's `makefun/twitch-ccu-case/v1` case and forecast files.

---

<sub>Entered on [make.fun](https://make.fun/?ref=ys1ka8r4&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
