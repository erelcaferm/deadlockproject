"""Thin client for the community Deadlock API (https://deadlock-api.com).

Two hosts are used:
- assets.deadlock-api.com: static game data (heroes, items, abilities, images)
- api.deadlock-api.com: match analytics (win rates, item stats, ability orders, matchups)

Responses are cached on disk so the app stays fast and we stay polite to a
free community service.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

ASSETS_URL = "https://assets.deadlock-api.com"
ANALYTICS_URL = "https://api.deadlock-api.com"

DEFAULT_CACHE_DIR = Path.home() / ".deadlock_helper" / "cache"
ASSETS_TTL_S = 24 * 3600  # game data changes only with patches
ANALYTICS_TTL_S = 6 * 3600
LOOKBACK_DAYS = 30


class DeadlockAPI:
    def __init__(self, cache_dir: Path | None = DEFAULT_CACHE_DIR, timeout: float = 30.0):
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "deadlockproject (learning helper; github.com/erelcaferm/deadlockproject)"

    # ---------- low level ----------
    def _get(self, base: str, path: str, params: dict[str, Any] | None, ttl: int) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = hashlib.sha1(json.dumps([base, path, params], sort_keys=True).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if cache_file and cache_file.exists() and time.time() - cache_file.stat().st_mtime < ttl:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        resp = self.session.get(base + path, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if cache_file:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data

    @staticmethod
    def _since() -> int:
        return int(time.time()) - LOOKBACK_DAYS * 24 * 3600

    # ---------- static game data ----------
    def _assets(self, name: str, params: dict[str, Any] | None = None) -> Any:
        """Static data from assets.deadlock-api.com, falling back to the identical
        copy served by api.deadlock-api.com/v1/assets when the assets host is
        unreachable (some networks and firewalls only allow one of the two)."""
        try:
            return self._get(ASSETS_URL, f"/v2/{name}", params, ASSETS_TTL_S)
        except requests.RequestException:
            return self._get(ANALYTICS_URL, f"/v1/assets/{name}", params, ASSETS_TTL_S)

    def heroes(self) -> list[dict]:
        return self._assets("heroes", {"only_active": "true"})

    def items(self) -> list[dict]:
        """All items, including shop upgrades (type 'upgrade') and hero abilities (type 'ability')."""
        return self._assets("items")

    # ---------- analytics ----------
    def item_stats(self, hero_id: int, enemy_hero_ids: list[int] | None = None,
                   min_average_badge: int | None = None) -> list[dict]:
        params = {
            "hero_ids": str(hero_id),
            "min_unix_timestamp": self._since(),
            "min_average_badge": min_average_badge,
        }
        if enemy_hero_ids:
            params["enemy_hero_ids"] = ",".join(map(str, enemy_hero_ids))
        return self._get(ANALYTICS_URL, "/v1/analytics/item-stats", params, ANALYTICS_TTL_S)

    def ability_order_stats(self, hero_id: int, min_average_badge: int | None = None) -> list[dict]:
        params = {"hero_id": hero_id, "min_unix_timestamp": self._since(),
                  "min_average_badge": min_average_badge}
        return self._get(ANALYTICS_URL, "/v1/analytics/ability-order-stats", params, ANALYTICS_TTL_S)

    def hero_counter_stats(self, min_average_badge: int | None = None) -> list[dict]:
        """Hero-vs-enemy-hero results for every pair; filtered client side."""
        params = {"min_unix_timestamp": self._since(), "min_average_badge": min_average_badge,
                  "same_lane_filter": "false"}
        return self._get(ANALYTICS_URL, "/v1/analytics/hero-counter-stats", params, ANALYTICS_TTL_S)
