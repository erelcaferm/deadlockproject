"""Command line entry point.

Example:
    python -m deadlock_helper Haze --enemies "Lash, Seven, Abrams, Mo & Krill, Bebop, Wraith"
"""

from __future__ import annotations

import argparse

from .api import DeadlockAPI
from .recommender import Recommendation, recommend

TIER_COST = {1: "800", 2: "1600", 3: "3200", 4: "6400"}


def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def format_recommendation(rec: Recommendation) -> str:
    lines = [f"=== {rec.hero} ===" + (f"  vs  {', '.join(rec.enemies)}" if rec.enemies else "")]

    lines.append("\nHow to play")
    lines += [f"  - {n}" for n in rec.playstyle] or ["  (no notes yet)"]

    lines.append("\nAbility to max (first to last)")
    if rec.ability_max_order:
        lines += [f"  {i}. {name}" for i, name in enumerate(rec.ability_max_order, 1)]
        lines.append(f"  based on {rec.ability_order_matches} games, {rec.ability_order_win_rate:.0%} win rate")
    else:
        lines.append("  (not enough data)")

    if rec.ability_steps:
        lines.append("\nAbility points, step by step")
        for st in rec.ability_steps:
            key = f"[{st.key}]" if st.key else "   "
            when = f"~{_mmss(st.avg_time_s)}" if st.avg_time_s is not None else "late"
            lines.append(f"  {st.step:>2}. {when:>6}  {key} {st.ability:<20} {st.action:<7} {st.effect}")

    lines.append("\nCore items by tier")
    for tier, picks in rec.core_items.items():
        lines.append(f"  Tier {tier} ({TIER_COST.get(tier, '?')} souls)")
        lines += [f"    {p.name:<28} {p.slot:<9} {p.win_rate:.1%}  ({p.matches} games)" for p in picks]

    if rec.counter_items:
        lines.append("\nGood against this enemy team")
        lines += [f"    {p.name:<28} {p.note}" for p in rec.counter_items]

    if rec.matchups:
        lines.append("\nYour matchups")
        lines += [f"    vs {name:<16} {wr:.0%}  ({m} games)" for name, wr, m in rec.matchups]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deadlock build and playstyle suggestions")
    parser.add_argument("hero", help="your hero, e.g. Haze")
    parser.add_argument("--enemies", default="", help="comma separated enemy heroes")
    parser.add_argument("--min-badge", type=int, default=None,
                        help="only use games at or above this average badge (rank) level")
    args = parser.parse_args()
    enemies = [e.strip() for e in args.enemies.split(",") if e.strip()]
    print(format_recommendation(recommend(DeadlockAPI(), args.hero, enemies, args.min_badge)))


if __name__ == "__main__":
    main()
