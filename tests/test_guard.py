"""Ranked guard logic, with a fake API (no network)."""

import tempfile
import unittest
from pathlib import Path

from deadlock_helper import guard as g


class FakeAPI:
    def __init__(self, active=None, history=None, fail=False):
        self.active, self.history, self.fail = active or [], history or [], fail

    def active_matches(self, account_id):
        if self.fail:
            raise ConnectionError("offline")
        return self.active

    def match_history(self, account_id):
        return self.history


def make(api, now=1_000_000.0):
    tmp = Path(tempfile.mkdtemp()) / "guard.json"
    clock = {"t": now}
    return g.RankedGuard(api, tmp, clock=lambda: clock["t"]), clock


class GuardTests(unittest.TestCase):
    def test_friend_code_parsing(self):
        self.assertEqual(g.parse_friend_code("123456789"), 123456789)
        self.assertEqual(g.parse_friend_code(str(g.STEAM64_BASE + 42)), 42)
        self.assertIsNone(g.parse_friend_code("abc"))
        self.assertIsNone(g.parse_friend_code(""))

    def test_must_choose_mode_and_ranked_is_refused(self):
        guard, _ = make(FakeAPI())
        self.assertFalse(guard.check(None).allowed)
        self.assertFalse(guard.check("Ranked").allowed)
        self.assertTrue(guard.check("Unranked").allowed)

    def test_live_ranked_match_is_refused(self):
        active = [{"match_mode": 4, "players": [{"account_id": 7}]},
                  {"match_mode": 1, "players": [{"account_id": 8}]}]
        guard, _ = make(FakeAPI(active=active))
        guard.set_account_id(7)
        self.assertFalse(guard.check("Unranked").allowed)
        guard.set_account_id(8)
        self.assertTrue(guard.check("Unranked").allowed)

    def test_network_failure_does_not_block(self):
        guard, _ = make(FakeAPI(fail=True))
        guard.set_account_id(7)
        self.assertTrue(guard.check("Unranked").allowed)

    def test_advice_during_ranked_match_locks_for_a_day(self):
        history = [{"match_id": 1, "match_mode": 4, "start_time": 1_000_000, "match_duration_s": 1800},
                   {"match_id": 2, "match_mode": 1, "start_time": 900_000, "match_duration_s": 1800}]
        guard, clock = make(FakeAPI(history=history), now=1_000_100)
        guard.set_account_id(7)
        guard.record_advice()                      # during ranked match 1
        clock["t"] = 1_003_000
        self.assertIn("locked", guard.audit_history(force=True))
        self.assertFalse(guard.check("Unranked").allowed)
        clock["t"] += 25 * 3600
        self.assertTrue(guard.check("Unranked").allowed)
        self.assertIsNone(guard.audit_history(force=True))  # same match is not punished twice

    def test_unranked_history_does_not_lock(self):
        history = [{"match_id": 2, "match_mode": 1, "start_time": 1_000_000, "match_duration_s": 1800}]
        guard, _ = make(FakeAPI(history=history), now=1_000_100)
        guard.set_account_id(7)
        guard.record_advice()
        self.assertIsNone(guard.audit_history(force=True))


if __name__ == "__main__":
    unittest.main()
