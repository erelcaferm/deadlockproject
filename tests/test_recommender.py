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
            {"item_id": 2, "wins": 2500, "matches": 5000},  # rest of the tier, so the tier average is realistic
        ]
        ranked = r.rank_items(stats, ITEMS)[1]
        self.assertEqual(ranked[0].name, "Basic Mag")

    def test_weak_hero_thin_items_do_not_jump_the_queue(self):
        # Hero wins ~45%. A 200-game item at 46% should not beat a 100k-game item at 47%.
        stats = [{"item_id": 1, "wins": 47000, "matches": 100000},
                 {"item_id": 3, "wins": 92, "matches": 200},
                 {"item_id": 2, "wins": 43000, "matches": 100000}]
        self.assertEqual(r.rank_items(stats, ITEMS)[1][0].name, "Basic Mag")

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

    def test_ability_steps_unlock_then_ranks_and_finish(self):
        idx = r.index_items([
            {"id": 1, "name": "Dash", "class_name": "ab_dash",
             "description": {"quip": "Go fast", "t1_desc": "<b>+1</b> charge", "t2_desc": "x", "t3_desc": "y"}},
            {"id": 2, "name": "Bomb", "class_name": "ab_bomb",
             "properties": {"Speed": {"label": "Sprint Speed", "postfix": "m"}},
             "upgrades": [{"property_upgrades": [{"name": "Speed", "bonus": "7m"}]}]},
        ])
        steps = r.ability_steps([1, 2, 1, 1], idx, {"ab_dash": 3}, [10.0, 70.0, 130.0, 200.0])
        self.assertEqual([(s.ability, s.rank) for s in steps[:4]],
                         [("Dash", 0), ("Bomb", 0), ("Dash", 1), ("Dash", 2)])
        self.assertEqual(steps[0].key, 3)
        self.assertEqual(steps[0].effect, "Go fast")
        self.assertEqual(steps[2].effect, "+1 charge")
        self.assertEqual(steps[3].avg_time_s, 200.0)
        # finished afterwards: Dash rank 3, then Bomb ranks 1-3, with no timing
        self.assertEqual(len(steps), 8)
        self.assertEqual((steps[4].ability, steps[4].rank, steps[4].avg_time_s), ("Dash", 3, None))
        self.assertEqual(steps[-1].action, "Rank 3")
        self.assertEqual(steps[5].effect, "+7m Sprint Speed")  # built from stat changes

    def test_hero_key_slots(self):
        hero = {"items": {"signature1": "a", "signature4": "d", "weapon_primary": "gun"}}
        self.assertEqual(r.ability_key_slots(hero, {}), {"a": 1, "d": 4})

    def test_best_order_needs_enough_games(self):
        rows = [{"abilities": [1], "wins": 10, "matches": 10}, {"abilities": [2], "wins": 600, "matches": 1000}]
        self.assertEqual(r.best_ability_order(rows)["abilities"], [2])


class PlaystyleTests(unittest.TestCase):
    def test_notes(self):
        core = {1: [r.ItemPick(2, "Extra Spirit", 1, "spirit", 800, 0.55, 500)]}
        notes = r.playstyle_notes({"description": {"role": "<b>Burst</b> caster"}}, core,
                                  [r.Matchup("Lash", 0.56, 300, 0.50, 0.50), r.Matchup("Seven", 0.44, 300, 0.50, 0.50)])
        self.assertIn("Burst caster", notes)
        self.assertTrue(any("spirit" in n for n in notes))
        self.assertTrue(any("Seven is a tough matchup" in n for n in notes))

    def test_matchups_account_for_both_heroes_strength(self):
        # Hero 1 is weak (40%), hero 3 is strong (60%). 1 vs 3 at 34% is about what both
        # strengths predict (~31%), so it is not a bad matchup; 1 vs 2 at 44% is a good one.
        stats = [{"hero_id": 1, "enemy_hero_id": 2, "wins": 460, "matches": 1000},
                 {"hero_id": 1, "enemy_hero_id": 3, "wins": 340, "matches": 1000},
                 {"hero_id": 2, "enemy_hero_id": 1, "wins": 540, "matches": 1000},
                 {"hero_id": 2, "enemy_hero_id": 3, "wins": 440, "matches": 1000},
                 {"hero_id": 3, "enemy_hero_id": 1, "wins": 660, "matches": 1000},
                 {"hero_id": 3, "enemy_hero_id": 2, "wins": 560, "matches": 1000}]
        self.assertAlmostEqual(r.overall_win_rate(stats, 1), 0.40)
        self.assertAlmostEqual(r.expected_win_rate(0.5, 0.5), 0.5)
        mus = {m.enemy: m for m in r.matchups(stats, 1, [2, 3], {2: "Lash", 3: "Seven"})}
        self.assertGreater(mus["Lash"].edge, 0.02)
        self.assertGreater(mus["Seven"].edge, -0.02)  # raw 34% looks awful, but it's expected
        notes = r.playstyle_notes({}, {}, list(mus.values()))
        self.assertTrue(any(n.startswith("Lash is your best matchup") for n in notes))
        self.assertTrue(any(n.startswith("Seven is strong right now") for n in notes))
        self.assertIsNone(r.overall_win_rate(stats, 99))

    def test_upgrade_text_keeps_line_breaks_readable(self):
        self.assertEqual(r._strip_tags('<b>+1s</b> Sleep<br>Applies <i>15</i> stacks', line_break="; "),
                         "+1s Sleep; Applies 15 stacks")
        self.assertEqual(r._strip_tags("+0.11</span>/ per Stack"), "+0.11 per Stack")

    def test_find_hero_partial(self):
        heroes = [{"id": 1, "name": "Mo & Krill"}, {"id": 2, "name": "Haze"}]
        self.assertEqual(r.find_hero(heroes, "mo")["id"], 1)
        with self.assertRaises(ValueError):
            r.find_hero(heroes, "nobody")


if __name__ == "__main__":
    unittest.main()
