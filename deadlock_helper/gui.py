"""Desktop app: pick heroes by clicking portraits, or let it read them from the screen.

Run with:  python -m deadlock_helper
"""

from __future__ import annotations

import io
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from PIL import Image, ImageDraw, ImageOps, ImageTk

from . import detect
from .api import DEFAULT_CACHE_DIR, DeadlockAPI
from .guard import MATCH_TYPES, RankedGuard, parse_friend_code
from .recommender import MATCHUP_EDGE, Recommendation, recommend

APP_DIR = DEFAULT_CACHE_DIR.parent
TEAM_SIZE = 6
ICON = 46
SLOT_ICON = 58
WATCH_EVERY_MS = 8000
TIER_COST = {1: "800", 2: "1,600", 3: "3,200", 4: "6,400"}
# badge = rank tier * 10 + sub-tier (see api.deadlock-api.com/v1/assets/ranks)
RANK_FILTERS = {"All ranks": None, "Acolyte and up": 31, "Mystic and up": 51, "Emissary and up": 71,
                "Phantom and up": 91, "Ascendant and up": 101}

BG, PANEL, CARD, TEXT, MUTED = "#15161a", "#1d1f25", "#262932", "#e6e6e6", "#9aa0aa"
ACCENT, GOOD, BAD, ALLY = "#e0b450", "#6cc58a", "#e06c6c", "#6aa6e0"


def placeholder(name: str, size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), CARD)
    initials = "".join(w[0] for w in name.replace("&", " ").split()[:2]).upper()
    ImageDraw.Draw(img).text((size // 2, size // 2), initials, fill=TEXT, anchor="mm")
    return img


class App(tk.Tk):
    def __init__(self, api: DeadlockAPI | None = None):
        super().__init__()
        self.title("Deadlock learning helper")
        self.configure(bg=BG)
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.api = api or DeadlockAPI()
        self.guard = RankedGuard(self.api, APP_DIR / "guard.json")
        self.heroes: list[dict] = []
        self.by_id: dict[int, dict] = {}
        self.portraits: dict[int, Image.Image] = {}        # small square icons for the UI
        self.photos: dict[tuple[int, int], ImageTk.PhotoImage] = {}
        self.detector: detect.HeroDetector | None = None

        self.me: int | None = None
        self.enemies: list[int | None] = [None] * TEAM_SIZE
        self.detected_allies: list[int] = []
        self.active_slot: str | int = "me"                   # "me" or enemy index
        self.watching = tk.BooleanVar(value=False)
        self.busy_detect = False
        self.last_detected: list[int] = []               # enemies from the previous screen read

        self._jobs: queue.Queue = queue.Queue()
        self._build()
        self.after(50, self._pump)
        self.status("Loading heroes...")
        self.run_bg(self._load_heroes, self._heroes_loaded)
        self.run_bg(lambda: self.guard.audit_history(force=True), self._audit_done)

    # ---------- background work ----------
    def run_bg(self, fn, done=None, failed=None):
        def worker():
            try:
                result = fn()
            except Exception as exc:  # shown to the user, never crashes the window
                self._jobs.put((failed or self._bg_error, exc))
            else:
                if done:
                    self._jobs.put((done, result))
        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                fn, arg = self._jobs.get_nowait()
                fn(arg)
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def _bg_error(self, exc: Exception):
        self.status(f"Something went wrong: {exc}", BAD)

    # ---------- layout ----------
    def _build(self):
        top = tk.Frame(self, bg=PANEL, padx=10, pady=8)
        top.pack(fill="x")
        tk.Label(top, text="I'm playing", bg=PANEL, fg=TEXT).pack(side="left")
        self.match_type = tk.StringVar(value="choose...")
        menu = tk.OptionMenu(top, self.match_type, *MATCH_TYPES, command=lambda _: self._mode_changed())
        self._style_menu(menu)
        menu.pack(side="left", padx=(6, 16))
        tk.Label(top, text="Stats from", bg=PANEL, fg=TEXT).pack(side="left")
        self.rank_filter = tk.StringVar(value="All ranks")
        menu = tk.OptionMenu(top, self.rank_filter, *RANK_FILTERS)
        self._style_menu(menu)
        menu.pack(side="left", padx=(6, 16))
        self.on_top = tk.BooleanVar(value=False)
        tk.Checkbutton(top, text="Keep window on top", variable=self.on_top, bg=PANEL, fg=TEXT,
                       selectcolor=CARD, activebackground=PANEL, activeforeground=TEXT,
                       command=lambda: self.attributes("-topmost", self.on_top.get())).pack(side="left")
        self._button(top, "Steam friend code...", self._ask_friend_code).pack(side="right")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG, padx=12, pady=10)
        left.pack(side="left", fill="y")
        right = tk.Frame(body, bg=BG, padx=4, pady=10)
        right.pack(side="left", fill="both", expand=True)

        # your hero + enemy team slots
        slots = tk.Frame(left, bg=BG)
        slots.pack(anchor="w")
        tk.Label(slots, text="You", bg=BG, fg=MUTED).grid(row=0, column=0, sticky="w")
        tk.Label(slots, text="Enemy team", bg=BG, fg=MUTED).grid(row=0, column=2, columnspan=TEAM_SIZE, sticky="w")
        self.slot_buttons: dict[str | int, tk.Label] = {}
        self.slot_buttons["me"] = self._slot(slots, "me")
        self.slot_buttons["me"].grid(row=1, column=0, padx=(0, 4))
        tk.Label(slots, text="vs", bg=BG, fg=MUTED).grid(row=1, column=1, padx=8)
        for i in range(TEAM_SIZE):
            self.slot_buttons[i] = self._slot(slots, i)
            self.slot_buttons[i].grid(row=1, column=2 + i, padx=2)
        tk.Label(left, text="Click a slot, then a hero below. Right-click a slot to clear it.",
                 bg=BG, fg=MUTED).pack(anchor="w", pady=(4, 6))

        # screen reading
        row = tk.Frame(left, bg=BG)
        row.pack(anchor="w", fill="x")
        self.detect_btn = self._button(row, "Read heroes from screen", self._detect_now)
        self.detect_btn.pack(side="left")
        tk.Checkbutton(row, text="Keep watching", variable=self.watching, bg=BG, fg=TEXT, selectcolor=CARD,
                       activebackground=BG, activeforeground=TEXT, command=self._toggle_watch).pack(side="left", padx=8)
        self._button(row, "Swap teams", self._swap_teams).pack(side="left")
        self._button(row, "From image...", self._detect_file).pack(side="left", padx=6)
        self.allies_row = tk.Frame(left, bg=BG)
        self.allies_row.pack(anchor="w", fill="x", pady=(6, 0))

        # hero grid
        search_row = tk.Frame(left, bg=BG)
        search_row.pack(anchor="w", fill="x", pady=(10, 4))
        tk.Label(search_row, text="Find hero", bg=BG, fg=MUTED).pack(side="left")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_grid())
        tk.Entry(search_row, textvariable=self.search, bg=CARD, fg=TEXT, insertbackground=TEXT,
                 relief="flat", width=18).pack(side="left", padx=6)
        self._button(search_row, "Clear all", self._clear_all).pack(side="right")
        self.grid_frame = tk.Frame(left, bg=BG)
        self.grid_frame.pack(anchor="w")

        self.advice_btn = tk.Button(left, text="Get advice", command=self._advise, bg=ACCENT, fg="#1a1a1a",
                                    activebackground="#f0c870", relief="flat", font=("Segoe UI", 12, "bold"),
                                    padx=16, pady=6, cursor="hand2")
        self.advice_btn.pack(anchor="w", pady=(12, 0), fill="x")

        # results
        text_frame = tk.Frame(right, bg=PANEL)
        text_frame.pack(fill="both", expand=True)
        self.out = tk.Text(text_frame, bg=PANEL, fg=TEXT, wrap="word", relief="flat", padx=14, pady=12,
                           font=("Segoe UI", 10), spacing1=2, cursor="arrow")
        sb = tk.Scrollbar(text_frame, command=self.out.yview)
        self.out.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.out.pack(side="left", fill="both", expand=True)
        for tag, opts in {
            "title": {"font": ("Segoe UI", 15, "bold"), "foreground": ACCENT, "spacing3": 6},
            "h": {"font": ("Segoe UI", 11, "bold"), "foreground": ACCENT, "spacing1": 12, "spacing3": 4},
            "muted": {"foreground": MUTED}, "good": {"foreground": GOOD}, "bad": {"foreground": BAD},
            "bold": {"font": ("Segoe UI", 10, "bold")}, "key": {"foreground": ALLY, "font": ("Consolas", 10, "bold")},
            "warn": {"foreground": BAD, "font": ("Segoe UI", 12, "bold")},
        }.items():
            self.out.tag_configure(tag, **opts)
        self._show_intro()

        self.status_var = tk.StringVar()
        self.status_label = tk.Label(self, textvariable=self.status_var, bg=PANEL, fg=MUTED, anchor="w", padx=10)
        self.status_label.pack(fill="x", side="bottom")
        self._refresh_slots()

    def _style_menu(self, menu):
        menu.configure(bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=TEXT, relief="flat",
                       highlightthickness=0)
        menu["menu"].configure(bg=CARD, fg=TEXT)

    def _button(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=CARD, fg=TEXT, activebackground="#343846",
                         activeforeground=TEXT, relief="flat", padx=8, pady=3, cursor="hand2")

    def _slot(self, parent, key):
        lbl = tk.Label(parent, bg=CARD, bd=0, highlightthickness=3, cursor="hand2")
        lbl.bind("<Button-1>", lambda _e: self._select_slot(key))
        lbl.bind("<Button-3>", lambda _e: self._set_slot(key, None))
        return lbl

    def status(self, text: str, colour: str = MUTED):
        self.status_var.set(text)
        self.status_label.configure(fg=colour)

    # ---------- heroes and portraits ----------
    def _load_heroes(self):
        return sorted(self.api.heroes(), key=lambda h: h["name"])

    def _heroes_loaded(self, heroes):
        self.heroes = heroes
        self.by_id = {int(h["id"]): h for h in heroes}
        self._fill_grid()
        self.status(f"{len(heroes)} heroes. Downloading portraits...")
        self.run_bg(self._load_portraits, self._portraits_loaded)

    def _fetch_image(self, url: str | None) -> Image.Image | None:
        if not url:
            return None
        try:
            return Image.open(io.BytesIO(self.api.image_bytes(url))).convert("RGBA")
        except Exception:
            return None

    def _load_portraits(self):
        icons, templates = {}, {}
        for h in self.heroes:
            imgs = h.get("images") or {}
            small = self._fetch_image(imgs.get("icon_image_small"))
            top_bar = self._fetch_image(imgs.get("top_bar_vertical_image"))
            if small:
                icons[int(h["id"])] = small
            templates[int(h["id"])] = [i for i in (top_bar, small) if i]
        detector = None
        if detect.available() and any(templates.values()):
            detector = detect.HeroDetector(templates)
        return icons, detector

    def _portraits_loaded(self, result):
        self.portraits, self.detector = result
        self.photos.clear()
        self._fill_grid()
        self._refresh_slots()
        missing = len(self.heroes) - len(self.portraits)
        msg = "Ready." + (f" {missing} portraits could not be downloaded." if missing else "")
        if not self.detector:
            msg += " Screen reading is off (needs opencv-python and the portraits)."
        self.status(msg)

    def photo(self, hero_id: int | None, size: int) -> ImageTk.PhotoImage:
        key = (hero_id or 0, size)
        if key not in self.photos:
            if hero_id is None:
                img = Image.new("RGB", (size, size), CARD)
            elif hero_id in self.portraits:
                img = ImageOps.fit(self.portraits[hero_id].convert("RGB"), (size, size))
            else:
                img = placeholder(self.by_id.get(hero_id, {}).get("name", "?"), size)
            self.photos[key] = ImageTk.PhotoImage(img)
        return self.photos[key]

    def _fill_grid(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()
        wanted = self.search.get().strip().lower()
        shown = [h for h in self.heroes if wanted in h["name"].lower()]
        cols = 8
        for i, h in enumerate(shown):
            hid = int(h["id"])
            cell = tk.Frame(self.grid_frame, bg=BG)
            cell.grid(row=i // cols, column=i % cols, padx=2, pady=2)
            btn = tk.Label(cell, image=self.photo(hid, ICON), bg=BG, cursor="hand2")
            btn.pack()
            name = h["name"] if len(h["name"]) <= 9 else h["name"][:8] + "."
            cap = tk.Label(cell, text=name, bg=BG, fg=MUTED, font=("Segoe UI", 7))
            cap.pack()
            for w in (btn, cap):
                w.bind("<Button-1>", lambda _e, hid=hid: self._pick(hid))

    # ---------- slots ----------
    def _select_slot(self, key):
        self.active_slot = key
        self._refresh_slots()

    def _set_slot(self, key, hero_id):
        if hero_id is not None:  # a hero can only be in one slot
            if self.me == hero_id:
                self.me = None
            self.enemies = [None if e == hero_id else e for e in self.enemies]
        if key == "me":
            self.me = hero_id
        else:
            self.enemies[key] = hero_id
        self._refresh_slots()

    def _pick(self, hero_id):
        self._set_slot(self.active_slot, hero_id)
        empty = [i for i, e in enumerate(self.enemies) if e is None]
        self.active_slot = empty[0] if empty else self.active_slot
        self._refresh_slots()

    def _refresh_slots(self):
        for key, lbl in self.slot_buttons.items():
            hid = self.me if key == "me" else self.enemies[key]
            border = ACCENT if key == self.active_slot else (ALLY if key == "me" else BAD)
            lbl.configure(image=self.photo(hid, SLOT_ICON), highlightbackground=border, highlightcolor=border)
        for w in self.allies_row.winfo_children():
            w.destroy()
        if self.detected_allies:
            tk.Label(self.allies_row, text="Your team (click yourself):", bg=BG, fg=MUTED).pack(side="left")
            for hid in self.detected_allies:
                b = tk.Label(self.allies_row, image=self.photo(hid, 32), bg=ALLY if hid == self.me else BG,
                             padx=2, pady=2, cursor="hand2")
                b.pack(side="left", padx=1)
                b.bind("<Button-1>", lambda _e, hid=hid: self._set_slot("me", hid))

    def _clear_all(self):
        self.me, self.enemies, self.detected_allies = None, [None] * TEAM_SIZE, []
        self.last_detected = []
        self.active_slot = "me"
        self._refresh_slots()

    def _swap_teams(self):
        if not self.detected_allies:
            self.status("Swap works after reading heroes from the screen.")
            return
        old_enemies = [e for e in self.enemies if e is not None]
        self.enemies = (self.detected_allies + [None] * TEAM_SIZE)[:TEAM_SIZE]
        self.detected_allies = old_enemies
        if self.me not in self.detected_allies:
            self.me = None
        self._refresh_slots()

    # ---------- ranked guard ----------
    def _mode_changed(self):
        if self.match_type.get() == "Ranked":
            self.watching.set(False)
            self._show_refusal("This helper is for learning in unranked games. It stays off in ranked "
                               "so nobody gets an unfair edge. Good luck in your match!")
        else:
            self.status(f"Mode: {self.match_type.get()}.")

    def _local_mode_ok(self) -> bool:
        """Quick check without network, used before reading the screen."""
        mode = self.match_type.get()
        if mode not in MATCH_TYPES:
            self.status("First pick what you're playing (top left).", BAD)
            return False
        if mode == "Ranked" or self.guard.locked_until > time.time():
            self._show_refusal(self.guard.check(mode).reason)
            return False
        return True

    def _ask_friend_code(self):
        current = self.guard.account_id or ""
        text = simpledialog.askstring(
            "Steam friend code",
            "Optional. Your Steam friend code (Steam > Friends > Add a Friend) lets the app check\n"
            "that you're not in a ranked match. Leave empty to turn this off.",
            initialvalue=str(current), parent=self)
        if text is None:
            return
        account = parse_friend_code(text)
        if text.strip() and account is None:
            messagebox.showerror("Steam friend code", "That doesn't look like a friend code (digits only).")
            return
        self.guard.set_account_id(account)
        self.status("Friend code saved." if account else "Friend code removed.")

    def _audit_done(self, message):
        if message:
            self._show_refusal(message)

    # ---------- screen reading ----------
    def _detect_now(self, image: Image.Image | None = None, auto_advise: bool = False):
        if self.busy_detect:
            return
        if not self.detector:
            self.status("Screen reading isn't ready (portraits still loading, or opencv-python missing).", BAD)
            return
        if not self._local_mode_ok():
            return
        self.busy_detect = True
        self.status("Reading the screen...")

        def work():
            shot = image or detect.grab_screen()
            result = self.detector.detect(shot, "top")
            if len(result.all) < 3:  # top bar not found; try the whole screen (scoreboard)
                result = self.detector.detect(shot, "full")
            try:
                debug = APP_DIR / "last_detection.png"
                detect.save_debug_image(shot, result, {i: h["name"] for i, h in self.by_id.items()}, debug)
            except Exception:
                pass
            return result

        def done(result: detect.DetectionResult):
            self.busy_detect = False
            self._apply_detection(result, auto_advise)

        def failed(exc):
            self.busy_detect = False
            self._bg_error(exc)

        self.run_bg(work, done, failed)

    def _apply_detection(self, result: detect.DetectionResult, auto_advise: bool):
        if not result.all:
            self.status("No hero portraits found. Open the game with the top bar visible, or press Esc/Tab "
                        "for the scoreboard, then try again.", BAD)
            return
        names = lambda dets: ", ".join(self.by_id[d.hero_id]["name"] for d in dets if d.hero_id in self.by_id)
        new_enemies = [d.hero_id for d in result.enemies][:TEAM_SIZE]
        changed = new_enemies != self.last_detected
        if auto_advise and not changed:
            return  # same as last read: keep any fixes the user made by hand
        self.last_detected = new_enemies
        self.detected_allies = [d.hero_id for d in result.allies]
        self.enemies = (new_enemies + [None] * TEAM_SIZE)[:TEAM_SIZE]
        if self.me in new_enemies:
            self.me = None
        if self.me is None and len(self.detected_allies) == 1:
            self.me = self.detected_allies[0]
        self._refresh_slots()
        msg = f"Found enemies: {names(result.enemies) or 'none'}. Teammates: {names(result.allies) or 'none'}."
        if self.me is None:
            msg += " Click yourself in 'Your team'."
        self.status(msg + " Wrong? Fix any slot by hand.", GOOD)
        if auto_advise and changed and self.me is not None and new_enemies:
            self._advise()

    def _detect_file(self):
        path = filedialog.askopenfilename(title="Screenshot of the game",
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")])
        if path:
            self._detect_now(Image.open(path))

    def _toggle_watch(self):
        if self.watching.get():
            if not self._local_mode_ok():
                self.watching.set(False)
                return
            self.status("Watching the screen every few seconds. Advice updates when the enemy team changes.")
            self._watch_tick()

    def _watch_tick(self):
        if not self.watching.get():
            return
        self._detect_now(auto_advise=True)
        self.after(WATCH_EVERY_MS, self._watch_tick)

    # ---------- advice ----------
    def _advise(self):
        if self.me is None:
            self.status("Pick your hero first (the 'You' slot).", BAD)
            self._select_slot("me")
            return
        mode = self.match_type.get()
        hero = self.by_id[self.me]["name"]
        enemies = [self.by_id[e]["name"] for e in self.enemies if e is not None]
        badge = RANK_FILTERS.get(self.rank_filter.get())
        self.advice_btn.configure(state="disabled", text="Working...")
        self.status(f"Getting advice for {hero}... (first time for a hero can take 10-20 seconds)")

        def work():
            verdict = self.guard.check(mode)
            if not verdict.allowed:
                return verdict
            lock_msg = self.guard.audit_history()
            if lock_msg:
                return lock_msg
            rec = recommend(self.api, hero, enemies, badge)
            self.guard.record_advice()
            return rec

        def done(result):
            self.advice_btn.configure(state="normal", text="Get advice")
            if isinstance(result, Recommendation):
                self._show_recommendation(result)
                self.status("Done.", GOOD)
            else:
                self.watching.set(False)
                self._show_refusal(getattr(result, "reason", result))

        def failed(exc):
            self.advice_btn.configure(state="normal", text="Get advice")
            self._bg_error(exc)

        self.run_bg(work, done, failed)

    # ---------- output ----------
    def _write(self, text, *tags):
        self.out.insert("end", text, tags)

    def _clear_out(self):
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")

    def _show_intro(self):
        self._clear_out()
        self._write("Deadlock learning helper\n", "title")
        self._write("1. Say what you're playing (top left). The helper stays off in ranked.\n")
        self._write("2. Click the 'You' slot and pick your hero, then fill in the enemy team.\n")
        self._write("   Or press 'Read heroes from screen' while the game shows its top bar or "
                    "scoreboard, and fix anything it gets wrong.\n")
        self._write("3. Press Get advice.\n\n")
        self._write("It only looks at the screen like you do. It never reads or changes the game.\n", "muted")
        self.out.configure(state="disabled")

    def _show_refusal(self, reason):
        self._clear_out()
        self._write("Helper is off\n", "title")
        self._write(f"{reason}\n", "warn")
        self.out.configure(state="disabled")
        self.status(str(reason), BAD)

    def _show_recommendation(self, rec: Recommendation):
        self._clear_out()
        w = self._write
        w(rec.hero, "title")
        if rec.enemies:
            w("  vs  " + ", ".join(rec.enemies), "muted")
        w("\n")

        w("How to play\n", "h")
        for note in rec.playstyle or ["No notes yet."]:
            w(f"•  {note}\n")

        w("Ability to max (first to last)\n", "h")
        if rec.ability_max_order:
            w("  >  ".join(rec.ability_max_order) + "\n", "bold")
            w(f"Most successful order in {rec.ability_order_matches:,} games.\n", "muted")
        else:
            w("Not enough data.\n", "muted")

        if rec.ability_steps:
            w("Ability points, step by step\n", "h")
            for st in rec.ability_steps:
                w(f"{st.step:>2}. ")
                w(f"[{st.key}]" if st.key else "   ", "key")
                w(f" {st.ability}  ", "bold")
                w(f"{st.action}", "good" if st.rank == 0 else "")
                w(f"   {st.effect}\n" if st.effect else "\n", "muted")

        w("Core items by tier\n", "h")
        for tier, picks in rec.core_items.items():
            w(f"Tier {tier}  ({TIER_COST.get(tier, '?')} souls)\n", "bold")
            for p in picks:
                w(f"    {p.name}", "")
                w(f"   {p.slot}  ·  {p.win_rate:.1%} won  ·  {p.matches:,} games\n", "muted")
        if 4 in rec.core_items:
            w("Tier 4 items look extra good partly because only winning games get that far. "
              "Compare items within a tier.\n", "muted")

        if rec.counter_items:
            w("Small edges against this enemy team\n", "h")
            for p in rec.counter_items:
                w(f"    {p.name}", "")
                w(f"   {p.note}\n", "good")
            w("Nice to have; never skip a core item for these.\n", "muted")

        if rec.matchups:
            w("How you do against each enemy\n", "h")
            w("Your win rate vs each enemy, compared with what both heroes' overall strength predicts.\n",
              "muted")
            for mu in sorted(rec.matchups, key=lambda x: -x.edge):
                label, tag = (("favoured", "good") if mu.edge >= MATCHUP_EDGE else
                              ("tough", "bad") if mu.edge <= -MATCHUP_EDGE else ("even", "muted"))
                w(f"    vs {mu.enemy}  ", "bold")
                w(f"{mu.win_rate:.1%}  ({mu.edge * 100:+.1f} pts)  ")
                w(f"{label}", tag)
                w(f"   {mu.games:,} games\n", "muted")
        self.out.configure(state="disabled")
        self.out.yview_moveto(0)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
