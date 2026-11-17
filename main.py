"""GTA VI launch-day Twitch viewers forecaster (make.fun program/v1).

Model in one paragraph: the case hands us, for each of ~40 past big game
launches, that launch's full hourly Twitch curve.  For a comparable whose
release day is usable we form the 23 log-ratios log(viewers_h / viewers_1)
of its release day.  The forecast for the target is a kernel-weighted
lognormal fit of those ratios, hour by hour: comparables are weighted by
how close their hour-1 audience is to the target's (a Gaussian kernel on
log size), only comparables whose release day was not still locked at
hour 1 are pooled (their day's peak is at most 6x their hour 1), and the
per-hour mean and standard deviation of the log-ratios are smoothed over
neighbouring hours before the five quantiles are read off at the case's
levels.  The design and the leave-one-out cross-validation behind every
constant are documented in docs/MODEL.md; the validation scripts live in
tools/.

The program is deterministic, standard-library only, and reads every
*.in file in $MAKEFUN_INPUT_DIR (default /input), writing <id>.out to
$MAKEFUN_OUTPUT_DIR (default /output).
"""

import json
import math
import os
import sys
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# A comparable joins the shape pool only if its release day was already
# unlocked at hour 1: peak / hour-1 at most this.  Single-time global
# unlocks sit at 10x-1000x and would poison every quantile.
PEAK_RATIO_CAP = 6.0
# Gaussian kernel bandwidth on log hour-1 size, and its floor weight so a
# distant comparable still counts a little.
SIZE_BANDWIDTH = 0.75
WEIGHT_FLOOR = 0.05
# Same-weekday launches get a small boost: Twitch has a weekly cycle.
WEEKDAY_BOOST = 1.75
# Neighbouring hours share strength: window for the moving average of the
# per-hour mean / sd curves, in hours.
SMOOTH_WINDOW = 3
# Spread of the fallback (house-style persistence) forecast, per sqrt hour.
FALLBACK_SIGMA = 0.15
# Below this hour-1 audience the target may not be unlocked yet; see the
# two-regime note in forecast_case.
SMALL_TARGET_P1 = 15000
# Gaussian kernel bandwidth on the pre-midnight ramp, log(p1 / prev hour).
RAMP_BANDWIDTH = 0.6

_NORM = NormalDist()


def _parse_stamp(stamp):
    """Parse an ISO-8601 UTC stamp to a comparable tuple (ordinal, hour)."""
    date_part, time_part = stamp.split("T")
    year, month, day = (int(x) for x in date_part.split("-"))
    hour = int(time_part[:2])
    # Days since a fixed epoch, via the civil calendar algorithm; only
    # differences and weekdays are used, so any consistent epoch works.
    y = year - (1 if month <= 2 else 0)
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = (month + 9) % 12
    doy = (153 * mp + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe
    return days, hour


def _weekday(day_start):
    days, _ = _parse_stamp(day_start)
    # 1970-01-01 (a Thursday) is day 719468 in the count above; the offset
    # only needs to be consistent between target and comparables.
    return days % 7


def release_day_hours(comp):
    """{hour 1..24: viewers} for a comparable's release day (UTC)."""
    start_date = comp["day_start"][:10]
    hours = {}
    for row in comp.get("hourly", []):
        stamp = row.get("from", "")
        if stamp[:10] != start_date:
            continue
        viewers = row.get("viewers")
        if viewers:
            hours[int(stamp[11:13]) + 1] = float(viewers)
    return hours


def previous_hour_viewers(rows, day_start):
    """Viewers in the hour just before day_start, from hourly rows."""
    best_stamp, best_viewers = None, None
    for row in rows:
        stamp = row.get("from", "")
        viewers = row.get("viewers")
        if viewers and stamp < day_start and (best_stamp is None or stamp > best_stamp):
            best_stamp, best_viewers = stamp, float(viewers)
    return best_viewers


def comparable_profile(comp, target_name):
    """Summarise one comparable, or return None if it cannot teach shape."""
    if comp.get("name") == target_name:
        return None  # the target's own pre-release history is not a launch
    hours = release_day_hours(comp)
    if 1 not in hours or len(hours) < 18:
        return None
    p1 = max(1.0, hours[1])
    peak_ratio = max(hours.values()) / p1
    prev = previous_hour_viewers(comp.get("hourly", []), comp["day_start"])
    ramp = math.log(p1 / max(1.0, prev)) if prev else 0.0
    return {"hours": hours, "p1": p1, "peak_ratio": peak_ratio, "ramp": ramp,
            "weekday": _weekday(comp["day_start"])}


def smooth(values, window):
    if window <= 1 or len(values) < 3:
        return list(values)
    half = window // 2
    out = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def round2(x):
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if float(value).is_integer() else value


def forecast_case(case):
    levels = case["levels"]
    zscores = [_NORM.inv_cdf(tau) for tau in levels]
    first = next(k for k in case["known"] if k["hour"] == 1)
    p1 = max(1.0, float(first["viewers"]))
    target_name = case.get("game", {}).get("name", "")
    target_weekday = _weekday(case["day_start"])
    forecast_hours = [row["hour"] for row in case["forecast"]]

    profiles = []
    for comp in case.get("comparables", []):
        prof = comparable_profile(comp, target_name)
        if prof is not None:
            profiles.append(prof)

    # Two regimes.  A target whose hour 1 already holds a large audience is
    # a rolling midnight launch: learn only from comparables that were also
    # unlocked by hour 1 (the capped pool).  A target with a small hour 1
    # may still be locked (a single-time unlock later in the UTC day): then
    # the cap would throw away exactly the comparables that behave that
    # way, so pool them all and let the pre-midnight ramp kernel (how fast
    # the audience was already rising into hour 1) do the separating.
    prev_target = previous_hour_viewers(case.get("history_hourly", []),
                                        case["day_start"])
    target_ramp = math.log(p1 / max(1.0, prev_target)) if prev_target else 0.0
    small_target = p1 < SMALL_TARGET_P1
    if small_target:
        pool = profiles
    else:
        pool = [p for p in profiles if p["peak_ratio"] <= PEAK_RATIO_CAP]
        if len(pool) < 5:
            pool = profiles

    rows = []
    if pool:
        weights = []
        for prof in pool:
            d = (math.log(prof["p1"]) - math.log(p1)) / SIZE_BANDWIDTH
            w = math.exp(-0.5 * d * d) + WEIGHT_FLOOR
            if prof["weekday"] == target_weekday:
                w *= WEEKDAY_BOOST
            if small_target:
                dr = (prof["ramp"] - target_ramp) / RAMP_BANDWIDTH
                w *= math.exp(-0.5 * dr * dr) + WEIGHT_FLOOR
            weights.append(w)
        means, sds = [], []
        for h in forecast_hours:
            pairs = [(math.log(prof["hours"][h] / prof["p1"]), w)
                     for prof, w in zip(pool, weights) if h in prof["hours"]]
            if len(pairs) < 3:
                means.append(0.0)
                sds.append(FALLBACK_SIGMA * math.sqrt(h - 1))
                continue
            total = sum(w for _, w in pairs)
            mean = sum(v * w for v, w in pairs) / total
            var = sum(w * (v - mean) ** 2 for v, w in pairs) / total
            means.append(mean)
            sds.append(math.sqrt(max(var, 1e-4)))
        means = smooth(means, SMOOTH_WINDOW)
        sds = smooth(sds, SMOOTH_WINDOW)
        for i, h in enumerate(forecast_hours):
            qs = [p1 * math.exp(means[i] + z * sds[i]) for z in zscores]
            rows.append({"hour": h, "q": [round2(min(max(q, 0.01), 1e9))
                                           for q in sorted(qs)]})
    else:
        for h in forecast_hours:
            sigma = FALLBACK_SIGMA * math.sqrt(h - 1)
            qs = [p1 * math.exp(z * sigma) for z in zscores]
            rows.append({"hour": h, "q": [round2(min(max(q, 0.01), 1e9))
                                           for q in sorted(qs)]})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
