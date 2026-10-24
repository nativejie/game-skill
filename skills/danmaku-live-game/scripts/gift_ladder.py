#!/usr/bin/env python3
"""Check a live game's gift table: does the effect grow with the price, and stay capped?

A gift that is cheap but strong lets one viewer buy the whole room's ranking; a gift that
costs more but shows less than a cheaper one feels like a scam to the sender. This prints the
ladder and reports both, without running the engine.

    python3 gift_ladder.py <gifts.json> [--cap-hours 3] [--entry-price 1]

Expects {"gifts": [{"id", "price", "effect_hours", "visibility"}]}:
  price         platform price (e.g. 抖币);
  effect_hours  the effect's strength as hours of a free player's income;
  visibility    one of seat < banner < half < full < ceremony.
Reports (exit code 1):
  - effect_hours or visibility going down while the price goes up;
  - effect_hours above --cap-hours (pay more for visibility, not for power);
  - no gift at or below --entry-price (everyone needs a way to join in).
Warns (exit code 0): a pricier gift giving more hours per coin than a cheaper one.
"""
import argparse
import json
import sys

VISIBILITY = ["seat", "banner", "half", "full", "ceremony"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gifts")
    parser.add_argument("--cap-hours", type=float, default=3.0)
    parser.add_argument("--entry-price", type=float, default=1.0)
    args = parser.parse_args()

    with open(args.gifts, encoding="utf-8") as handle:
        gifts = sorted(json.load(handle)["gifts"], key=lambda gift: float(gift["price"]))
    problems: list[str] = []
    warnings: list[str] = []

    print(f"{'礼物':<16}{'价格':>8}{'效果(小时)':>12}{'小时/价格':>12}  可见度")
    previous = None
    for gift in gifts:
        price = float(gift["price"])
        hours = float(gift["effect_hours"])
        visibility = gift["visibility"]
        if visibility not in VISIBILITY:
            problems.append(f"{gift['id']}: 可见度 {visibility!r} 不在 {VISIBILITY} 里")
            continue
        per_coin = hours / price if price > 0 else 0.0
        print(f"{gift['id']:<16}{price:>8g}{hours:>12g}{per_coin:>12.4f}  {visibility}")
        if hours > args.cap_hours:
            problems.append(f"{gift['id']}: 效果 {hours:g} 小时超过上限 {args.cap_hours:g}，多出的价值改给可见度和身份")
        if previous is not None and price > float(previous["price"]):
            if hours < float(previous["effect_hours"]):
                problems.append(f"{gift['id']}: 比 {previous['id']} 贵，效果反而更弱")
            if VISIBILITY.index(visibility) < VISIBILITY.index(previous["visibility"]):
                problems.append(f"{gift['id']}: 比 {previous['id']} 贵，可见度反而更低")
            previous_per_coin = float(previous["effect_hours"]) / float(previous["price"])
            if per_coin > previous_per_coin * 1.2:
                warnings.append(f"{gift['id']}: 每单位价格的效果比 {previous['id']} 高 {per_coin / previous_per_coin - 1:.0%}，大额礼物性价比越来越高会把排名变成比谁送得多")
        previous = gift

    if not any(float(gift["price"]) <= args.entry_price for gift in gifts):
        problems.append(f"没有价格 ≤ {args.entry_price:g} 的入门礼物")

    for line in warnings:
        print(f"警告  {line}")
    for line in problems:
        print(f"问题  {line}")
    if not problems:
        print("通过")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
