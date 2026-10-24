#!/usr/bin/env python3
"""Print how long one event rotation lasts and how the time splits between events.

    python3 loop_length.py <path/to/game.json>

Expects {"cycle": {"waiting_seconds", "settle_seconds", "rotation": [{"kind", "seconds"}]}}.
Use it before and after changing durations; the main event (e.g. invasion) should take
about half the loop or more, and the loop should match the competitor's (about 30 minutes).
"""
import json
import sys
from collections import defaultdict


def main() -> int:
    cycle = json.load(open(sys.argv[1], encoding="utf-8"))["cycle"]
    rotation = cycle["rotation"]
    gap = float(cycle.get("waiting_seconds", 0)) + float(cycle.get("settle_seconds", 0))
    by_kind = defaultdict(lambda: [0, 0.0])
    for entry in rotation:
        by_kind[entry["kind"]][0] += 1
        by_kind[entry["kind"]][1] += float(entry["seconds"])
    events = sum(total for _, total in by_kind.values())
    gaps = gap * len(rotation)
    loop = events + gaps
    print(f"一轮 {loop / 60:.1f} 分钟（事件 {events:.0f} 秒 + 等待/结算 {gaps:.0f} 秒，共 {len(rotation)} 场）")
    for kind, (count, total) in sorted(by_kind.items(), key=lambda item: -item[1][1]):
        print(f"  {kind:<10} {count} 场 × {total / count:.0f} 秒 = {total:.0f} 秒  占 {total / loop * 100:.0f}%")
    print(f"  {'等待/结算':<8} {gaps:.0f} 秒  占 {gaps / loop * 100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
