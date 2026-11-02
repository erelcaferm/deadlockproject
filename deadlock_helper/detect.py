"""Find hero portraits in a screenshot.

This only looks at pixels on the screen, the same way you do. It never touches
the game's memory or files, so it carries no anti-cheat risk.

How it works: every hero's portrait art (from the community API, the same art
the game uses) is scaled to a range of sizes and slid over the screenshot with
OpenCV template matching. The strongest non-overlapping hits win. Heroes left of
the screen centre are your team, right of centre are the enemy, which matches
the top bar of the in-game HUD. If that's the wrong way round, the app has a
Swap button.

Untested against the live game when written: the scale range and the score
threshold may need tuning. `save_debug_image` writes what was found so it can
be checked by eye.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

try:
    import cv2
except ImportError:  # detection is optional; the rest of the app works without it
    cv2 = None

WORK_HEIGHT = 540          # screenshots are scaled to this height before matching (speed)
TOP_REGION = 0.16          # the HUD top bar sits in the top ~16% of the screen
MIN_SCORE = 0.62
MAX_HEROES = 12


@dataclass
class Detection:
    hero_id: int
    score: float
    box: tuple[int, int, int, int]   # x, y, w, h in screenshot pixels
    team: str = ""                   # "ally" or "enemy"


@dataclass
class DetectionResult:
    allies: list[Detection] = field(default_factory=list)
    enemies: list[Detection] = field(default_factory=list)

    @property
    def all(self) -> list[Detection]:
        return self.allies + self.enemies


def available() -> bool:
    return cv2 is not None


def _prep_template(img: Image.Image, background=(20, 20, 24)) -> np.ndarray:
    """Crop transparent borders and flatten onto a dark HUD-like background. Returns BGR."""
    img = img.convert("RGBA")
    bbox = img.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    flat = Image.new("RGBA", img.size, background + (255,))
    flat.alpha_composite(img)
    return np.asarray(flat.convert("RGB"))[:, :, ::-1].copy()


class HeroDetector:
    """Holds the portrait templates. Build once, call `detect()` per screenshot."""

    def __init__(self, portraits: dict[int, list[Image.Image]],
                 height_fracs: tuple[float, ...] | None = None):
        """portraits: hero id -> one or more portrait images (e.g. top bar art and small icon).
        height_fracs: portrait heights to try, as a fraction of screen height."""
        if cv2 is None:
            raise RuntimeError("opencv-python is not installed, so screen detection is off")
        self.templates = {hid: [_prep_template(p) for p in imgs] for hid, imgs in portraits.items() if imgs}
        self.height_fracs = height_fracs or tuple(np.geomspace(0.025, 0.11, 12))
        self.last_good_frac: float | None = None

    def _scaled(self, tmpl: np.ndarray, height: int) -> np.ndarray | None:
        h, w = tmpl.shape[:2]
        width = max(4, round(w * height / h))
        if height < 8:
            return None
        return cv2.resize(tmpl, (width, height), interpolation=cv2.INTER_AREA)

    def detect(self, screenshot: Image.Image, region: str = "top", min_score: float = MIN_SCORE) -> DetectionResult:
        """region: "top" scans the HUD top bar only (fast), "full" scans the whole screen
        (for the scoreboard; slower)."""
        full_w, full_h = screenshot.size
        factor = WORK_HEIGHT / full_h
        small = screenshot.convert("RGB").resize((round(full_w * factor), WORK_HEIGHT), Image.BILINEAR)
        crop_h = round(WORK_HEIGHT * TOP_REGION) if region == "top" else WORK_HEIGHT
        hay = np.asarray(small)[:crop_h, :, ::-1].copy()

        fracs = list(self.height_fracs)
        if self.last_good_frac is not None:  # try last game's size first, and its neighbours
            fracs.sort(key=lambda f: abs(np.log(f / self.last_good_frac)))
            fracs = fracs[:4]

        candidates: list[tuple[float, int, tuple[int, int, int, int], float]] = []
        for frac in fracs:
            height = round(frac * WORK_HEIGHT)
            for hid, tmpls in self.templates.items():
                for tmpl in tmpls:
                    t = self._scaled(tmpl, height)
                    if t is None or t.shape[0] > hay.shape[0] or t.shape[1] > hay.shape[1]:
                        continue
                    res = np.nan_to_num(cv2.matchTemplate(hay, t, cv2.TM_CCOEFF_NORMED), nan=-1.0)
                    # several peaks per template, in case of near-duplicates elsewhere
                    for _ in range(2):
                        _, score, _, (x, y) = cv2.minMaxLoc(res)
                        if score < min_score:
                            break
                        candidates.append((score, hid, (x, y, t.shape[1], t.shape[0]), frac))
                        res[max(0, y - t.shape[0] // 2):y + t.shape[0] // 2 + 1,
                            max(0, x - t.shape[1] // 2):x + t.shape[1] // 2 + 1] = -1

        picked = _best_row(candidates, same_line=(region == "top"))
        if picked:
            self.last_good_frac = float(np.median([c[3] for c in picked]))

        result = DetectionResult()
        mid = WORK_HEIGHT * full_w / full_h / 2
        for score, hid, (x, y, w, h), _ in sorted(picked, key=lambda c: c[2][0]):
            det = Detection(hid, float(score), tuple(round(v / factor) for v in (x, y, w, h)))
            if x + w / 2 < mid:
                det.team = "ally"
                result.allies.append(det)
            else:
                det.team = "enemy"
                result.enemies.append(det)
        return result


def _overlap(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / min(aw * ah, bw * bh) if inter else 0.0


def _non_max_suppression(candidates, limit):
    """Best hits first; each hero once, and no two hits on the same spot."""
    picked, used = [], set()
    for cand in sorted(candidates, key=lambda c: c[0], reverse=True):
        score, hid, box, _ = cand
        if hid in used or any(_overlap(box, p[2]) > 0.3 for p in picked):
            continue
        picked.append(cand)
        used.add(hid)
        if len(picked) >= limit:
            break
    return picked


MIN_ROW = 3  # portraits come in a row of equal size; fewer than this is probably noise


def _best_row(candidates, same_line: bool = True):
    """HUD portraits share one size and one line. For each size tried, keep the hits that
    sit on a common line, and return the strongest such row. Lone look-alikes elsewhere
    on the screen (wrong size or height) are dropped."""
    best, best_quality = [], 0.0
    for frac in {c[3] for c in candidates}:
        picks = _non_max_suppression([c for c in candidates if c[3] == frac], MAX_HEROES)
        if len(picks) < MIN_ROW:
            continue
        mid_y = float(np.median([c[2][1] for c in picks]))
        row = [c for c in picks if not same_line or abs(c[2][1] - mid_y) <= 0.3 * c[2][3]]
        quality = sum(c[0] for c in row)
        if len(row) >= MIN_ROW and quality > best_quality:
            best, best_quality = row, quality
    return best


def save_debug_image(screenshot: Image.Image, result: DetectionResult, names: dict[int, str], path) -> None:
    """Draw boxes around what was found, for checking detection by eye."""
    img = screenshot.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    for det in result.all:
        x, y, w, h = det.box
        colour = (80, 200, 120) if det.team == "ally" else (230, 80, 80)
        draw.rectangle([x, y, x + w, y + h], outline=colour, width=3)
        draw.text((x, y + h + 2), f"{names.get(det.hero_id, det.hero_id)} {det.score:.2f}", fill=colour)
    img.save(path)


def grab_screen() -> Image.Image:
    """Screenshot of the primary monitor. Works with Deadlock in borderless or windowed
    mode; exclusive fullscreen can come back black on some systems."""
    from PIL import ImageGrab
    return ImageGrab.grab()
