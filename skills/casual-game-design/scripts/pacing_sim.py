#!/usr/bin/env python3
"""Monte Carlo pacing simulator for short-session games.

Simulates many players over a few hours from a JSON spec and reports what makes numbers
boring or frustrating: how long until the first "good moment", the longest stretch without
one (for the unluckiest 10%), time to key levels, level-ups per hour, currency build-up, and
how often pity timers fire. Engine-independent; see assets/example_spec.json for the format.

    python3 pacing_sim.py spec.json [--players 300] [--hours 3] [--seed 1]

Model (kept simple on purpose):
  - Rewards are fractions of the current level's requirement (xp_fraction), so the curve
    (xp_growth) only changes how big numbers look, not how fast levels come.
  - "continuous" sources pay every step (passive income). Other sources fire randomly with
    an average interval `every_seconds`, succeed with `chance`, and may have `pity`
    (guaranteed on the Nth try since the last success).
  - Every `gate.every` levels the player must break through: one try every
    `attempt_every_seconds`, success by realm, failure loses part of the progress.
  - Sinks buy as soon as the balance allows (up to `max_buys`).
  - A "moment" is anything the spec marks as one (level-up, gate passed, rare drop, purchase).
"""
import argparse
import json
import math
import random
import statistics
import sys


def pct(values, q):
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def fmt_minutes(seconds):
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return "—"
    return f"{seconds / 60:.1f}"


class Player:
    def __init__(self, spec, rng):
        self.rng = rng
        self.level = 1
        self.progress = 0.0  # fraction of the current level
        self.balance = {c: 0.0 for c in spec.get("currencies", [])}
        self.earned = {c: 0.0 for c in self.balance}
        self.spent = {c: 0.0 for c in self.balance}
        self.misses = {s["name"]: 0 for s in spec["sources"]}
        self.pity_hits = {s["name"]: 0 for s in spec["sources"]}
        self.successes = {s["name"]: 0 for s in spec["sources"]}
        self.buys = {k["name"]: 0 for k in spec.get("sinks", [])}
        self.moments = []  # seconds
        self.level_times = {}  # level -> seconds reached
        self.level_ups = []  # seconds
        self.next_attempt = 0.0


def run_player(spec, rng, seconds, step):
    p = Player(spec, rng)
    level_cfg = spec["level"]
    max_level = int(level_cfg["max"])
    growth = float(level_cfg.get("xp_growth", 1.0))
    gate = level_cfg.get("gate")
    moments_cfg = spec.get("moments", {"level_up": True, "gate": True})
    bonus = 1.0 + float(spec.get("xp_bonus", 0.0))
    p.level_times[1] = 0.0
    t = 0.0
    while t < seconds:
        t += step
        for source in spec["sources"]:
            if source.get("continuous"):
                gain = float(source.get("xp_fraction", 0.0)) * step / float(source["every_seconds"])
                p.progress += gain * bonus
                continue
            if rng.random() >= step / float(source["every_seconds"]):
                continue
            pity = int(source.get("pity", 0))
            hit = rng.random() < float(source.get("chance", 1.0))
            if not hit and pity > 0 and p.misses[source["name"]] + 1 >= pity:
                hit = True
                p.pity_hits[source["name"]] += 1
            if not hit:
                p.misses[source["name"]] += 1
                continue
            p.misses[source["name"]] = 0
            p.successes[source["name"]] += 1
            p.progress += float(source.get("xp_fraction", 0.0)) * bonus
            for currency, amount in source.get("currency", {}).items():
                value = rng.uniform(amount[0], amount[1]) if isinstance(amount, list) else float(amount)
                p.balance[currency] = p.balance.get(currency, 0.0) + value
                p.earned[currency] = p.earned.get(currency, 0.0) + value
            if source.get("moment"):
                p.moments.append(t)
        # Level-ups, with breakthrough gates at every `gate.every` levels.
        while p.level < max_level and p.progress >= 1.0:
            at_gate = gate is not None and p.level % int(gate["every"]) == 0
            if at_gate:
                p.progress = min(p.progress, 1.0)
                if t < p.next_attempt:
                    break
                p.next_attempt = t + float(gate.get("attempt_every_seconds", 30))
                realm = p.level // int(gate["every"])
                rates = gate["success"]
                losses = gate.get("fail_loss", [0.0] * len(rates))
                if rng.random() >= float(rates[min(realm, len(rates) - 1)]):
                    p.progress -= float(losses[min(realm, len(losses) - 1)]) * p.progress
                    break
                if moments_cfg.get("gate", True):
                    p.moments.append(t)
            p.level += 1
            p.progress = (p.progress - 1.0) / growth if growth > 0 else 0.0
            p.progress = max(0.0, p.progress)
            p.level_times[p.level] = t
            p.level_ups.append(t)
            if moments_cfg.get("level_up", True):
                p.moments.append(t)
        if p.level >= max_level:
            p.progress = 0.0
        for sink in spec.get("sinks", []):
            currency = sink["currency"]
            if p.buys[sink["name"]] < int(sink.get("max_buys", 1)) and p.balance.get(currency, 0.0) >= float(sink["price"]):
                p.balance[currency] -= float(sink["price"])
                p.spent[currency] = p.spent.get(currency, 0.0) + float(sink["price"])
                p.buys[sink["name"]] += 1
                if sink.get("moment", True):
                    p.moments.append(t)
        if int(t) % 3600 < step:
            p.__dict__.setdefault("hourly_balance", []).append(dict(p.balance))
    return p


def longest_gap(moments, seconds):
    marks = [0.0] + sorted(moments) + [seconds]
    return max(b - a for a, b in zip(marks, marks[1:]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spec")
    parser.add_argument("--players", type=int, default=None)
    parser.add_argument("--hours", type=float, default=None)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    spec = json.load(open(args.spec, encoding="utf-8"))
    players = args.players or int(spec.get("players", 300))
    hours = args.hours or float(spec.get("hours", 3))
    seconds = hours * 3600
    step = float(spec.get("step_seconds", 5))
    rng = random.Random(args.seed)
    results = [run_player(spec, rng, seconds, step) for _ in range(players)]
    warn = spec.get("warnings", {})
    warnings = []

    print(f"# 节奏模拟：{spec.get('name', args.spec)}")
    print(f"{players} 名玩家 × {hours:g} 小时，步长 {step:g} 秒，种子 {args.seed}。「慢 10%」= 最倒霉 / 最慢的 10% 玩家。\n")

    first = [min(p.moments) if p.moments else seconds for p in results]
    gaps = [longest_gap(p.moments, seconds) for p in results]
    print("## 好事节奏")
    print(f"- 第一次好事：中位 {fmt_minutes(statistics.median(first))} 分钟，慢 10% {fmt_minutes(pct(first, 0.9))} 分钟")
    print(f"- 最长没好事：中位 {fmt_minutes(statistics.median(gaps))} 分钟，慢 10% {fmt_minutes(pct(gaps, 0.9))} 分钟")
    per_hour = [len(p.moments) / hours for p in results]
    print(f"- 每小时好事次数：中位 {statistics.median(per_hour):.1f}")
    if pct(first, 0.9) > float(warn.get("first_moment_minutes", 3)) * 60:
        warnings.append(f"慢 10% 的玩家要 {fmt_minutes(pct(first, 0.9))} 分钟才有第一次好事（目标 ≤ {warn.get('first_moment_minutes', 3)}）")
    if pct(gaps, 0.9) > float(warn.get("max_dry_minutes", 10)) * 60:
        warnings.append(f"慢 10% 的玩家最长 {fmt_minutes(pct(gaps, 0.9))} 分钟没有好事（目标 ≤ {warn.get('max_dry_minutes', 10)}）")

    print("\n## 等级")
    final = [p.level for p in results]
    print(f"- {hours:g} 小时后等级：中位 {statistics.median(final):g}，慢 10% {pct(final, 0.1):g}，快 10% {pct(final, 0.9):g}")
    ups = [len(p.level_ups) / hours for p in results]
    print(f"- 每小时升级：中位 {statistics.median(ups):.1f} 次")
    intervals = []
    for p in results:
        marks = p.level_ups
        intervals.extend(b - a for a, b in zip(marks, marks[1:]))
    if intervals:
        print(f"- 升级间隔：中位 {fmt_minutes(statistics.median(intervals))} 分钟，慢 10% {fmt_minutes(pct(intervals, 0.9))} 分钟")
        low, high = warn.get("level_minutes_range", [2, 15])
        median_interval = statistics.median(intervals) / 60
        if median_interval < low:
            warnings.append(f"升级太快：中位 {median_interval:.1f} 分钟一级（目标 {low}–{high}）")
        if median_interval > high:
            warnings.append(f"升级太慢：中位 {median_interval:.1f} 分钟一级（目标 {low}–{high}）")
    milestones = spec.get("milestone_levels", [])
    if milestones:
        print("\n| 等级 | 到达比例 | 中位到达（分钟） | 慢 10%（分钟） |\n|---|---|---|---|")
        for level in milestones:
            times = [p.level_times[level] for p in results if level in p.level_times]
            share = len(times) / players
            slow = pct(times, 0.9) if share >= 0.9 else None
            print(f"| {level} | {share * 100:.0f}% | {fmt_minutes(statistics.median(times)) if times else '—'} | {fmt_minutes(slow) if slow is not None else '未全到'} |")
        target = spec.get("target_level_at_end")
        if target and statistics.median(final) > target * 1.3:
            warnings.append(f"成长太快：{hours:g} 小时中位等级 {statistics.median(final):g}，目标约 {target}")
        if target and statistics.median(final) < target * 0.7:
            warnings.append(f"成长太慢：{hours:g} 小时中位等级 {statistics.median(final):g}，目标约 {target}")

    print("\n## 掉落与保底")
    for source in spec["sources"]:
        if source.get("continuous") or float(source.get("chance", 1.0)) >= 1.0:
            continue
        name = source["name"]
        got = [p.successes[name] for p in results]
        never = sum(1 for g in got if g == 0) / players
        pity = sum(p.pity_hits[name] for p in results)
        total = sum(got)
        line = f"- {name}：人均 {statistics.mean(got):.1f} 次，{never * 100:.0f}% 的人一次都没有"
        if source.get("pity"):
            share = pity / total if total else 0.0
            line += f"，保底触发占 {share * 100:.0f}%"
            if share > 0.3:
                warnings.append(f"{name} 的保底触发占 {share * 100:.0f}%：概率可能太低，大家都靠保底")
        print(line)
        if source.get("moment") and never > 0.25:
            warnings.append(f"{name}：{never * 100:.0f}% 的玩家 {hours:g} 小时里一次都没有")

    if spec.get("currencies"):
        print("\n## 货币")
        print("| 货币 | 每小时收入（中位） | 消耗占收入 | 结束余额（中位） | 每小时余额 |\n|---|---|---|---|---|")
        for currency in spec["currencies"]:
            earned = [p.earned.get(currency, 0.0) for p in results]
            spent = [p.spent.get(currency, 0.0) for p in results]
            end = [p.balance.get(currency, 0.0) for p in results]
            hourly = []
            for h in range(len(results[0].__dict__.get("hourly_balance", []))):
                hourly.append(statistics.median(p.hourly_balance[h].get(currency, 0.0) for p in results if len(p.hourly_balance) > h))
            ratio = sum(spent) / sum(earned) if sum(earned) else 0.0
            print(f"| {currency} | {statistics.median(earned) / hours:.0f} | {ratio * 100:.0f}% | {statistics.median(end):.0f} | {' → '.join(f'{v:.0f}' for v in hourly)} |")
            if sum(earned) and ratio < float(warn.get("min_spend_ratio", 0.3)):
                warnings.append(f"{currency} 只花掉了收入的 {ratio * 100:.0f}%：消耗不够，会越攒越多")
        for sink in spec.get("sinks", []):
            bought = [p.buys[sink["name"]] for p in results]
            reached = sum(1 for b in bought if b > 0) / players
            print(f"- {sink['name']}（{sink['price']:g} {sink['currency']}）：{reached * 100:.0f}% 的人买到")

    print("\n## 警告")
    if warnings:
        for line in warnings:
            print(f"- {line}")
    else:
        print("- 无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
