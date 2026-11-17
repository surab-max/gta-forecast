"""Third-round CV: add a pre-midnight ramp-shape kernel.

For each comparable we take the six hours before its release day
(18:00..23:00 UTC of the day before), expressed as log(viewers / p1).  The
target case exposes the same window through history_hourly, so a shipped
program can compute the identical feature for the target.  Comparables whose
run-up shape matches the target's (steep rolling-unlock ramp vs flat
early-access plateau vs pre-unlock trickle) get more weight.
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
        by_stamp = {row["from"]: row["viewers"] for row in comp["hourly"] if row["viewers"]}
        hours = {}
        for stamp, v in by_stamp.items():
            if stamp[:10] == start[:10]:
                hours[int(stamp[11:13]) + 1] = float(v)
        if 1 not in hours or len(hours) < 18:
            continue
        p1 = max(1.0, hours[1])
        # hours -6..-1: stamps on the previous day at 18..23
        import datetime as dt
        day0 = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
        ramp = []
        ok = True
        for back in range(6, 0, -1):
            stamp = (day0 - dt.timedelta(hours=back)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if stamp in by_stamp:
                ramp.append(math.log(max(1.0, by_stamp[stamp]) / p1))
            else:
                ok = False
                break
        comps.append({"name": comp["name"], "hours": hours, "p1": p1,
                      "peak_ratio": max(hours.values()) / p1,
                      "ramp_vec": ramp if ok else None})
    return comps


def smooth(vals, window):
    if window <= 1:
        return list(vals)
    half = window // 2
    return [sum(vals[max(0, i - half):min(len(vals), i + half + 1)]) /
            (min(len(vals), i + half + 1) - max(0, i - half)) for i in range(len(vals))]


def forecast(target, pool, peak_cap=6.0, bw_size=0.75, bw_shape=None, spread=1.0):
    usable = [c for c in pool if c["peak_ratio"] <= peak_cap]
    if len(usable) < 5:
        usable = list(pool)
    weights = []
    for c in usable:
        d = (math.log(c["p1"]) - math.log(target["p1"])) / bw_size
        w = math.exp(-0.5 * d * d) + 0.05
        if bw_shape and c["ramp_vec"] and target["ramp_vec"]:
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(c["ramp_vec"], target["ramp_vec"])) / 6.0)
            w *= math.exp(-0.5 * (dist / bw_shape) ** 2) + 0.02
        weights.append(w)
    hours = list(range(2, 25))
    med, sig = [], []
    for h in hours:
        pairs = [(math.log(c["hours"][h] / c["p1"]), w)
                 for c, w in zip(usable, weights) if h in c["hours"]]
        tot = sum(w for _, w in pairs)
        mean = sum(v * w for v, w in pairs) / tot
        var = sum(w * (v - mean) ** 2 for v, w in pairs) / tot
        med.append(mean)
        sig.append(math.sqrt(var))
    med = smooth(med, 3)
    sig = smooth(sig, 3)
    return {h: sorted(target["p1"] * math.exp(med[i] + z * sig[i] * spread) for z in Z)
            for i, h in enumerate(hours)}


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
    print("with ramp_vec:", sum(1 for c in comps if c["ramp_vec"]))
    clean = lambda t: t["peak_ratio"] <= 4 and t["p1"] >= 20000
    for label, kw in [
        ("base bw0.75 peak6", dict()),
        ("shape1.0", dict(bw_shape=1.0)),
        ("shape0.7", dict(bw_shape=0.7)),
        ("shape0.5", dict(bw_shape=0.5)),
        ("shape0.35", dict(bw_shape=0.35)),
        ("shape0.5 bw1.25", dict(bw_shape=0.5, bw_size=1.25)),
        ("shape0.5 peakInf", dict(bw_shape=0.5, peak_cap=1e9)),
        ("shape0.35 peakInf", dict(bw_shape=0.35, peak_cap=1e9)),
    ]:
        print(f"clean {evaluate(comps, clean, **kw):.4f}  {label}")


if __name__ == "__main__":
    main()
