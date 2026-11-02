"""Good-faith guard that keeps the helper out of ranked games.

The app never reads game memory, so it cannot know the game mode for certain.
It stacks three honest checks instead:

1. You say what you're playing before any advice is shown. "Ranked" is refused.
2. If you enter your Steam friend code, the app looks you up in the live match
   list of the community API and refuses if you're in a ranked match. That list
   only covers the ~200 matches on the in-game Watch tab, so it often finds nothing.
3. Afterwards it checks your match history. If advice was shown during what turned
   out to be a ranked match, the app locks itself for 24 hours.

None of this is tamper-proof. It is there to keep honest people honest.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

RANKED_MATCH_MODE = 4          # match_mode value the API uses for ranked
STEAM64_BASE = 76561197960265728
LOCK_HOURS = 24
PRE_MATCH_WINDOW_S = 5 * 60    # hero select happens a few minutes before the match clock starts
HISTORY_CHECK_EVERY_S = 10 * 60

MATCH_TYPES = ["Unranked", "Street Brawl", "Bots / practice", "Ranked"]
ALLOWED_TYPES = set(MATCH_TYPES) - {"Ranked"}


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""


def parse_friend_code(text: str) -> int | None:
    """Steam friend code (the 32-bit account id) or a SteamID64. None if not a number."""
    text = (text or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    if value >= STEAM64_BASE:
        value -= STEAM64_BASE
    return value if 0 < value < 2 ** 32 else None


def in_ranked_live_match(active_matches: list[dict], account_id: int) -> bool:
    for match in active_matches:
        if int(match.get("match_mode", 0)) != RANKED_MATCH_MODE:
            continue
        if any(int(p.get("account_id", -1)) == account_id for p in match.get("players", [])):
            return True
    return False


def ranked_matches_with_advice(history: list[dict], advice_times: list[float]) -> list[dict]:
    """Ranked matches during which the app showed advice."""
    hits = []
    for match in history:
        if int(match.get("match_mode", 0)) != RANKED_MATCH_MODE:
            continue
        start = int(match.get("start_time", 0))
        end = start + int(match.get("match_duration_s", 0) or 0)
        if any(start - PRE_MATCH_WINDOW_S <= t <= end for t in advice_times):
            hits.append(match)
    return hits


class RankedGuard:
    def __init__(self, api, state_file: Path, clock: Callable[[], float] = time.time):
        self.api = api
        self.state_file = state_file
        self.clock = clock
        self.state = self._load()
        self._last_history_check = 0.0

    # ---------- persistence ----------
    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
        except OSError:
            pass

    @property
    def account_id(self) -> int | None:
        return self.state.get("account_id")

    def set_account_id(self, account_id: int | None) -> None:
        self.state["account_id"] = account_id
        self._save()

    @property
    def locked_until(self) -> float:
        return float(self.state.get("locked_until", 0))

    # ---------- checks ----------
    def check(self, match_type: str | None) -> GuardResult:
        now = self.clock()
        if self.locked_until > now:
            when = time.strftime("%a %H:%M", time.localtime(self.locked_until))
            return GuardResult(False, f"Locked until {when}: advice was shown during a ranked match "
                                      f"({self.state.get('lock_reason', 'match history')}).")
        if match_type not in ALLOWED_TYPES:
            if match_type == "Ranked":
                return GuardResult(False, "This helper is for learning in unranked games. "
                                          "It stays off in ranked so nobody gets an unfair edge.")
            return GuardResult(False, "Pick what you're playing first (top left).")
        if self.account_id:
            try:
                if in_ranked_live_match(self.api.active_matches(self.account_id), self.account_id):
                    return GuardResult(False, "You're in a ranked match right now, so the helper is off.")
            except Exception:
                pass  # the live list is best effort; never block on a network hiccup
        return GuardResult(True)

    def record_advice(self) -> None:
        """Remember when advice was shown, so the history check can spot ranked games later."""
        now = self.clock()
        times = [t for t in self.state.get("advice_times", []) if now - t < 7 * 24 * 3600]
        times.append(now)
        self.state["advice_times"] = times[-500:]
        self._save()

    def audit_history(self, force: bool = False) -> str | None:
        """Look for ranked matches that overlapped advice. Locks the app and returns a message if found."""
        now = self.clock()
        if not self.account_id or (not force and now - self._last_history_check < HISTORY_CHECK_EVERY_S):
            return None
        self._last_history_check = now
        try:
            history = self.api.match_history(self.account_id)
        except Exception:
            return None
        seen = set(self.state.get("flagged_matches", []))
        hits = [m for m in ranked_matches_with_advice(history, self.state.get("advice_times", []))
                if m.get("match_id") not in seen]
        if not hits:
            return None
        self.state["flagged_matches"] = sorted(seen | {m.get("match_id") for m in hits})
        self.state["locked_until"] = now + LOCK_HOURS * 3600
        self.state["lock_reason"] = f"match {hits[0].get('match_id')}"
        self._save()
        return (f"Advice was shown during ranked match {hits[0].get('match_id')}. "
                f"The helper is locked for {LOCK_HOURS} hours.")
