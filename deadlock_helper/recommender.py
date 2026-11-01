"""Turns raw Deadlock API data into advice: what to buy, what to max, how to play.

All functions here are pure (data in, advice out) so they can be tested
without network access. `recommend()` at the bottom wires them to the API.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# Bayesian smoothing: pretend every option starts with PRIOR_N games at 50%.
# Stops a 3-0 item from outranking a 5000-game staple.
PRIOR_N = 200
MIN_MATCHES = 50


# ---------- helpers that tolerate small differences in API field names ----------
def _matches(row: dict) -> int:
    for key in ("matches", "matches_played", "total"):
        if row.get(key) is not None:
            return int(row[key])
    return int(row.get("wins", 0)) + int(row.get("losses", 0))


def smoothed_win_rate(wins: int, matches: int, prior_wr: float = 0.5, prior_n: int = PRIOR_N) -> float:
    return (wins + prior_wr * prior_n) / (matches + prior_n)


def raw_win_rate(row: dict) -> float:
    m = _matches(row)
    return row.get("wins", 0) / m if m else 0.0


# ---------- results ----------
@dataclass
class ItemPick:
    item_id: int
    name: str
    tier: int
    slot: str  # weapon / vitality / spirit
    cost: int
    win_rate: float
    matches: int
    note: str = ""


@dataclass
class AbilityStep:
    """One ability point spent: unlocking an ability or buying one of its 3 upgrade ranks."""
    step: int
    ability: str
    key: int | None  # 1-4, the in-game ability slot
    rank: int        # 0 = unlock, 1-3 = upgrade rank
    effect: str = ""
    avg_time_s: float | None = None  # when players typically took it; None if added to finish the build

    @property
    def action(self) -> str:
        return "Unlock" if self.rank == 0 else f"Rank {self.rank}"


@dataclass
class Recommendation:
    hero: str
    enemies: list[str]
    core_items: dict[int, list[ItemPick]] = field(default_factory=dict)  # tier -> picks
    counter_items: list[ItemPick] = field(default_factory=list)
    ability_max_order: list[str] = field(default_factory=list)
    ability_steps: list[AbilityStep] = field(default_factory=list)
    ability_order_win_rate: float | None = None
    ability_order_matches: int = 0
    playstyle: list[str] = field(default_factory=list)
    matchups: list[tuple[str, float, int]] = field(default_factory=list)  # (enemy, my win rate, games)


# ---------- items ----------
def index_items(items: list[dict]) -> dict[int, dict]:
    return {int(i["id"]): i for i in items if "id" in i}


def rank_items(item_stats: list[dict], item_index: dict[int, dict], per_tier: int = 4,
               min_matches: int = MIN_MATCHES) -> dict[int, list[ItemPick]]:
    """Best shop items per tier for a hero, ranked by smoothed win rate."""
    total = sum(_matches(r) for r in item_stats) or 1
    picks: dict[int, list[ItemPick]] = {}
    for row in item_stats:
        info = item_index.get(int(row.get("item_id", -1)))
        if not info or info.get("type") != "upgrade" or not info.get("shopable", True):
            continue
        m = _matches(row)
        if m < min_matches:
            continue
        pick = ItemPick(
            item_id=int(info["id"]),
            name=info.get("name", info.get("class_name", "?")),
            tier=int(info.get("item_tier", 0)),
            slot=str(info.get("item_slot_type", "?")),
            cost=int(info.get("cost", 0) or 0),
            win_rate=smoothed_win_rate(int(row.get("wins", 0)), m),
            matches=m,
        )
        picks.setdefault(pick.tier, []).append(pick)
    for tier, lst in picks.items():
        # Mostly win rate, with a small bonus for being commonly bought (proven, not niche).
        lst.sort(key=lambda p: p.win_rate + 0.02 * (p.matches / total) ** 0.5, reverse=True)
        picks[tier] = lst[:per_tier]
    return dict(sorted(picks.items()))


def counter_items(baseline_stats: list[dict], vs_enemy_stats: list[dict], item_index: dict[int, dict],
                  top: int = 5, min_matches: int = 30) -> list[ItemPick]:
    """Items whose win rate rises the most when facing this specific enemy lineup."""
    base = {int(r["item_id"]): r for r in baseline_stats if "item_id" in r}
    out: list[ItemPick] = []
    for row in vs_enemy_stats:
        iid = int(row.get("item_id", -1))
        info = item_index.get(iid)
        if not info or info.get("type") != "upgrade" or iid not in base:
            continue
        m = _matches(row)
        if m < min_matches:
            continue
        base_wr = raw_win_rate(base[iid])
        vs_wr = smoothed_win_rate(int(row.get("wins", 0)), m, prior_wr=base_wr, prior_n=100)
        delta = vs_wr - base_wr
        if delta <= 0:
            continue
        out.append(ItemPick(iid, info.get("name", "?"), int(info.get("item_tier", 0)),
                            str(info.get("item_slot_type", "?")), int(info.get("cost", 0) or 0),
                            vs_wr, m, note=f"+{delta * 100:.1f}% vs this lineup"))
    out.sort(key=lambda p: p.win_rate - raw_win_rate(base[p.item_id]), reverse=True)
    return out[:top]


# ---------- abilities ----------
def max_order_from_sequence(sequence: list[int], points_to_max: int = 4) -> list[int]:
    """Given the order abilities received points (unlock + upgrades), return which got maxed first.

    An ability appearing `points_to_max` times is maxed. Abilities never maxed are
    appended by how many points they got.
    """
    counts: Counter[int] = Counter()
    maxed: list[int] = []
    for ability in sequence:
        counts[ability] += 1
        if counts[ability] == points_to_max:
            maxed.append(ability)
    rest = [a for a, _ in counts.most_common() if a not in maxed]
    return maxed + rest


def ability_key_slots(hero: dict, item_index: dict[int, dict]) -> dict[str, int]:
    """Map ability class_name -> in-game key (1-4) from the hero's signature slots."""
    hero_items = hero.get("items") or {}
    return {cls: int(slot[-1]) for slot, cls in hero_items.items()
            if slot.startswith("signature") and slot[-1].isdigit()}


def ability_steps(sequence: list[int], item_index: dict[int, dict], key_slots: dict[str, int] | None = None,
                  times: list[float] | None = None, points_to_max: int = 4) -> list[AbilityStep]:
    """Turn a raw point sequence into a step-by-step plan.

    The first point in an ability unlocks it, the next three buy upgrade ranks 1-3.
    Abilities left unfinished are completed at the end (most-invested first) so the
    plan always covers every unlock and rank.
    """
    key_slots = key_slots or {}
    times = times or []
    counts: Counter[int] = Counter()
    steps: list[AbilityStep] = []

    def add(aid: int, t: float | None) -> None:
        rank = counts[aid]
        counts[aid] += 1
        info = item_index.get(aid, {})
        desc = info.get("description") or {}
        effect = ""
        if rank == 0 and isinstance(desc, dict):
            effect = _strip_tags(str(desc.get("quip") or ""))
        elif isinstance(desc, dict):
            effect = _strip_tags(str(desc.get(f"t{rank}_desc") or ""))
        if rank > 0 and not effect:
            effect = _upgrade_from_properties(info, rank)
        steps.append(AbilityStep(len(steps) + 1, info.get("name", str(aid)), key_slots.get(info.get("class_name", "")),
                                 rank, effect, t))

    for i, aid in enumerate(sequence):
        if counts[aid] < points_to_max:
            add(aid, times[i] if i < len(times) else None)
    for aid, _ in counts.most_common():
        while counts[aid] < points_to_max:
            add(aid, None)
    return steps


def _upgrade_from_properties(info: dict, rank: int) -> str:
    """Fallback rank text built from the raw stat changes, e.g. '+7m Invis Sprint Speed'."""
    upgrades = info.get("upgrades") or []
    if rank > len(upgrades):
        return ""
    props = info.get("properties") or {}
    parts = []
    for up in upgrades[rank - 1].get("property_upgrades", []):
        if up.get("upgrade_type") == "EAddToScale":
            continue
        meta = props.get(up.get("name"), {}) or {}
        label = meta.get("label") or up.get("name", "")
        value = str(up.get("bonus", ""))
        postfix = meta.get("postfix") or ""
        if postfix and not value.endswith(postfix):
            value += postfix
        if not value.startswith(("-", "+")):
            value = "+" + value
        parts.append(f"{value} {label}".strip())
    return ", ".join(parts)


def best_ability_order(order_stats: list[dict], min_matches: int = MIN_MATCHES) -> dict | None:
    """Most reliable high-win-rate ability order (smoothed, so popular orders win ties)."""
    candidates = [r for r in order_stats if _matches(r) >= min_matches and r.get("abilities")]
    if not candidates:
        return None
    return max(candidates, key=lambda r: smoothed_win_rate(int(r.get("wins", 0)), _matches(r)))


# ---------- matchups & playstyle ----------
def matchups(counter_stats: list[dict], hero_id: int, enemy_ids: list[int]) -> dict[int, tuple[float, int]]:
    out: dict[int, tuple[float, int]] = {}
    for row in counter_stats:
        if int(row.get("hero_id", -1)) == hero_id and int(row.get("enemy_hero_id", -1)) in enemy_ids:
            m = _matches(row)
            out[int(row["enemy_hero_id"])] = (smoothed_win_rate(int(row.get("wins", 0)), m), m)
    return out


def playstyle_notes(hero: dict, core: dict[int, list[ItemPick]],
                    hero_matchups: list[tuple[str, float, int]]) -> list[str]:
    notes: list[str] = []
    desc = hero.get("description") or {}
    if isinstance(desc, dict):
        for key in ("role", "playstyle"):
            if desc.get(key):
                notes.append(_strip_tags(str(desc[key])))

    slots = Counter(p.slot for picks in core.values() for p in picks)
    if slots:
        main, n = slots.most_common(1)[0]
        share = n / sum(slots.values())
        if share >= 0.5:
            flavour = {"weapon": "gun damage", "spirit": "ability (spirit) damage",
                       "vitality": "survivability"}.get(main, main)
            notes.append(f"Winning builds lean on {flavour}: {share:.0%} of the top items are {main} items.")

    if hero_matchups:
        best = max(hero_matchups, key=lambda m: m[1])
        worst = min(hero_matchups, key=lambda m: m[1])
        if best[1] >= 0.52:
            notes.append(f"You do well against {best[0]} ({best[1]:.0%} win rate). Look to fight them.")
        if worst[1] <= 0.48:
            notes.append(f"{worst[0]} is a tough matchup ({worst[1]:.0%} win rate). Avoid fighting them alone.")
    return notes


def _strip_tags(text: str) -> str:
    import re
    text = re.sub(r"<br\s*/?>", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


# ---------- wiring ----------
def find_hero(heroes: list[dict], name: str) -> dict:
    wanted = name.strip().lower()
    for h in heroes:
        if h.get("name", "").lower() == wanted:
            return h
    for h in heroes:
        if wanted in h.get("name", "").lower():
            return h
    raise ValueError(f"Unknown hero: {name!r}. Known: {', '.join(sorted(h['name'] for h in heroes))}")


def recommend(api, hero_name: str, enemy_names: list[str], min_average_badge: int | None = None) -> Recommendation:
    heroes = api.heroes()
    hero = find_hero(heroes, hero_name)
    enemies = [find_hero(heroes, n) for n in enemy_names]
    enemy_ids = [int(e["id"]) for e in enemies]
    item_index = index_items(api.items())

    base_stats = api.item_stats(int(hero["id"]), min_average_badge=min_average_badge)
    rec = Recommendation(hero=hero["name"], enemies=[e["name"] for e in enemies])
    rec.core_items = rank_items(base_stats, item_index)

    if enemy_ids:
        vs_stats = api.item_stats(int(hero["id"]), enemy_hero_ids=enemy_ids, min_average_badge=min_average_badge)
        rec.counter_items = counter_items(base_stats, vs_stats, item_index)
        mu = matchups(api.hero_counter_stats(min_average_badge), int(hero["id"]), enemy_ids)
        names = {int(e["id"]): e["name"] for e in enemies}
        rec.matchups = sorted(((names[i], wr, m) for i, (wr, m) in mu.items()), key=lambda x: x[1])

    order = best_ability_order(api.ability_order_stats(int(hero["id"]), min_average_badge))
    if order:
        rec.ability_max_order = [item_index.get(int(a), {}).get("name", str(a))
                                 for a in max_order_from_sequence([int(a) for a in order["abilities"]])]
        rec.ability_steps = ability_steps([int(a) for a in order["abilities"]], item_index,
                                          ability_key_slots(hero, item_index), order.get("avg_upgrade_times_s"))
        rec.ability_order_matches = _matches(order)
        rec.ability_order_win_rate = raw_win_rate(order)

    rec.playstyle = playstyle_notes(hero, rec.core_items, rec.matchups)
    return rec
