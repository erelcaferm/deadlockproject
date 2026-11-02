"""Entry point. With no arguments it opens the desktop app; with a hero it prints advice.

Examples:
    python -m deadlock_helper
    python -m deadlock_helper Haze --enemies "Lash, Seven, Abrams, Mo & Krill, Bebop, Wraith"
"""

from __future__ import annotations

import argparse
import textwrap

from .api import DeadlockAPI
from .recommender import MATCHUP_EDGE, Recommendation, recommend

TIER_COST = {1: "800", 2: "1,600", 3: "3,200", 4: "6,400"}
WIDTH = 88


def _section(title: str) -> list[str]:
    return ["", title, "-" * len(title)]


def _wrap(text: str, indent: str = "  - ", width: int = WIDTH) -> list[str]:
    return textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=" " * len(indent)) or [indent]


def _matchup_label(edge: float) -> str:
    if edge >= MATCHUP_EDGE:
        return "favoured"
    if edge <= -MATCHUP_EDGE:
        return "tough"
    return "even"


def format_recommendation(rec: Recommendation) -> str:
    title = f"{rec.hero}" + (f"  vs  {', '.join(rec.enemies)}" if rec.enemies else "")
    lines = ["=" * min(WIDTH, max(len(title), 20)), title, "=" * min(WIDTH, max(len(title), 20))]

    lines += _section("How to play")
    if rec.playstyle:
        for note in rec.playstyle:
            lines += _wrap(note)
    else:
        lines.append("  (no notes yet)")

    lines += _section("Ability to max (first to last)")
    if rec.ability_max_order:
        lines.append("  " + "  >  ".join(rec.ability_max_order))
        lines.append(f"  Most successful order seen in {rec.ability_order_matches:,} games "
                     f"({rec.ability_order_win_rate:.0%} won*)")
    else:
        lines.append("  (not enough data)")

    if rec.ability_steps:
        lines += _section("Ability points, step by step")
        name_w = max(len(st.ability) for st in rec.ability_steps)
        for st in rec.ability_steps:
            key = f"[{st.key}]" if st.key else "   "
            head = f"  {st.step:>2}. {key} {st.ability:<{name_w}}  {st.action:<6}  "
            lines += textwrap.wrap(st.effect or "", width=WIDTH, initial_indent=head,
                                   subsequent_indent=" " * len(head)) or [head.rstrip()]

    lines += _section("Core items by tier")
    for tier, picks in rec.core_items.items():
        lines.append(f"  Tier {tier}  ({TIER_COST.get(tier, '?')} souls)")
        lines += [f"    {p.name:<26} {p.slot.capitalize():<9} {p.win_rate:5.1%} won   {p.matches:>9,} games"
                  for p in picks]
    if 4 in rec.core_items:
        lines.append("  * Tier 4 items and full ability orders show high win rates partly because")
        lines.append("    only games that are going well get that far. Compare items within a tier.")

    if rec.counter_items:
        lines += _section("Small edges against this enemy team")
        lines += [f"    {p.name:<26} {p.note}" for p in rec.counter_items]
        if max(float(p.note.split("%")[0].lstrip("+")) for p in rec.counter_items) < 2:
            lines.append("    (all under 2 points: nice to have, never worth skipping a core item for)")

    if rec.matchups:
        lines += _section("How you do against each enemy")
        lines.append("  Your win rate vs each enemy, next to what you'd expect from both heroes'")
        lines.append("  overall strength. The difference is the matchup itself.")
        name_w = max(len(mu.enemy) for mu in rec.matchups)
        for mu in sorted(rec.matchups, key=lambda x: -x.edge):
            exp = f"expected {mu.expected:5.1%}" if mu.expected is not None else ""
            lines.append(f"    vs {mu.enemy:<{name_w}}  {mu.win_rate:5.1%}  {exp}  {mu.edge * 100:+5.1f} pts  "
                         f"{_matchup_label(mu.edge):<8}  ({mu.games:,} games)")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deadlock build and playstyle suggestions")
    parser.add_argument("hero", nargs="?", help="your hero, e.g. Haze (leave out to open the app)")
    parser.add_argument("--enemies", default="", help="comma separated enemy heroes")
    parser.add_argument("--min-badge", type=int, default=None,
                        help="only use games at or above this average badge (rank) level")
    args = parser.parse_args()
    if not args.hero:
        from .gui import main as gui_main
        gui_main()
        return
    enemies = [e.strip() for e in args.enemies.split(",") if e.strip()]
    print(format_recommendation(recommend(DeadlockAPI(), args.hero, enemies, args.min_badge)))


if __name__ == "__main__":
    main()
