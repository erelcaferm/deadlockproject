"""Screen detection on synthetic screenshots (no game needed). Skipped without OpenCV."""

import io
import random
import unittest

from PIL import Image, ImageDraw, ImageFilter

from deadlock_helper import detect


def fake_portrait(seed: int, size=(80, 110)) -> Image.Image:
    """A made-up 'hero portrait': random coloured shapes, different for every seed."""
    rnd = random.Random(seed)
    img = Image.new("RGBA", size, tuple(rnd.randrange(256) for _ in range(3)) + (255,))
    draw = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rnd.randrange(size[0]), rnd.randrange(size[1])
        x1, y1 = x0 + rnd.randrange(10, 50), y0 + rnd.randrange(10, 50)
        colour = tuple(rnd.randrange(256) for _ in range(3)) + (255,)
        (draw.ellipse if rnd.random() < 0.5 else draw.rectangle)([x0, y0, x1, y1], fill=colour)
    return img


def fake_screenshot(portraits, allies, enemies, screen=(1920, 1080), height=56, seed=0) -> Image.Image:
    rnd = random.Random(seed)
    shot = Image.new("RGB", screen, (35, 38, 45))
    draw = ImageDraw.Draw(shot)
    for _ in range(300):  # busy background so matching has to work for it
        x, y = rnd.randrange(screen[0]), rnd.randrange(screen[1])
        draw.rectangle([x, y, x + rnd.randrange(5, 80), y + rnd.randrange(5, 80)],
                       fill=tuple(rnd.randrange(256) for _ in range(3)))
    draw.rectangle([0, 0, screen[0], height + 30], fill=(18, 18, 22))  # HUD bar
    cx = screen[0] // 2

    def paste(hid, x):
        p = portraits[hid].resize((round(80 * height / 110), height))
        shot.paste(p.convert("RGB"), (x, 12))

    w = round(80 * height / 110) + 6
    for i, hid in enumerate(allies):
        paste(hid, cx - 120 - (len(allies) - i) * w)
    for i, hid in enumerate(enemies):
        paste(hid, cx + 120 + i * w)
    shot = shot.filter(ImageFilter.GaussianBlur(0.6))
    buf = io.BytesIO()
    shot.save(buf, "JPEG", quality=70)  # compression noise, like a real capture
    return Image.open(io.BytesIO(buf.getvalue()))


@unittest.skipUnless(detect.available(), "opencv not installed")
class DetectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.portraits = {hid: fake_portrait(hid) for hid in range(1, 41)}
        cls.detector = detect.HeroDetector({h: [p] for h, p in cls.portraits.items()})

    def test_finds_both_teams_in_top_bar(self):
        allies, enemies = [3, 7, 11, 15, 19, 23], [2, 6, 10, 14, 18, 22]
        shot = fake_screenshot(self.portraits, allies, enemies)
        result = self.detector.detect(shot)
        self.assertEqual([d.hero_id for d in result.allies], allies)
        self.assertEqual([d.hero_id for d in result.enemies], enemies)

    def test_other_resolution_and_size(self):
        allies, enemies = [1, 2, 3, 4, 5, 6], [31, 32, 33, 34, 35, 36]
        shot = fake_screenshot(self.portraits, allies, enemies, screen=(2560, 1440), height=90, seed=4)
        result = detect.HeroDetector({h: [p] for h, p in self.portraits.items()}).detect(shot)
        self.assertEqual(sorted(d.hero_id for d in result.enemies), enemies)
        self.assertEqual(sorted(d.hero_id for d in result.allies), allies)

    def test_nothing_on_screen_finds_nothing(self):
        shot = fake_screenshot(self.portraits, [], [], seed=9)
        self.assertEqual(self.detector.detect(shot).all, [])


if __name__ == "__main__":
    unittest.main()
