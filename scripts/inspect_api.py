"""Print one sample row from every endpoint we use, so field names can be checked.

Run: python scripts/inspect_api.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deadlock_helper.api import DeadlockAPI  # noqa: E402

api = DeadlockAPI(cache_dir=None)
heroes = api.heroes()
hero_id = int(heroes[0]["id"])
calls = {
    "heroes": lambda: heroes,
    "items": api.items,
    "item_stats": lambda: api.item_stats(hero_id),
    "ability_order_stats": lambda: api.ability_order_stats(hero_id),
    "hero_counter_stats": api.hero_counter_stats,
}
for name, call in calls.items():
    try:
        data = call()
        sample = data[0] if isinstance(data, list) and data else data
        print(f"== {name}: {len(data) if isinstance(data, list) else '?'} rows")
        print(json.dumps(sample, indent=2)[:1500])
    except Exception as exc:  # noqa: BLE001
        print(f"== {name}: FAILED {exc}")
