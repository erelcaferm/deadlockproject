"""Logic tests with small hand-written inputs (no network). Run: python -m unittest"""

import unittest

from deadlock_helper import recommender as r

ITEMS = r.index_items([
    {"id": 1, "name": "Basic Mag", "type": "upgrade", "item_tier": 1, "item_slot_type": "weapon", "cost": 800},
    {"id": 2, "name": "Extra Spirit", "type": "upgrade", "item_tier": 1, "item_slot_type": "spirit", "cost": 800},
    {"id": 3, "name": "Rare Item", "type": "upgrade", "item_tier": 1, "item_slot_type": "weapon", "cost": 800},
    {"id": 4, "name": "Debuff Remover", "type": "upgrade", "item_tier": 2, "item_slot_type": "vitality", "cost": 1600},
    {"id": 100, "name": "Dash", "type": "ability"},
])


class ItemTests(unittest.TestCase):
    def test_smoothing_beats_tiny_samples(self):
        stats = [
            {"item_id": 1, "wins": 3000, "matches": 5600},  # 53.6% over many games
            {"item_id": 3, "wins": 35, "matches": 55},      # 64% but few games
        ]
        ranked = r.rank_items(stats, ITEMS)[1]
        self.assertEqual(ranked[0].name, "Basic Mag")

    def test_abilities_and_low_sample_items_excluded(self):
        stats = [{"item_id": 100, "wins": 900, "matches": 1000}, {"item_id": 2, "wins": 5, "matches": 10}]
        self.assertEqual(r.rank_items(stats, ITEMS), {})

    def test_counter_items_find_lineup_specific_gains(self):
        base = [{"item_id": 4, "wins": 500, "matches": 1000}, {"item_id": 1, "wins": 500, "matches": 1000}]
        vs = [{"item_id": 4, "wins": 400, "matches": 600}, {"item_id": 1, "wins": 290, "matches": 600}]
        picks = r.counter_items(base, vs, ITEMS)
        self.assertEqual([p.name for p in picks], ["Debuff Remover"])

    def test_field_name_fallbacks(self):
        self.assertEqual(r._matches({"wins": 3, "losses": 2}), 5)
        self.assertEqual(r._matches({"matches_played": 7}), 7)


class AbilityTests(unittest.TestCase):
    def test_max_order(self):
        # 1 and 2 unlocked, then 1 maxed, then 3 unlocked, 2 maxed
        seq = [1, 2, 1, 1, 3, 1, 2, 2, 2]
        self.assertEqual(r.max_order_from_sequence(seq), [1, 2, 3])

    def test_best_order_needs_enough_games(self):
        rows = [{"abilities": [1], "wins": 10, "matches": 10}, {"abilities": [2], "wins": 600, "matches": 1000}]
        self.assertEqual(r.best_ability_order(rows)["abilities"], [2])


class PlaystyleTests(unittest.TestCase):
    def test_notes(self):
        core = {1: [r.ItemPick(2, "Extra Spirit", 1, "spirit", 800, 0.55, 500)]}
        notes = r.playstyle_notes({"description": {"role": "<b>Burst</b> caster"}}, core,
                                  [("Lash", 0.56, 300), ("Seven", 0.44, 300)])
        self.assertIn("Burst caster", notes)
        self.assertTrue(any("spirit" in n for n in notes))
        self.assertTrue(any("Seven is a tough matchup" in n for n in notes))

    def test_find_hero_partial(self):
        heroes = [{"id": 1, "name": "Mo & Krill"}, {"id": 2, "name": "Haze"}]
        self.assertEqual(r.find_hero(heroes, "mo")["id"], 1)
        with self.assertRaises(ValueError):
            r.find_hero(heroes, "nobody")


if __name__ == "__main__":
    unittest.main()
