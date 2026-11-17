"""Exploration of the practice cases' comparables (run locally, not by the grader).

Prints, for every comparable in p00: its release-day hour-1 viewers, its peak
hour on release day, the peak / hour-1 ratio, how many release-day hours are
present, and the start of its free-text unlock description.  This is the table
the modelling choices in docs/MODEL.md were read off.
"""
import json
import math
from pathlib import Path

KIT_INPUT = Path.home() / "workspace/makefun/forecast-kit/gta6-twitch-ccu-forecast-01-kit/input"


def parse_day(case):
    return case["day_start"][:10]


def day_hours(comp):
    """Map hour-of-release-day (1..24) -> viewers for one comparable."""
    start = comp["day_start"]
    out = {}
    for row in comp["hourly"]:
        stamp = row["from"]
        if stamp[:10] != start[:10]:
            continue
        hour = int(stamp[11:13]) + 1
        if row["viewers"] is not None:
            out[hour] = row["viewers"]
    return out


def main():
    case = json.loads((KIT_INPUT / "p00.in").read_text())
    rows = []
    for comp in case["comparables"]:
        hours = day_hours(comp)
        if 1 not in hours or len(hours) < 12:
            rows.append((comp["name"], None, None, len(hours), comp["unlock"][:110]))
            continue
        p1 = max(1, hours[1])
        peak_h = max(hours, key=lambda h: hours[h])
        rows.append((comp["name"], p1, round(hours[peak_h] / p1, 2), len(hours),
                     f"peak h{peak_h} | " + comp["unlock"][:90]))
    for name, p1, ratio, n, unlock in rows:
        print(f"{name:45s} p1={p1} peak_ratio={ratio} hours={n} {unlock}")


if __name__ == "__main__":
    main()
