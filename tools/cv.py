"""Leave-one-out cross-validation over the comparables in practice case p00.

Each comparable with a usable release day becomes a pseudo-target in turn: we
pretend only its hour-1 print is known, forecast hours 2..24 with the other
comparables, and score with the contest's pinball loss on the log scale.
This is the honest local proxy for the practice grade: the practice launches
themselves are excluded from every case's comparables, so their answers are
not available locally, but the comparables are the same population the shipped
program learns its shape from.

Usage: python3 tools/cv.py [variant ...]   (default: a grid of variants)
"""
import itertools
import json
import math
import sys
from pathlib import Path

KIT_INPUT = Path.home() / "workspace/makefun/forecast-kit/gta6-twitch-ccu-forecast-01-kit/input"
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]


def day_hours(comp):
    start = comp["day_start"][:10]
    out = {}
    for row in comp["hourly"]:
        if row["from"][:10] != start:
            continue
        hour = int(row["from"][11:13]) + 1
        if row["viewers"]:
            out[hour] = float(row["viewers"])
    return out


def load_comps():
    case = json.loads((KIT_INPUT / "p00.in").read_text())
    comps = []
    for comp in case["comparables"]:
        hours = day_hours(comp)
        if 1 not in hours or len(hours) < 18:
            continue
        p1 = max(1.0, hours[1])
        peak = max(hours.values())
        comps.append({"name": comp["name"], "hours": hours, "p1": p1,
                      "peak_ratio": peak / p1})
    return comps


def weighted_quantile(sorted_pairs, tau):
    """Smallest value whose cumulative weight reaches tau (pairs pre-sorted)."""
    total = sum(w for _, w in sorted_pairs)
    if total <= 0:
        return sorted_pairs[len(sorted_pairs) // 2][0]
    acc = 0.0
    for value, w in sorted_pairs:
        acc += w
        if acc / total >= tau:
            return value
    return sorted_pairs[-1][0]


def smooth(values, window):
    if window <= 1:
        return list(values)
    half = window // 2
    out = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def forecast(target, pool, max_peak_ratio, bandwidth, spread_scale,
             median_smooth, quantile_smooth, min_p1):
    """Return {hour: [q05..q95]} for target using pool of comparables."""
    usable = [c for c in pool
              if c["peak_ratio"] <= max_peak_ratio and c["p1"] >= min_p1]
    if len(usable) < 5:  # fall back to the whole pool rather than nothing
        usable = list(pool)
    log_p1 = math.log(target["p1"])
    weights = {}
    for c in usable:
        if bandwidth == float("inf"):
            weights[c["name"]] = 1.0
        else:
            d = (math.log(c["p1"]) - log_p1) / bandwidth
            weights[c["name"]] = math.exp(-0.5 * d * d) + 0.05
    hours = list(range(2, 25))
    per_hour = {}
    for h in hours:
        pairs = []
        for c in usable:
            if h in c["hours"]:
                pairs.append((math.log(c["hours"][h] / c["p1"]), weights[c["name"]]))
        pairs.sort()
        per_hour[h] = [weighted_quantile(pairs, tau) for tau in LEVELS]
    # Smooth each quantile curve across neighbouring hours (log-ratio space).
    for qi in range(5):
        curve = smooth([per_hour[h][qi] for h in hours], quantile_smooth)
        for h, v in zip(hours, curve):
            per_hour[h][qi] = v
    medians = smooth([per_hour[h][2] for h in hours], median_smooth)
    out = {}
    for h, med in zip(hours, medians):
        qs = []
        for qi in range(5):
            centre = per_hour[h][2]
            spread = (per_hour[h][qi] - centre) * spread_scale
            log_q = med + spread if qi != 2 else med
            qs.append(target["p1"] * math.exp(log_q))
        qs.sort()
        out[h] = qs
    return out


def pinball(target, fc):
    total, n = 0.0, 0
    for h, qs in fc.items():
        if h not in target["hours"]:
            continue
        y = max(1.0, target["hours"][h])
        for tau, q in zip(LEVELS, qs):
            d = math.log(y) - math.log(max(q, 1e-9))
            total += 2.0 * max(tau * d, (tau - 1.0) * d)
            n += 1
    return total / max(1, n), n


def baseline(target):
    out = {}
    for h in range(2, 25):
        out[h] = [target["p1"] * math.exp(z * 0.15 * math.sqrt(h - 1)) for z in Z]
    return out


def run_variant(comps, **kw):
    losses = []
    for target in comps:
        pool = [c for c in comps if c["name"] != target["name"]]
        fc = forecast(target, pool, **kw)
        loss, _ = pinball(target, fc)
        losses.append(loss)
    return sum(losses) / len(losses)


def main():
    comps = load_comps()
    print(f"{len(comps)} usable comparables")
    base = sum(pinball(t, baseline(t))[0] for t in comps) / len(comps)
    print(f"baseline persistence: {base:.4f}")
    grid = []
    for peak, bw, spread, ms, qs, minp1 in itertools.product(
            [3.0, 4.0, 6.0, 10.0, 1e9],
            [float("inf"), 2.0, 1.25],
            [0.85, 1.0, 1.15],
            [1, 3],
            [1, 3],
            [0, 10000]):
        grid.append((peak, bw, spread, ms, qs, minp1))
    results = []
    wanted = sys.argv[1:]
    for peak, bw, spread, ms, qs, minp1 in grid:
        label = f"peak<={peak} bw={bw} spread={spread} medsmooth={ms} qsmooth={qs} minp1={minp1}"
        if wanted and not any(w in label for w in wanted):
            continue
        loss = run_variant(comps, max_peak_ratio=peak, bandwidth=bw,
                           spread_scale=spread, median_smooth=ms,
                           quantile_smooth=qs, min_p1=minp1)
        results.append((loss, label))
    for loss, label in sorted(results)[:25]:
        print(f"{loss:.4f}  {label}")


if __name__ == "__main__":
    main()
