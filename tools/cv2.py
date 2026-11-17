"""Second-round CV: parametric (lognormal) vs empirical quantiles, median
shrinkage toward persistence, and a second kernel dimension from the target's
own pre-midnight ramp (hour-1 print vs the previous hour's viewers).

The ramp matters because the comparables mix two regimes: rolling midnight
launches, whose hour 1 is already a real audience, and single-time global
unlocks, whose hour 1 is a pre-unlock trickle.  p1 alone partly separates
them; log(p1 / previous hour) separates them directly.
"""
import json
import math
from pathlib import Path

KIT_INPUT = Path.home() / "workspace/makefun/forecast-kit/gta6-twitch-ccu-forecast-01-kit/input"
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]


def load():
    case = json.loads((KIT_INPUT / "p00.in").read_text())
    comps = []
    for comp in case["comparables"]:
        start = comp["day_start"]
        hours, prev = {}, None
        for row in comp["hourly"]:
            stamp = row["from"]
            if stamp[:10] == start[:10] and row["viewers"]:
                hours[int(stamp[11:13]) + 1] = float(row["viewers"])
            if stamp == start[:10] + "T00:00:00Z":
                pass
        # previous hour = the hour ending at day_start: stamp day-1 23:00
        for row in comp["hourly"]:
            if row["from"][11:13] == "23" and row["viewers"]:
                # keep the last 23:00 before day_start
                if row["from"] < start:
                    prev = float(row["viewers"])
        if 1 not in hours or len(hours) < 18:
            continue
        p1 = max(1.0, hours[1])
        comps.append({"name": comp["name"], "hours": hours, "p1": p1,
                      "peak_ratio": max(hours.values()) / p1,
                      "ramp": math.log(p1 / max(1.0, prev)) if prev else 0.0})
    return comps


def wquantile(pairs, tau):
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc / total >= tau:
            return v
    return pairs[-1][0]


def smooth(vals, window):
    if window <= 1:
        return list(vals)
    half = window // 2
    return [sum(vals[max(0, i - half):min(len(vals), i + half + 1)]) /
            (min(len(vals), i + half + 1) - max(0, i - half)) for i in range(len(vals))]


def forecast(target, pool, peak_cap=6.0, bw_size=1.0, bw_ramp=None,
             method="normal", shrink=1.0, spread=1.0, qsmooth=3):
    usable = [c for c in pool if c["peak_ratio"] <= peak_cap]
    if len(usable) < 5:
        usable = list(pool)
    weights = []
    for c in usable:
        d = (math.log(c["p1"]) - math.log(target["p1"])) / bw_size
        w = math.exp(-0.5 * d * d) + 0.05
        if bw_ramp:
            dr = (c["ramp"] - target["ramp"]) / bw_ramp
            w *= math.exp(-0.5 * dr * dr) + 0.05
        weights.append(w)
    hours = list(range(2, 25))
    med, sig = [], []
    emp = []
    for h in hours:
        pairs = [(math.log(c["hours"][h] / c["p1"]), w)
                 for c, w in zip(usable, weights) if h in c["hours"]]
        tot = sum(w for _, w in pairs)
        mean = sum(v * w for v, w in pairs) / tot
        var = sum(w * (v - mean) ** 2 for v, w in pairs) / tot
        med.append(mean)
        sig.append(math.sqrt(var))
        emp.append([wquantile(pairs, t) for t in LEVELS])
    med = smooth([m * shrink for m in med], qsmooth)
    sig = smooth(sig, qsmooth)
    out = {}
    for i, h in enumerate(hours):
        if method == "normal":
            qs = [target["p1"] * math.exp(med[i] + z * sig[i] * spread) for z in Z]
        else:
            centre = emp[i][2]
            qs = [target["p1"] * math.exp(med[i] + (e - centre) * spread) for e in emp[i]]
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
    return total / max(1, n)


def evaluate(comps, filt, **kw):
    losses = []
    for t in comps:
        if not filt(t):
            continue
        pool = [c for c in comps if c["name"] != t["name"]]
        losses.append(pinball(t, forecast(t, pool, **kw)))
    return sum(losses) / len(losses)


def main():
    comps = load()
    clean = lambda t: t["peak_ratio"] <= 4 and t["p1"] >= 20000
    allf = lambda t: True
    for label, kw in [
        ("normal bw1 peak6", dict()),
        ("normal bw1 peak6 shrink0.9", dict(shrink=0.9)),
        ("normal bw1 peak6 shrink0.8", dict(shrink=0.8)),
        ("normal bw1 peak6 spread0.9", dict(spread=0.9)),
        ("normal bw1 peak6 spread1.1", dict(spread=1.1)),
        ("normal bw0.75 peak6", dict(bw_size=0.75)),
        ("normal bw1.5 peak6", dict(bw_size=1.5)),
        ("normal bw1 peak6 ramp1.0", dict(bw_ramp=1.0)),
        ("normal bw1 peak6 ramp0.6", dict(bw_ramp=0.6)),
        ("normal bw1 peakInf ramp0.6", dict(peak_cap=1e9, bw_ramp=0.6)),
        ("normal bw1 peakInf ramp1.0", dict(peak_cap=1e9, bw_ramp=1.0)),
        ("normal bw1 peakInf", dict(peak_cap=1e9)),
        ("emp bw1 peak6", dict(method="emp")),
        ("emp bw1 peak6 ramp0.6", dict(method="emp", bw_ramp=0.6)),
        ("emp bw1 peakInf ramp0.6", dict(method="emp", peak_cap=1e9, bw_ramp=0.6)),
    ]:
        print(f"clean {evaluate(comps, clean, **kw):.4f}   all {evaluate(comps, allf, **kw):.4f}   {label}")


if __name__ == "__main__":
    main()
