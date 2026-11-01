"""Simulate random 6v6 lobbies and run the recommender for all 12 heroes.

Each hero gets advice against the other team, exactly as a player in that
match would see it. Useful for spot-checking the recommender across many
heroes at once, and for demo material.

    python scripts/simulate.py --matches 3 --seed 7 --out sim_output
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deadlock_helper.__main__ import format_recommendation  # noqa: E402
from deadlock_helper.api import DeadlockAPI  # noqa: E402
from deadlock_helper.recommender import Recommendation, recommend  # noqa: E402

TEAM_SIZE = 6


def random_lobby(hero_names: list[str], rng: random.Random) -> tuple[list[str], list[str]]:
    picks = rng.sample(hero_names, TEAM_SIZE * 2)
    return picks[:TEAM_SIZE], picks[TEAM_SIZE:]


def summary_line(rec: Recommendation) -> str:
    first_max = rec.ability_max_order[0] if rec.ability_max_order else "?"
    t3 = rec.core_items.get(3, [])
    key_item = t3[0].name if t3 else "?"
    counter = rec.counter_items[0].name if rec.counter_items else "-"
    overall = f"{rec.overall_win_rate:.1%} overall" if rec.overall_win_rate is not None else ""
    return f"  {rec.hero:<14} {overall:<14} max {first_max:<20} T3 {key_item:<20} edge {counter}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matches", type=int, default=3)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--min-badge", type=int, default=None)
    parser.add_argument("--out", type=Path, default=None, help="folder for each hero's full advice")
    args = parser.parse_args()

    api = DeadlockAPI()
    rng = random.Random(args.seed)
    names = sorted(h["name"] for h in api.heroes()
                   if h.get("player_selectable", True) and not h.get("in_development") and not h.get("disabled"))

    for n in range(1, args.matches + 1):
        amber, sapphire = random_lobby(names, rng)
        print(f"\nMatch {n}")
        print(f"  Amber Hand:  {', '.join(amber)}")
        print(f"  Sapphire Flame: {', '.join(sapphire)}")
        for team_name, team, enemies in (("Amber Hand", amber, sapphire), ("Sapphire Flame", sapphire, amber)):
            print(f"\n {team_name}")
            for hero in team:
                rec = recommend(api, hero, enemies, args.min_badge)
                print(summary_line(rec))
                if args.out:
                    folder = args.out / f"match{n}"
                    folder.mkdir(parents=True, exist_ok=True)
                    slug = hero.lower().replace(" ", "_").replace("&", "and")
                    (folder / f"{slug}.txt").write_text(format_recommendation(rec), encoding="utf-8")


if __name__ == "__main__":
    main()
