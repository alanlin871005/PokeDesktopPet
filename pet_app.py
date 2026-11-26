r"""
Poke Finder Windows 透明互動桌寵（全功能版）
- 支援 PyInstaller 單檔攜帶模式（自動唯讀掃描本機 Chrome/Edge/Brave Poke Finder 擴充與存檔）
- 支援圖鑑盒長按拖曳召喚到桌面任意位置、Win32 視窗標題列棲息、拋物線像素樹果互動與親密度培養
- 支援背景自動增量偵測新捕獲寶可夢、CPU/RAM/GPU 負載提醒、深夜催睡與久坐喝水番茄鐘
- 支援原版 Poke Finder .wav 音效與 8-bit 叫聲彩蛋（附靜音開關）
- 支援零額外開 Port 的本機檔案佇列（data/remote_cmd.json），可搭配 pet_ctl.py 與 Telegram 阿飛連動
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageTk

import sound_fx
import sync_pokefinder
import win_tracker

APP_ROOT = sync_pokefinder.APP_ROOT
DATA_DIR = sync_pokefinder.DATA_DIR
CAUGHT_JSON = sync_pokefinder.CAUGHT_JSON
SETTINGS_JSON = DATA_DIR / "settings.json"
REMOTE_CMD_JSON = DATA_DIR / "remote_cmd.json"
PET_STATUS_JSON = DATA_DIR / "pet_status.json"

TRANSPARENT_KEY = "#ff00fe"
TRANSPARENT_RGB = (255, 0, 254)
MAX_PETS = 6
CREATE_NO_WINDOW = 0x08000000

TYPE_ZH = {
    "normal": ("一般", "#A8A77A"),
    "fire": ("火", "#EE8130"),
    "water": ("水", "#6390F0"),
    "electric": ("電", "#F7D02C"),
    "grass": ("草", "#7AC74C"),
    "ice": ("冰", "#96D9D6"),
    "fighting": ("格鬥", "#C22E28"),
    "poison": ("毒", "#A33EA1"),
    "ground": ("地面", "#E2BF65"),
    "flying": ("飛行", "#A98FF3"),
    "psychic": ("超能力", "#F95587"),
    "bug": ("蟲", "#A6B91A"),
    "rock": ("岩石", "#B6A136"),
    "ghost": ("幽靈", "#735797"),
    "dragon": ("龍", "#6F35FC"),
    "dark": ("惡", "#705746"),
    "steel": ("鋼", "#B7B7CE"),
    "fairy": ("妖精", "#D685AD"),
}

CUSTOM_QUOTES: dict[str, list[str]] = {
    "celestial:shadow-mewtwo": [
        "…別分心，我在看著你工作。",
        "暗影之力隨時待命！⚡",
        "哼，今天就勉為其難陪你加班吧。",
        "（念力浮空中…）",
    ],
    "pikachu": [
        "皮卡皮卡！⚡",
        "皮卡～啾！❤",
        "今天也要元氣滿滿喔！✨",
        "摸頭會觸電喔～（開玩笑的）",
    ],
}

TYPE_QUOTES: dict[str, list[str]] = {
    "fire": ["暖呼呼的～🔥", "燃起來吧！"],
    "water": ["記得多喝水喔！💧", "咕嚕咕嚕～"],
    "electric": ["電力滿滿！⚡", "充個電繼續加油！"],
    "grass": ["休息一下看點綠色吧 🌿", "好想曬太陽～"],
    "psychic": ["我感應到你快收工了 ✨", "專心、專心～"],
    "ghost": ["嘻嘻…別被我嚇到喔 👻", "飄來飄去～"],
    "dragon": ["有我在，什麼難題都搞定！🐉", "吼喔——！"],
    "normal": ["陪你一起工作真開心 ❤", "摸摸頭～♪"],
}


def get_affection_info(score: int) -> tuple[int, str]:
    if score >= 25:
        return 5, "💖💖💖"
    if score >= 15:
        return 4, "❤️❤️"
    if score >= 8:
        return 3, "❤️"
    if score >= 3:
        return 2, "🩷"
    return 1, "🤍"


def _acquire_single_instance_mutex() -> bool:
    """Return True if this is the primary instance; False if another instance is already running."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\PokeDesktopPet_SingleInstance_Mutex")
        ERROR_ALREADY_EXISTS = 183
        if handle and kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
    except Exception:
        pass
    return True


def _enqueue_local_action(cmd: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if REMOTE_CMD_JSON.exists():
        try:
            loaded = json.loads(REMOTE_CMD_JSON.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except Exception:
            pass
    existing.append({"ts": time.time(), **cmd})
    tmp = DATA_DIR / f".remote_cmd.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, REMOTE_CMD_JSON)


def load_gif_frames(gif_path: str | Path, scale: int, flip: bool = False) -> tuple[list[ImageTk.PhotoImage], list[int], int, int]:
    """Load an animated pixel-art GIF into crisp transparent-key PhotoImages."""
    img = Image.open(gif_path)
    frames: list[ImageTk.PhotoImage] = []
    durations: list[int] = []
    w, h = img.size
    sw, sh = max(1, w * scale), max(1, h * scale)

    idx = 0
    while True:
        try:
            img.seek(idx)
        except EOFError:
            break
        rgba = img.convert("RGBA")
        if flip:
            rgba = ImageOps.mirror(rgba)
        scaled = rgba.resize((sw, sh), Image.Resampling.NEAREST)

        bg = Image.new("RGB", (sw, sh), TRANSPARENT_RGB)
        alpha = scaled.getchannel("A")
        mask = alpha.point(lambda a: 255 if a >= 128 else 0)
        bg.paste(scaled.convert("RGB"), (0, 0), mask)

        frames.append(ImageTk.PhotoImage(bg))
        dur = int(img.info.get("duration", 125) or 125)
        durations.append(max(60, min(dur, 400)))
        idx += 1

    if not frames:
        fallback = Image.new("RGB", (32 * scale, 32 * scale), TRANSPARENT_RGB)
        frames = [ImageTk.PhotoImage(fallback)]
        durations = [150]
    return frames, durations, sw, sh


def _render_pixel_sprite(grid: list[str], palette: dict[str, tuple[int, int, int]], scale: int = 2) -> ImageTk.PhotoImage:
    h = len(grid)
    w = len(grid[0]) if h else 1
    img = Image.new("RGB", (w, h), TRANSPARENT_RGB)
    px = img.load()
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            if ch in palette:
                px[x, y] = palette[ch]
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.Resampling.NEAREST)
    return ImageTk.PhotoImage(img)


def make_berry_photo(kind: str, scale: int = 2) -> tuple[ImageTk.PhotoImage, int, int]:
    # 14x14 crisp pixel-art berries
    grid = [
        "......gg......",
        "....ggGGg.....",
        "...gGGgg......",
        "....oooGoo....",
        "..ooBBBBBBoo..",
        ".oBBhhBBBBbbo.",
        ".oBhBBBBBBbbo.",
        "oBBBBBBBBbbboo",
        "oBBBBBBBBbbboo",
        "oBBBBbbbBbbboo",
        ".oBBbbbbbbboo.",
        ".ooBbbbbbbboo.",
        "...ooooooooo..",
        "..............",
    ]
    palettes = {
        "oran": {
            "o": (23, 37, 84),
            "B": (59, 130, 246),
            "b": (29, 78, 216),
            "h": (191, 219, 254),
            "g": (21, 128, 61),
            "G": (74, 222, 128),
        },
        "sitrus": {
            "o": (113, 63, 18),
            "B": (250, 204, 21),
            "b": (202, 138, 4),
            "h": (254, 249, 195),
            "g": (21, 128, 61),
            "G": (74, 222, 128),
        },
        "razz": {
            "o": (127, 29, 29),
            "B": (244, 63, 94),
            "b": (190, 18, 60),
            "h": (254, 205, 211),
            "g": (22, 163, 74),
            "G": (134, 239, 172),
        },
    }
    pal = palettes.get(kind, palettes["razz"])
    return _render_pixel_sprite(grid, pal, scale=scale), 14 * scale, 14 * scale


def make_heart_photo(scale: int = 2) -> tuple[ImageTk.PhotoImage, int, int]:
    grid = [
        ".ooo...ooo.",
        "oRRRo.oRRRo",
        "oRhRRoRRRRo",
        "oRRRRRRRRRo",
        "oRRRRRRRdro",
        ".oRRRRRdro.",
        "..oRRRdro..",
        "...oRdro...",
        "....odo....",
        ".....o.....",
    ]
    pal = {
        "o": (136, 19, 55),
        "R": (251, 113, 133),
        "r": (225, 29, 72),
        "d": (190, 18, 60),
        "h": (255, 228, 230),
    }
    return _render_pixel_sprite(grid, pal, scale=scale), 11 * scale, 10 * scale


def make_single_frame_photo(gif_path: str | Path, scale: int = 2) -> tuple[ImageTk.PhotoImage, int, int]:
    try:
        im = Image.open(gif_path).convert("RGBA")
        w, h = im.size
        sw, sh = max(1, w * scale), max(1, h * scale)
        scaled = im.resize((sw, sh), Image.Resampling.NEAREST)
        bg = Image.new("RGB", (sw, sh), TRANSPARENT_RGB)
        mask = scaled.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
        bg.paste(scaled.convert("RGB"), (0, 0), mask)
        return ImageTk.PhotoImage(bg), sw, sh
    except Exception:
        fallback = Image.new("RGB", (48, 48), TRANSPARENT_RGB)
        return ImageTk.PhotoImage(fallback), 48, 48


class SpeechBubble:
    """Lightweight floating Traditional Chinese speech bubble above a pet."""

    def __init__(self, master: tk.Misc) -> None:
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#1e2230")
        self.label = tk.Label(
            self.win,
            text="",
            bg="#1e2230",
            fg="#f8fafc",
            font=("Microsoft JhengHei UI", 10, "bold"),
            padx=10,
            pady=6,
            bd=1,
            relief="solid",
            highlightthickness=1,
            highlightbackground="#60a5fa",
            wraplength=260,
            justify="left",
        )
        self.label.pack()
        self.win.withdraw()
        self._hide_job: str | None = None

    def show(self, text: str, x: int, y: int, duration_ms: int = 3200) -> None:
        if self._hide_job:
            try:
                self.win.after_cancel(self._hide_job)
            except Exception:
                pass
        self.label.config(text=text)
        self.win.update_idletasks()
        bw = self.win.winfo_reqwidth()
        bh = self.win.winfo_reqheight()
        left, top, right, _ = win_tracker.get_work_area()
        bx = max(left + 8, min(x - bw // 2, right - bw - 8))
        by = max(top + 8, y - bh - 6)
        self.win.geometry(f"+{bx}+{by}")
        self.win.deiconify()
        self.win.lift()
        self._hide_job = self.win.after(duration_ms, self.hide)

    def move_to(self, x: int, y: int) -> None:
        try:
            if self.win.state() == "normal":
                bw = self.win.winfo_reqwidth()
                bh = self.win.winfo_reqheight()
                left, top, right, _ = win_tracker.get_work_area()
                bx = max(left + 8, min(x - bw // 2, right - bw - 8))
                by = max(top + 8, y - bh - 6)
                self.win.geometry(f"+{bx}+{by}")
        except Exception:
            pass

    def hide(self) -> None:
        self._hide_job = None
        try:
            self.win.withdraw()
        except Exception:
            pass

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass


class HeartParticle:
    """Floating pixel heart particle that rises and fades away after eating a berry."""

    def __init__(self, manager: "PetManager", x: int, y: int) -> None:
        self.manager = manager
        self.win = tk.Toplevel(manager.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT_KEY)
        self.win.attributes("-transparentcolor", TRANSPARENT_KEY)

        self.photo, self.w, self.h = make_heart_photo(scale=2)
        lbl = tk.Label(self.win, image=self.photo, bg=TRANSPARENT_KEY, bd=0, highlightthickness=0)
        lbl.pack()
        self.x = float(x - self.w // 2)
        self.y = float(y - self.h)
        self.life = 26
        self.vx = random.uniform(-0.8, 0.8)
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")
        self._step()

    def _step(self) -> None:
        self.life -= 1
        if self.life <= 0:
            try:
                self.win.destroy()
            except Exception:
                pass
            return
        self.x += self.vx
        self.y -= 2.1
        try:
            if self.life < 10:
                self.win.attributes("-alpha", max(0.15, self.life / 10.0))
            self.win.geometry(f"+{int(self.x)}+{int(self.y)}")
            self.win.after(33, self._step)
        except Exception:
            pass


class BerryEntity:
    """Throwable parabolic pixel-art berry that lands on windows/taskbar for pets to eat."""

    def __init__(self, manager: "PetManager", start_x: int, start_y: int) -> None:
        self.manager = manager
        self.kind = random.choice(("razz", "oran", "sitrus"))
        self.win = tk.Toplevel(manager.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT_KEY)
        self.win.attributes("-transparentcolor", TRANSPARENT_KEY)

        self.photo, self.w, self.h = make_berry_photo(self.kind, scale=2)
        lbl = tk.Label(self.win, image=self.photo, bg=TRANSPARENT_KEY, bd=0, highlightthickness=0)
        lbl.pack()

        left, top, right, bottom = win_tracker.get_work_area()
        self.x = float(max(left + 20, min(start_x - self.w // 2, right - self.w - 20)))
        self.y = float(max(top + 20, min(start_y, bottom - self.h - 40)))
        self.vx = random.choice([-1, 1]) * random.uniform(3.2, 6.2)
        self.vy = random.uniform(-10.5, -7.0)
        self.settled = False
        self.bounces = 0
        self.alive = True
        self.age_ticks = 0
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")
        self._tick()

    def _tick(self) -> None:
        if not self.alive:
            return
        self.age_ticks += 1
        if self.age_ticks > 900:  # 30s timeout safety
            self.consume()
            return

        left, top, right, bottom = win_tracker.get_work_area()
        floor_y = float(bottom - self.h)

        if not self.settled:
            prev_bottom = self.y + self.h
            self.vy += 0.65
            self.x += self.vx
            next_y = self.y + self.vy

            if self.x <= left + 8:
                self.x = float(left + 8)
                self.vx = abs(self.vx) * 0.75
            elif self.x >= right - self.w - 8:
                self.x = float(right - self.w - 8)
                self.vx = -abs(self.vx) * 0.75

            landed_win = None
            if self.vy > 0 and self.manager.perch_enabled:
                landed_win = win_tracker.find_landing_window(
                    self.manager.perch_windows,
                    self.x + self.w / 2,
                    prev_bottom,
                    next_y + self.h,
                    top,
                    margin=10,
                )

            if landed_win is not None:
                self.y = float(landed_win.top - self.h)
                if abs(self.vy) > 3.2 and self.bounces < 3:
                    self.vy = -self.vy * 0.48
                    self.vx *= 0.72
                    self.bounces += 1
                else:
                    self.vy = 0.0
                    self.vx = 0.0
                    self.settled = True
            elif next_y >= floor_y:
                self.y = floor_y
                if abs(self.vy) > 3.2 and self.bounces < 3:
                    self.vy = -self.vy * 0.48
                    self.vx *= 0.72
                    self.bounces += 1
                else:
                    self.vy = 0.0
                    self.vx = 0.0
                    self.settled = True
            else:
                self.y = next_y

            try:
                self.win.geometry(f"+{int(self.x)}+{int(self.y)}")
            except Exception:
                pass

        try:
            self.win.after(33, self._tick)
        except Exception:
            pass

    def consume(self) -> None:
        if not self.alive:
            return
        self.alive = False
        if self in self.manager.berries:
            self.manager.berries.remove(self)
        try:
            self.win.destroy()
        except Exception:
            pass


class DesktopPet:
    """Single interactive transparent Pokémon desktop pet window."""

    def __init__(
        self,
        manager: "PetManager",
        pokemon: dict[str, Any],
        start_x: int | None = None,
        start_y: int | None = None,
        play_spawn_sfx: bool = True,
    ) -> None:
        self.manager = manager
        self.pokemon = pokemon
        self.scale = int(manager.settings.get("scale", 3))
        self.mode = manager.settings.get("mode", "wander")  # wander | follow | idle
        self.floating = bool(manager.settings.get("floating", False))
        self.topmost = bool(manager.settings.get("topmost", True))
        self.chatter = bool(manager.settings.get("chatter", True))

        self.win = tk.Toplevel(manager.root)
        self.win.overrideredirect(True)
        self.win.configure(bg=TRANSPARENT_KEY)
        self.win.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.win.attributes("-topmost", self.topmost)

        self.label = tk.Label(self.win, bg=TRANSPARENT_KEY, bd=0, highlightthickness=0)
        self.label.pack()

        self.bubble = SpeechBubble(self.win)

        self.anim_frames: dict[tuple[str, int], tuple[list[ImageTk.PhotoImage], list[int]]] = {}
        self.w = 96
        self.h = 96
        self.x = 0.0
        self.y = 0.0
        self.state = "idle"
        self.facing = random.choice([-1, 1])
        self.frame_idx = 0

        self._load_sprites()

        left, top, right, bottom = win_tracker.get_work_area()
        self.x = float(
            max(left + 8, min(start_x, right - self.w - 8))
            if start_x is not None
            else random.randint(left + 120, max(left + 140, right - self.w - 120))
        )
        self.y = float(
            max(top + 8, min(start_y, bottom - self.h))
            if start_y is not None
            else (bottom - self.h)
        )
        self.vx = 0.0
        self.vy = 0.0
        self.perched_hwnd: int | None = None
        self.prev_perch_rect: win_tracker.WindowRect | None = None
        self.state_timer = random.randint(40, 120)
        self.chatter_cooldown = random.randint(350, 750)
        self.berry_notice_cooldown = 0
        self.dragging = False
        self.drag_moved = False
        self.drag_off_x = 0
        self.drag_off_y = 0
        self.alive = True

        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

        self.label.bind("<ButtonPress-1>", self._on_press)
        self.label.bind("<B1-Motion>", self._on_drag)
        self.label.bind("<ButtonRelease-1>", self._on_release)
        self.label.bind("<Button-3>", self._on_right_click)
        self.label.bind("<Double-Button-1>", self._on_double_click)

        self.say(f"{self.pokemon['name_zh']} 登場！✨", 2600)
        if play_spawn_sfx:
            self.manager.sound.play_event("spawn")
        self._animate()
        self._tick()

    def _load_sprites(self) -> None:
        self.anim_frames.clear()
        for anim_name, path_key in (("idle", "idle_gif"), ("walk", "walk_gif")):
            gif_path = sync_pokefinder.resolve_sprite_path(self.pokemon[path_key])
            f_left, d_left, w, h = load_gif_frames(gif_path, self.scale, flip=False)
            f_right, d_right, _, _ = load_gif_frames(gif_path, self.scale, flip=True)
            self.anim_frames[(anim_name, -1)] = (f_left, d_left)
            self.anim_frames[(anim_name, 1)] = (f_right, d_right)
            self.w, self.h = w, h
        self.frame_idx = 0
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

    def set_pokemon(self, pokemon: dict[str, Any]) -> None:
        self.pokemon = pokemon
        old_bottom = self.y + self.h
        self._load_sprites()
        left, top, right, bottom = win_tracker.get_work_area()
        self.y = min(old_bottom - self.h, bottom - self.h)
        self.x = max(left, min(self.x, right - self.w))
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")
        self.say(f"換 {pokemon['name_zh']} 上場！✨", 2500)
        self.manager.sound.play_event("spawn")
        self.manager.save_settings()
        self.manager.write_status()

    def set_scale(self, scale: int) -> None:
        self.scale = scale
        old_bottom = self.y + self.h
        self._load_sprites()
        _, _, _, bottom = win_tracker.get_work_area()
        self.y = min(old_bottom - self.h, bottom - self.h)
        self.win.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

    def set_topmost(self, val: bool) -> None:
        self.topmost = val
        self.win.attributes("-topmost", val)

    def _pick_quote(self) -> str:
        pid = self.pokemon["pokemon_id"]
        if pid in CUSTOM_QUOTES:
            return random.choice(CUSTOM_QUOTES[pid])
        if "pikachu" in pid:
            return random.choice(CUSTOM_QUOTES["pikachu"])
        pool = [
            f"{self.pokemon['name_zh']} 很開心！❤",
            f"我是 {self.pokemon['name_zh']}～✨",
            "摸摸頭好舒服～♪",
        ]
        for t in self.pokemon.get("types", []):
            pool.extend(TYPE_QUOTES.get(t, []))
        return random.choice(pool)

    def say(self, text: str, duration_ms: int = 3000) -> None:
        self.bubble.show(text, int(self.x + self.w / 2), int(self.y), duration_ms)

    def jump(self, vy: float = -8.5) -> None:
        if not self.floating:
            self.perched_hwnd = None
            self.prev_perch_rect = None
            self.vy = vy

    def _on_press(self, event: tk.Event) -> None:
        self.dragging = True
        self.drag_moved = False
        self.drag_off_x = event.x
        self.drag_off_y = event.y
        self.vy = 0.0
        self.vx = 0.0
        self.perched_hwnd = None
        self.prev_perch_rect = None

    def _on_drag(self, event: tk.Event) -> None:
        if not self.dragging:
            return
        nx = self.win.winfo_pointerx() - self.drag_off_x
        ny = self.win.winfo_pointery() - self.drag_off_y
        if abs(nx - self.x) > 4 or abs(ny - self.y) > 4:
            self.drag_moved = True
        self.x = float(nx)
        self.y = float(ny)
        self.win.geometry(f"+{int(self.x)}+{int(self.y)}")
        self.bubble.move_to(int(self.x + self.w / 2), int(self.y))

    def _on_release(self, _event: tk.Event) -> None:
        self.dragging = False
        if not self.drag_moved:
            if not self.floating:
                self.perched_hwnd = None
                self.prev_perch_rect = None
                self.vy = -8.5
            self.say(self._pick_quote(), 2800)
            if random.random() < 0.28:
                self.manager.sound.play_cry(self.pokemon)
            else:
                self.manager.sound.play_event("pet")

    def _on_double_click(self, _event: tk.Event) -> None:
        self.manager.open_pokedex(target_pet=self)

    def _on_right_click(self, event: tk.Event) -> None:
        menu = tk.Menu(self.win, tearoff=0, font=("Microsoft JhengHei UI", 10))
        shiny_tag = " ✨閃光" if self.pokemon.get("is_shiny") else ""
        aff_score = self.manager.get_affection(self.pokemon["key"])
        aff_lv, aff_hearts = get_affection_info(aff_score)
        menu.add_command(
            label=f"🐾 {self.pokemon['name_zh']}{shiny_tag}（第 {self.pokemon['count']} 隻）",
            state="disabled",
        )
        menu.add_command(
            label=f"💖 親密度：Lv.{aff_lv} {aff_hearts}（{aff_score} 分）",
            state="disabled",
        )
        menu.add_separator()

        menu.add_command(
            label="🍓 丟一顆樹果給桌寵吃",
            command=lambda: self.manager.throw_berry(event.x_root, max(60, event.y_root - 100)),
        )
        menu.add_command(
            label="🔊 叫一聲彩蛋！",
            command=lambda: (self.manager.sound.play_cry(self.pokemon), self.say(f"{self.pokemon['name_zh']}：啾！♪", 2200)),
        )
        menu.add_separator()
        menu.add_command(
            label="📖 打開我的寶可夢圖鑑盒（支援拖曳召喚）",
            command=lambda: self.manager.open_pokedex(target_pet=self),
        )
        if len(self.manager.pets) < MAX_PETS:
            menu.add_command(label="🎲 隨機再召喚一隻夥伴", command=self.manager.spawn_random_pet)
        menu.add_separator()

        mode_menu = tk.Menu(menu, tearoff=0, font=("Microsoft JhengHei UI", 10))
        for m_id, m_label in (("wander", "自由散步"), ("follow", "跟隨滑鼠"), ("idle", "乖乖待在原地")):
            prefix = "✓ " if self.mode == m_id else "   "
            mode_menu.add_command(label=f"{prefix}{m_label}", command=lambda m=m_id: self._set_mode(m))
        menu.add_cascade(label="🏃 行為模式", menu=mode_menu)

        scale_menu = tk.Menu(menu, tearoff=0, font=("Microsoft JhengHei UI", 10))
        for s in (2, 3, 4, 5):
            prefix = "✓ " if self.scale == s else "   "
            scale_menu.add_command(label=f"{prefix}{s}x 像素大小", command=lambda sc=s: self.manager.set_all_scale(sc))
        menu.add_cascade(label="📏 調整大小", menu=scale_menu)

        menu.add_command(
            label=f"{'✓ ' if self.manager.perch_enabled else '   '}🪟 跳上視窗標題列",
            command=self.manager.toggle_perch,
        )
        if self.perched_hwnd is not None:
            menu.add_command(label="⬇️ 跳回工作列地面", command=self._drop_to_floor)
        menu.add_command(
            label=f"{'✓ ' if self.floating else '   '}🎈 懸浮模式（不掉回工作列）",
            command=self._toggle_floating,
        )
        menu.add_command(
            label=f"{'✓ ' if self.topmost else '   '}📌 永遠置頂",
            command=self._toggle_topmost,
        )
        menu.add_command(
            label=f"{'✓ ' if self.chatter else '   '}💬 偶爾冒泡講話",
            command=self._toggle_chatter,
        )
        menu.add_command(
            label=f"{'✓ ' if self.manager.sound.enabled else '   '}🔊 原版音效與叫聲",
            command=self.manager.toggle_sound,
        )

        # Butler & System monitor submenu
        butler_menu = tk.Menu(menu, tearoff=0, font=("Microsoft JhengHei UI", 10))
        st = self.manager.sys_stats
        gpu_txt = f"｜GPU {st['gpu']}%" if st.get("gpu") is not None else ""
        butler_menu.add_command(
            label=f"🖥️ 負載：CPU {st.get('cpu', 0):.0f}%｜RAM {st.get('ram', 0):.0f}%{gpu_txt}",
            state="disabled",
        )
        butler_menu.add_separator()
        butler_menu.add_command(
            label=f"{'✓ ' if self.manager.hydration_enabled else '   '}💧 久坐／喝水番茄鐘提醒",
            command=self.manager.toggle_hydration,
        )
        for mins in (30, 45, 60):
            prefix = "✓ " if self.manager.hydration_interval_min == mins else "   "
            butler_menu.add_command(
                label=f"{prefix}⏱️ 提醒間隔：{mins} 分鐘",
                command=lambda m=mins: self.manager.set_hydration_interval(m),
            )
        butler_menu.add_command(label="🔔 立即測試喝水提醒", command=self.manager.trigger_hydration_reminder)
        butler_menu.add_command(label="🔁 重新計算喝水時間", command=self.manager.reset_hydration_timer)
        butler_menu.add_separator()
        butler_menu.add_command(
            label=f"{'✓ ' if self.manager.butler_enabled else '   '}🌡️ 高負載與深夜催睡提醒",
            command=self.manager.toggle_butler,
        )
        butler_menu.add_command(
            label=f"{'✓ ' if self.manager.auto_sync_enabled else '   '}🔍 背景自動偵測新抓寶可夢",
            command=self.manager.toggle_auto_sync,
        )
        menu.add_cascade(label="🤖 貼心管家與系統狀態", menu=butler_menu)

        menu.add_separator()
        menu.add_command(label="🔄 立即同步瀏覽器 Poke Finder 存檔", command=lambda: self.manager.sync_now(notify_pet=self))
        menu.add_separator()
        if len(self.manager.pets) > 1:
            menu.add_command(label="📥 收回這隻寶可夢", command=lambda: self.manager.remove_pet(self))
        menu.add_command(label="❌ 關閉全部桌寵", command=self.manager.quit_all)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _drop_to_floor(self) -> None:
        self.perched_hwnd = None
        self.prev_perch_rect = None
        self.vy = 1.5
        self.say("跳下來囉～", 1600)

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.manager.settings["mode"] = mode
        self.manager.save_settings()
        labels = {"wander": "自由散步模式！", "follow": "跟著你走囉！", "idle": "好的，乖乖待在這裡～"}
        self.say(labels[mode], 2000)

    def _toggle_floating(self) -> None:
        self.floating = not self.floating
        if self.floating:
            self.perched_hwnd = None
            self.prev_perch_rect = None
        self.manager.settings["floating"] = self.floating
        self.manager.save_settings()
        self.say("懸浮模式開啟！🎈" if self.floating else "回到地面散步囉！", 2000)

    def _toggle_topmost(self) -> None:
        self.set_topmost(not self.topmost)
        self.manager.settings["topmost"] = self.topmost
        self.manager.save_settings()

    def _toggle_chatter(self) -> None:
        self.chatter = not self.chatter
        self.manager.settings["chatter"] = self.chatter
        self.manager.save_settings()

    def _animate(self) -> None:
        if not self.alive:
            return
        frames, durations = self.anim_frames[(self.state, self.facing)]
        if self.frame_idx >= len(frames):
            self.frame_idx = 0
        self.label.config(image=frames[self.frame_idx])
        dur = durations[self.frame_idx]
        self.frame_idx = (self.frame_idx + 1) % len(frames)
        self.win.after(dur, self._animate)

    def _find_closest_berry(self) -> BerryEntity | None:
        if not self.manager.berries:
            return None
        cx = self.x + self.w / 2
        cy = self.y + self.h
        best = None
        best_dist = 1e9
        for b in self.manager.berries:
            if not b.alive:
                continue
            bx = b.x + b.w / 2
            by = b.y + b.h
            d = abs(bx - cx) + abs(by - cy) * 0.6
            if d < best_dist:
                best_dist = d
                best = b
        return best

    def _try_jump_onto_window(self, work_top: int) -> bool:
        if not self.manager.perch_enabled or self.floating or self.perched_hwnd is not None or self.vy != 0:
            return False
        cx = self.x + self.w / 2
        candidates = []
        for win in self.manager.perch_windows:
            if win.top >= work_top + 40 and 45 < (self.y + self.h - win.top) <= 340:
                if win.left + 24 <= cx <= win.right - 24:
                    if not win_tracker.is_perch_spot_occluded(self.manager.perch_windows, win.hwnd, cx, win.top):
                        candidates.append(win)
        if not candidates:
            return False
        target = min(candidates, key=lambda w: (self.y + self.h) - w.top)
        dy = (self.y + self.h) - target.top + 32
        self.vy = -min(21.5, math.sqrt(2.0 * 0.75 * max(40.0, dy)))
        self.vx = random.uniform(-1.5, 1.5)
        self.state = "walk"
        self.manager.sound.play_event("jump")
        return True

    def _tick(self) -> None:
        if not self.alive:
            return
        work_area = win_tracker.get_work_area()
        left, top, right, bottom = work_area
        floor_y = float(bottom - self.h)

        if self.berry_notice_cooldown > 0:
            self.berry_notice_cooldown -= 1

        if not self.dragging:
            # 1. Perch maintenance & gravity
            active_perch_rect: win_tracker.WindowRect | None = None
            if not self.floating and self.perched_hwnd is not None:
                if self.manager.perch_enabled:
                    active_perch_rect = win_tracker.get_window_rect_if_alive(
                        self.perched_hwnd, self.manager.pid, work_area
                    )
                    if active_perch_rect and win_tracker.is_perch_spot_occluded(
                        self.manager.perch_windows,
                        self.perched_hwnd,
                        self.x + self.w / 2,
                        active_perch_rect.top + 2,
                    ):
                        active_perch_rect = None
                if active_perch_rect is None:
                    self.perched_hwnd = None
                    self.prev_perch_rect = None
                else:
                    if self.prev_perch_rect is not None:
                        self.x += (active_perch_rect.left - self.prev_perch_rect.left)
                    self.y = float(active_perch_rect.top - self.h)
                    self.vy = 0.0
                    self.prev_perch_rect = active_perch_rect

            if not self.floating and self.perched_hwnd is None:
                if self.y < floor_y or self.vy < 0:
                    prev_bottom = self.y + self.h
                    self.vy += 0.75
                    next_y = self.y + self.vy
                    next_bottom = next_y + self.h

                    landed_win = None
                    if self.vy > 0 and self.manager.perch_enabled:
                        landed_win = win_tracker.find_landing_window(
                            self.manager.perch_windows,
                            self.x + self.w / 2,
                            prev_bottom,
                            next_bottom,
                            top,
                        )
                    if landed_win is not None:
                        self.y = float(landed_win.top - self.h)
                        self.vy = 0.0
                        self.perched_hwnd = landed_win.hwnd
                        self.prev_perch_rect = landed_win
                        active_perch_rect = landed_win
                    else:
                        self.y = next_y
                        if self.y >= floor_y:
                            self.y = floor_y
                            if abs(self.vy) > 4.2:
                                self.vy = -self.vy * 0.25
                            else:
                                self.vy = 0.0
            elif self.floating:
                self.vy = 0.0

            # 2. AI: Berry chasing overrides passive behavior
            target_berry = self._find_closest_berry()
            if target_berry is not None:
                cx = self.x + self.w / 2
                bx = target_berry.x + target_berry.w / 2
                dx = bx - cx
                if self.berry_notice_cooldown <= 0 and abs(dx) > 45:
                    self.say("🍓 哇！樹果！", 1500)
                    self.berry_notice_cooldown = 120
                if abs(dx) > 14:
                    self.state = "walk"
                    self.facing = 1 if dx > 0 else -1
                    self.vx = 3.9 * self.facing
                else:
                    self.vx = 0.0
                    self.state = "idle"

                # If perched high above the berry, hop off toward it
                if self.perched_hwnd is not None and (target_berry.y - (self.y + self.h)) > 40:
                    self.perched_hwnd = None
                    self.prev_perch_rect = None
                    self.vy = -3.5

                # Eat berry when close enough
                if abs(dx) < 32:
                    dy_feet = abs((self.y + self.h) - (target_berry.y + target_berry.h))
                    if dy_feet < 48:
                        target_berry.consume()
                        self.manager.on_pet_ate_berry(self)
                    elif self.vy == 0 and (target_berry.y + target_berry.h) < (self.y + self.h - 20):
                        self.jump(-10.5)

            elif self.mode == "idle":
                self.state = "idle"
                self.vx = 0.0
            elif self.mode == "follow":
                mx = self.win.winfo_pointerx()
                cx = self.x + self.w / 2
                dx = mx - cx
                if abs(dx) > 48:
                    self.state = "walk"
                    self.facing = 1 if dx > 0 else -1
                    self.vx = 2.7 * self.facing
                else:
                    self.state = "idle"
                    self.vx = 0.0
            else:  # wander
                self.state_timer -= 1
                if self.state_timer <= 0:
                    if self.state == "idle":
                        if random.random() < 0.14 and self._try_jump_onto_window(top):
                            self.state_timer = random.randint(70, 140)
                        else:
                            self.state = "walk"
                            self.facing = random.choice([-1, 1])
                            self.vx = random.uniform(1.1, 2.2) * self.facing
                            self.state_timer = random.randint(60, 170)
                    else:
                        self.state = "idle"
                        self.vx = 0.0
                        self.state_timer = random.randint(55, 160)

            self.x += self.vx

            # Keep inside perched window edges (or occasionally step off)
            if self.perched_hwnd is not None and active_perch_rect is not None and target_berry is None:
                if self.x + self.w / 2 <= active_perch_rect.left + 12:
                    if random.random() < 0.2:
                        self.perched_hwnd = None
                        self.prev_perch_rect = None
                    else:
                        self.x = float(active_perch_rect.left + 12 - self.w / 2)
                        self.facing = 1
                        self.vx = abs(self.vx)
                elif self.x + self.w / 2 >= active_perch_rect.right - 12:
                    if random.random() < 0.2:
                        self.perched_hwnd = None
                        self.prev_perch_rect = None
                    else:
                        self.x = float(active_perch_rect.right - 12 - self.w / 2)
                        self.facing = -1
                        self.vx = -abs(self.vx)

            if self.x <= left + 4:
                self.x = float(left + 4)
                self.facing = 1
                self.vx = abs(self.vx)
            elif self.x >= right - self.w - 4:
                self.x = float(right - self.w - 4)
                self.facing = -1
                self.vx = -abs(self.vx)

            self.win.geometry(f"+{int(self.x)}+{int(self.y)}")
            self.bubble.move_to(int(self.x + self.w / 2), int(self.y))

            if self.chatter and target_berry is None:
                self.chatter_cooldown -= 1
                if self.chatter_cooldown <= 0:
                    self.say(self._pick_quote(), 3200)
                    self.chatter_cooldown = random.randint(500, 1200)

        self.win.after(33, self._tick)

    def destroy(self) -> None:
        self.alive = False
        self.bubble.destroy()
        try:
            self.win.destroy()
        except Exception:
            pass


class PokedexWindow:
    """Traditional Chinese Pokédex box supporting drag-out summoning, switching & PokéAPI lookup."""

    def __init__(self, manager: "PetManager", target_pet: DesktopPet | None) -> None:
        self.manager = manager
        self.target_pet = target_pet
        self.thumbs: list[ImageTk.PhotoImage] = []
        self.selected_pokemon: dict[str, Any] | None = None

        # Drag-to-summon state
        self._drag_pokemon: dict[str, Any] | None = None
        self._drag_start = (0, 0)
        self._drag_active = False
        self._drag_ghost: tk.Toplevel | None = None
        self._drag_photo: ImageTk.PhotoImage | None = None
        self._drag_hint: tk.Label | None = None

        self.win = tk.Toplevel(manager.root)
        self.win.title("Poke Finder 我的寶可夢圖鑑盒")
        self.win.geometry("840x620")
        self.win.configure(bg="#111827")
        self.win.attributes("-topmost", True)

        top_bar = tk.Frame(self.win, bg="#1f2937", padx=14, pady=10)
        top_bar.pack(fill="x")

        self.title_lbl = tk.Label(
            top_bar,
            text=f"🐾 我的寶可夢圖鑑盒（已收集 {len(manager.catalog)} 種 / 共捕獲 {manager.total_captures} 隻）",
            bg="#1f2937",
            fg="#f9fafb",
            font=("Microsoft JhengHei UI", 12, "bold"),
        )
        self.title_lbl.pack(side="left")

        tk.Button(
            top_bar,
            text="🔄 同步瀏覽器存檔",
            bg="#2563eb",
            fg="#ffffff",
            activebackground="#1d4ed8",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
            pady=4,
            font=("Microsoft JhengHei UI", 9, "bold"),
            command=self._on_sync,
        ).pack(side="right")

        tip_bar = tk.Frame(self.win, bg="#0f172a", padx=14, pady=4)
        tip_bar.pack(fill="x")
        tk.Label(
            tip_bar,
            text="💡 提示：長按左側寶可夢卡片並「直接拖出圖鑑視窗外」放開，即可在滑鼠落點召喚到桌面！",
            bg="#0f172a",
            fg="#93c5fd",
            font=("Microsoft JhengHei UI", 9),
        ).pack(side="left")

        ctrl = tk.Frame(self.win, bg="#111827", padx=14, pady=8)
        ctrl.pack(fill="x")

        tk.Label(ctrl, text="搜尋：", bg="#111827", fg="#d1d5db", font=("Microsoft JhengHei UI", 10)).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_grid())
        search_entry = tk.Entry(
            ctrl,
            textvariable=self.search_var,
            bg="#1f2937",
            fg="#f9fafb",
            insertbackground="#f9fafb",
            relief="flat",
            width=22,
            font=("Microsoft JhengHei UI", 10),
        )
        search_entry.pack(side="left", padx=(4, 12), ipady=4)

        self.filter_var = tk.StringVar(value="all")
        for fid, flabel in (
            ("all", "全部"),
            ("special", "特殊／暗影"),
            ("shiny", "閃光"),
            ("gen1", "第 1 世代"),
            ("gen2", "第 2 世代+"),
        ):
            tk.Radiobutton(
                ctrl,
                text=flabel,
                variable=self.filter_var,
                value=fid,
                command=self._refresh_grid,
                bg="#111827",
                fg="#e5e7eb",
                selectcolor="#374151",
                activebackground="#111827",
                activeforeground="#ffffff",
                font=("Microsoft JhengHei UI", 9),
            ).pack(side="left", padx=4)

        body = tk.Frame(self.win, bg="#111827", padx=14, pady=4)
        body.pack(fill="both", expand=True)

        left_wrap = tk.Frame(body, bg="#111827")
        left_wrap.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(left_wrap, bg="#0f172a", highlightthickness=0)
        sb = ttk.Scrollbar(left_wrap, orient="vertical", command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, bg="#0f172a")
        self.grid_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self.detail = tk.Frame(body, bg="#1e293b", width=260, padx=14, pady=12)
        self.detail.pack(side="right", fill="y", padx=(12, 0))
        self.detail.pack_propagate(False)

        self.preview_lbl = tk.Label(self.detail, bg="#1e293b")
        self.preview_lbl.pack(pady=(4, 6))
        self.detail_name = tk.Label(
            self.detail, text="請點選左側寶可夢", bg="#1e293b", fg="#f8fafc",
            font=("Microsoft JhengHei UI", 13, "bold"), wraplength=230
        )
        self.detail_name.pack()
        self.detail_info = tk.Label(
            self.detail, text="", bg="#1e293b", fg="#cbd5e1",
            font=("Microsoft JhengHei UI", 9), justify="left", wraplength=230
        )
        self.detail_info.pack(pady=6, anchor="w")

        self.btn_switch = tk.Button(
            self.detail, text="🔄 切換成這隻桌寵", bg="#10b981", fg="#ffffff",
            relief="flat", pady=5, font=("Microsoft JhengHei UI", 10, "bold"),
            state="disabled", command=self._do_switch
        )
        self.btn_switch.pack(fill="x", pady=3)

        self.btn_spawn = tk.Button(
            self.detail, text="➕ 再召喚這隻到桌面", bg="#6366f1", fg="#ffffff",
            relief="flat", pady=5, font=("Microsoft JhengHei UI", 10, "bold"),
            state="disabled", command=self._do_spawn
        )
        self.btn_spawn.pack(fill="x", pady=3)

        action_row = tk.Frame(self.detail, bg="#1e293b")
        action_row.pack(fill="x", pady=3)
        self.btn_cry = tk.Button(
            action_row, text="🔊 聽叫聲", bg="#0284c7", fg="#ffffff",
            relief="flat", pady=4, font=("Microsoft JhengHei UI", 9, "bold"),
            state="disabled", command=self._do_cry
        )
        self.btn_cry.pack(side="left", fill="x", expand=True, padx=(0, 3))

        self.btn_berry = tk.Button(
            action_row, text="🍓 丟樹果", bg="#e11d48", fg="#ffffff",
            relief="flat", pady=4, font=("Microsoft JhengHei UI", 9, "bold"),
            command=lambda: self.manager.throw_berry()
        )
        self.btn_berry.pack(side="right", fill="x", expand=True, padx=(3, 0))

        self.btn_pokeapi = tk.Button(
            self.detail, text="🌐 查 PokéAPI 百科（免 Key）", bg="#334155", fg="#e2e8f0",
            relief="flat", pady=5, font=("Microsoft JhengHei UI", 9),
            state="disabled", command=self._fetch_pokeapi
        )
        self.btn_pokeapi.pack(fill="x", pady=(6, 3))

        self.pokeapi_lbl = tk.Label(
            self.detail, text="", bg="#1e293b", fg="#93c5fd",
            font=("Microsoft JhengHei UI", 9), justify="left", wraplength=230
        )
        self.pokeapi_lbl.pack(pady=4, anchor="w")

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_grid()
        if manager.catalog:
            self._select_pokemon(manager.catalog[0])

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _cleanup_drag_ghost(self) -> None:
        if self._drag_ghost is not None:
            try:
                self._drag_ghost.destroy()
            except Exception:
                pass
            self._drag_ghost = None
        self._drag_photo = None
        self._drag_hint = None

    def _on_close(self) -> None:
        self._cleanup_drag_ghost()
        self._drag_pokemon = None
        self._drag_active = False
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        if self.manager.pokedex_win is self:
            self.manager.pokedex_win = None
        self.win.destroy()

    def refresh_from_catalog(self) -> None:
        try:
            self.title_lbl.config(
                text=f"🐾 我的寶可夢圖鑑盒（已收集 {len(self.manager.catalog)} 種 / 共捕獲 {self.manager.total_captures} 隻）"
            )
            self._refresh_grid()
            if self.selected_pokemon:
                updated = self.manager.by_key.get(self.selected_pokemon["key"])
                if updated:
                    self._select_pokemon(updated)
        except Exception:
            pass

    def _on_sync(self) -> None:
        self.manager.sync_now()
        self.refresh_from_catalog()

    def _is_outside_window(self, x_root: int, y_root: int) -> bool:
        wx = self.win.winfo_rootx()
        wy = self.win.winfo_rooty()
        ww = self.win.winfo_width()
        wh = self.win.winfo_height()
        return not (wx <= x_root <= wx + ww and wy <= y_root <= wy + wh)

    def _on_card_press(self, event: tk.Event, pk: dict[str, Any]) -> None:
        self._select_pokemon(pk)
        self._drag_pokemon = pk
        self._drag_start = (event.x_root, event.y_root)
        self._drag_active = False

    def _on_card_drag(self, event: tk.Event) -> None:
        if self._drag_pokemon is None:
            return
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        if not self._drag_active:
            if math.hypot(dx, dy) < 8:
                return
            self._drag_active = True
            self._create_drag_ghost(self._drag_pokemon)

        if self._drag_ghost is not None:
            gw = self._drag_ghost.winfo_reqwidth()
            gh = self._drag_ghost.winfo_reqheight()
            self._drag_ghost.geometry(f"+{event.x_root - gw // 2}+{event.y_root - gh // 2}")
            self._drag_ghost.lift()
            outside = self._is_outside_window(event.x_root, event.y_root)
            if self._drag_hint is not None:
                if outside:
                    self._drag_hint.config(text="✨ 放開即可召喚！", bg="#065f46", fg="#ecfdf5")
                else:
                    self._drag_hint.config(text="➡ 拖出視窗外召喚", bg="#1e293b", fg="#cbd5e1")

    def _on_card_release(self, event: tk.Event) -> None:
        pk = self._drag_pokemon
        was_dragging = self._drag_active
        self._drag_pokemon = None
        self._drag_active = False
        self._cleanup_drag_ghost()

        if was_dragging and pk is not None and self._is_outside_window(event.x_root, event.y_root):
            self.manager.spawn_pet_at(pk, event.x_root, event.y_root)
            self.btn_spawn.config(state="normal" if len(self.manager.pets) < MAX_PETS else "disabled")

    def _create_drag_ghost(self, pk: dict[str, Any]) -> None:
        self._cleanup_drag_ghost()
        ghost = tk.Toplevel(self.win)
        ghost.overrideredirect(True)
        ghost.attributes("-topmost", True)
        ghost.configure(bg=TRANSPARENT_KEY)
        ghost.attributes("-transparentcolor", TRANSPARENT_KEY)
        try:
            ghost.attributes("-alpha", 0.92)
        except Exception:
            pass

        scale = int(self.manager.settings.get("scale", 3))
        gif_path = sync_pokefinder.resolve_sprite_path(pk["idle_gif"])
        photo, _, _ = make_single_frame_photo(gif_path, scale=scale)
        self._drag_photo = photo

        tk.Label(ghost, image=photo, bg=TRANSPARENT_KEY, bd=0).pack()
        hint = tk.Label(
            ghost,
            text="➡ 拖出視窗外召喚",
            bg="#1e293b",
            fg="#cbd5e1",
            font=("Microsoft JhengHei UI", 8, "bold"),
            padx=6,
            pady=2,
        )
        hint.pack()
        ghost.update_idletasks()
        self._drag_ghost = ghost
        self._drag_hint = hint

    def _refresh_grid(self) -> None:
        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.thumbs.clear()

        q = self.search_var.get().strip().lower()
        flt = self.filter_var.get()

        items = []
        for p in self.manager.catalog:
            if flt == "special" and not (p.get("is_special") or p.get("is_legendary")):
                continue
            if flt == "shiny" and not p.get("is_shiny"):
                continue
            if flt == "gen1" and p.get("generation") != 1:
                continue
            if flt == "gen2" and (p.get("generation") or 1) < 2:
                continue
            if q and q not in p["name_zh"].lower() and q not in p["name_en"].lower() and q not in str(p["dex"]):
                continue
            items.append(p)

        cols = 4
        for idx, p in enumerate(items):
            r, c = divmod(idx, cols)
            card = tk.Frame(self.grid_frame, bg="#1e293b", bd=1, relief="flat", padx=6, pady=6, cursor="hand2")
            card.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")

            try:
                sprite_file = sync_pokefinder.resolve_sprite_path(p["idle_gif"])
                im = Image.open(sprite_file).convert("RGBA").resize((52, 52), Image.Resampling.NEAREST)
                photo = ImageTk.PhotoImage(im)
            except Exception:
                photo = ImageTk.PhotoImage(Image.new("RGBA", (52, 52), (0, 0, 0, 0)))
            self.thumbs.append(photo)

            img_lbl = tk.Label(card, image=photo, bg="#1e293b", cursor="hand2")
            img_lbl.pack()
            badge = "✨" if p.get("is_shiny") else ("⭐" if p.get("is_special") else "")
            name_lbl = tk.Label(
                card,
                text=f"{badge}{p['name_zh']}",
                bg="#1e293b",
                fg="#f8fafc",
                font=("Microsoft JhengHei UI", 9, "bold"),
                wraplength=105,
                cursor="hand2",
            )
            name_lbl.pack()
            cnt_lbl = tk.Label(
                card,
                text=f"#{p['dex']:03d} · x{p['count']}",
                bg="#1e293b",
                fg="#94a3b8",
                font=("Microsoft JhengHei UI", 8),
                cursor="hand2",
            )
            cnt_lbl.pack()

            for widget in (card, img_lbl, name_lbl, cnt_lbl):
                widget.bind("<ButtonPress-1>", lambda e, pk=p: self._on_card_press(e, pk))
                widget.bind("<B1-Motion>", self._on_card_drag)
                widget.bind("<ButtonRelease-1>", self._on_card_release)

    def _select_pokemon(self, p: dict[str, Any]) -> None:
        self.selected_pokemon = p
        try:
            sprite_file = sync_pokefinder.resolve_sprite_path(p["idle_gif"])
            im = Image.open(sprite_file).convert("RGBA").resize((96, 96), Image.Resampling.NEAREST)
            self._preview_img = ImageTk.PhotoImage(im)
            self.preview_lbl.config(image=self._preview_img)
        except Exception:
            pass

        types_str = " / ".join(TYPE_ZH.get(t, (t, ""))[0] for t in p.get("types", [])) or "未知"
        stats = p.get("stats") or {}
        stat_str = (
            f"HP {stats.get('hp', '?')} | 攻 {stats.get('attack', '?')} | 防 {stats.get('defense', '?')}\n"
            f"特攻 {stats.get('specialAttack', '?')} | 特防 {stats.get('specialDefense', '?')} | 速 {stats.get('speed', '?')}"
            if stats
            else ""
        )
        aff_score = self.manager.get_affection(p["key"])
        aff_lv, aff_hearts = get_affection_info(aff_score)
        self.detail_name.config(text=f"{p['name_zh']}\n({p['name_en']})")
        self.detail_info.config(
            text=f"圖鑑編號：#{p['dex']:03d}（第 {p['generation']} 世代）\n"
                 f"屬性：{types_str}\n"
                 f"捕獲次數：{p['count']} 次\n"
                 f"親密度：Lv.{aff_lv} {aff_hearts}（{aff_score} 分）\n"
                 f"{stat_str}"
        )
        self.pokeapi_lbl.config(text="")
        self.btn_switch.config(state="normal" if (self.target_pet and self.target_pet.alive) else "disabled")
        self.btn_spawn.config(state="normal" if len(self.manager.pets) < MAX_PETS else "disabled")
        self.btn_cry.config(state="normal")
        self.btn_pokeapi.config(state="normal" if p.get("dex", 0) > 0 else "disabled")

    def _do_switch(self) -> None:
        if self.target_pet and self.target_pet.alive and self.selected_pokemon:
            self.target_pet.set_pokemon(self.selected_pokemon)

    def _do_spawn(self) -> None:
        if self.selected_pokemon:
            self.manager.spawn_pet(self.selected_pokemon)
            if len(self.manager.pets) >= MAX_PETS:
                self.btn_spawn.config(state="disabled")

    def _do_cry(self) -> None:
        if self.selected_pokemon:
            self.manager.sound.play_cry(self.selected_pokemon)

    def _fetch_pokeapi(self) -> None:
        p = self.selected_pokemon
        if not p or not p.get("dex"):
            return
        dex = p["dex"]
        self.pokeapi_lbl.config(text="正在查詢 PokéAPI...")

        def worker() -> None:
            try:
                req = urllib.request.Request(
                    f"https://pokeapi.co/api/v2/pokemon/{dex}",
                    headers={"User-Agent": "PokeDesktopPet/1.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    info = json.loads(resp.read().decode("utf-8"))
                h_m = info.get("height", 0) / 10.0
                w_kg = info.get("weight", 0) / 10.0
                base_exp = info.get("base_experience", "?")
                moves_n = len(info.get("moves", []))
                txt = f"【PokéAPI 即時資料】\n身高：{h_m:.1f} m｜體重：{w_kg:.1f} kg\n基礎經驗：{base_exp}｜可學招式：{moves_n} 種"
            except Exception as exc:
                txt = f"PokéAPI 查詢失敗：{exc}"
            try:
                self.win.after(0, lambda: self.pokeapi_lbl.config(text=txt))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()


class SetupGuideDialog:
    """Friendly first-run onboarding guide when Poke Finder extension/captures aren't found yet."""

    def __init__(self, root: tk.Tk, err_msg: str) -> None:
        self.root = root
        self.ready = False
        self.win = tk.Toplevel(root)
        self.win.title("PokeDesktopPet 首次啟動引導")
        self.win.geometry("540x360")
        self.win.configure(bg="#111827")
        self.win.resizable(False, False)

        tk.Label(
            self.win,
            text="🐾 歡迎使用 Poke Finder 寶可夢桌寵！",
            bg="#111827",
            fg="#f8fafc",
            font=("Microsoft JhengHei UI", 14, "bold"),
        ).pack(pady=(20, 8))

        guide = (
            "本工具採用純淨攜帶設計，不會內建他人存檔或圖片素材，\n"
            "而是唯讀讀取您自己瀏覽器（Chrome / Edge / Brave）中「Poke Finder」擴充的捕獲紀錄。\n\n"
            f"偵測狀態：{err_msg}\n\n"
            "📋 三步驟快速開始：\n"
            "  1. 點下方按鈕前往 Chrome 線上應用程式商店安裝「Poke Finder」。\n"
            "  2. 瀏覽任意網頁並捕捉至少 1 隻野生寶可夢。\n"
            "  3. 回到這裡點擊「🔄 重新掃描瀏覽器存檔」即可馬上召喚！\n"
            "  （小提醒：若剛安裝或剛抓完，請先關閉或重新整理該瀏覽器分頁確保存檔寫入）"
        )
        self.info_lbl = tk.Label(
            self.win,
            text=guide,
            bg="#1e293b",
            fg="#e2e8f0",
            font=("Microsoft JhengHei UI", 9),
            justify="left",
            padx=14,
            pady=12,
            wraplength=490,
        )
        self.info_lbl.pack(fill="x", padx=20, pady=8)

        btn_row = tk.Frame(self.win, bg="#111827")
        btn_row.pack(pady=16)

        tk.Button(
            btn_row,
            text="🌐 前往安裝 Poke Finder",
            bg="#2563eb",
            fg="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            font=("Microsoft JhengHei UI", 10, "bold"),
            command=lambda: webbrowser.open(sync_pokefinder.CHROME_WEB_STORE_URL),
        ).pack(side="left", padx=6)

        tk.Button(
            btn_row,
            text="🔄 重新掃描瀏覽器存檔",
            bg="#10b981",
            fg="#ffffff",
            relief="flat",
            padx=12,
            pady=7,
            font=("Microsoft JhengHei UI", 10, "bold"),
            command=self._retry,
        ).pack(side="left", padx=6)

        tk.Button(
            btn_row,
            text="結束離開",
            bg="#374151",
            fg="#e5e7eb",
            relief="flat",
            padx=12,
            pady=7,
            font=("Microsoft JhengHei UI", 10),
            command=self._quit,
        ).pack(side="left", padx=6)

        self.win.protocol("WM_DELETE_WINDOW", self._quit)

    def _retry(self) -> None:
        try:
            res = sync_pokefinder.sync_all()
            if res.get("unique_count", 0) > 0:
                self.ready = True
                self.win.destroy()
            else:
                messagebox.showinfo(
                    "尚未找到寶可夢",
                    "已找到 Poke Finder 擴充，但目前還沒有捕獲紀錄。\n請先在瀏覽器捕捉 1 隻寶可夢後再按重新掃描！",
                    parent=self.win,
                )
        except Exception as exc:
            messagebox.showwarning("尚未偵測到存檔", str(exc), parent=self.win)

    def _quit(self) -> None:
        self.ready = False
        self.win.destroy()


class PetManager:
    """Manages synced catalog, settings, window tracking, berries, butler & remote queue."""

    def __init__(self) -> None:
        win_tracker.enable_dpi_awareness()
        self.pid = os.getpid()
        self.root = tk.Tk()
        self.root.withdraw()

        self.catalog: list[dict[str, Any]] = []
        self.by_key: dict[str, dict[str, Any]] = {}
        self.by_pid: dict[str, dict[str, Any]] = {}
        self.active_companions: list[str] = []
        self.total_captures = 0
        self.pets: list[DesktopPet] = []
        self.berries: list[BerryEntity] = []
        self.pokedex_win: PokedexWindow | None = None

        self.settings = self._load_settings()
        self.perch_enabled = bool(self.settings.get("perch_enabled", True))
        self.butler_enabled = bool(self.settings.get("butler_enabled", True))
        self.hydration_enabled = bool(self.settings.get("hydration_enabled", True))
        self.hydration_interval_min = int(self.settings.get("hydration_interval_min", 45))
        if self.hydration_interval_min not in (30, 45, 60):
            self.hydration_interval_min = 45
        self.auto_sync_enabled = bool(self.settings.get("auto_sync_enabled", True))

        self.sound = sound_fx.SoundEngine(DATA_DIR, sync_pokefinder.find_pokefinder_ext_dir)
        self.sound.enabled = bool(self.settings.get("sound_enabled", True))

        # Load or sync initial catalog gracefully without crashing
        if not self._ensure_initial_catalog():
            self.root.after(0, self.root.quit)
            return

        # Runtime trackers
        self.perch_windows: list[win_tracker.WindowRect] = []
        self._storage_dir: Path | None = None
        self._last_storage_sig: tuple[tuple[str, int, int], ...] = ()
        self._sync_in_flight = False
        self._pending_sync_result: dict[str, Any] | None = None

        self.sys_stats: dict[str, Any] = {"cpu": 0.0, "ram": 0.0, "gpu": None}
        self._sys_in_flight = False
        self._sys_stats_ready = False
        self._high_load_streak = 0
        self._last_load_alert_ts = 0.0
        self._last_sleep_alert_ts = 0.0
        self._last_hydration_ts = time.monotonic()
        self._nvidia_smi_path = shutil.which("nvidia-smi")
        if not self._nvidia_smi_path:
            sys32_nvsmi = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
            if sys32_nvsmi.is_file():
                self._nvidia_smi_path = str(sys32_nvsmi)

        try:
            import psutil

            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        # Spawn saved squad or Poke Finder active companion
        initial_keys: list[str] = self.settings.get("active_keys") or []
        spawned = 0
        for key in initial_keys[:MAX_PETS]:
            pk = self.by_key.get(key)
            if pk:
                self.spawn_pet(pk, play_sfx=(spawned == 0))
                spawned += 1

        if spawned == 0:
            for cid in self.active_companions:
                pk = self.by_pid.get(cid)
                if pk:
                    self.spawn_pet(pk, play_sfx=True)
                    spawned += 1
                    break
        if spawned == 0 and self.catalog:
            self.spawn_pet(self.catalog[0], play_sfx=True)

        # Prime storage signature for background auto-sync
        try:
            _, sdir = sync_pokefinder.find_pokefinder_paths()
            self._storage_dir = sdir
            self._last_storage_sig = sync_pokefinder.get_storage_signature(sdir)
        except Exception:
            pass

        self.write_status()
        self._refresh_windows_loop()
        self._poll_remote_commands_loop()
        self._auto_sync_loop()
        self._system_butler_loop()
        self._status_heartbeat_loop()

    def _load_settings(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "scale": 3,
            "mode": "wander",
            "floating": False,
            "topmost": True,
            "chatter": True,
            "perch_enabled": True,
            "sound_enabled": True,
            "butler_enabled": True,
            "hydration_enabled": True,
            "hydration_interval_min": 45,
            "auto_sync_enabled": True,
            "active_keys": [],
            "affection": {},
        }
        if SETTINGS_JSON.exists():
            try:
                loaded = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    defaults.update(loaded)
            except Exception:
                pass
        return defaults

    def save_settings(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.settings["active_keys"] = [p.pokemon["key"] for p in self.pets]
        self.settings["perch_enabled"] = self.perch_enabled
        self.settings["sound_enabled"] = self.sound.enabled
        self.settings["butler_enabled"] = self.butler_enabled
        self.settings["hydration_enabled"] = self.hydration_enabled
        self.settings["hydration_interval_min"] = self.hydration_interval_min
        self.settings["auto_sync_enabled"] = self.auto_sync_enabled
        tmp = SETTINGS_JSON.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_JSON)

    def _load_catalog_from_disk(self) -> None:
        data = json.loads(CAUGHT_JSON.read_text(encoding="utf-8"))
        self.catalog = data.get("pokemon", [])
        self.active_companions = data.get("active_companions", [])
        self.total_captures = int(data.get("total_captures", 0))
        self.by_key = {p["key"]: p for p in self.catalog}
        self.by_pid = {p["pokemon_id"]: p for p in self.catalog}

    def _ensure_initial_catalog(self) -> bool:
        if CAUGHT_JSON.exists():
            try:
                self._load_catalog_from_disk()
                if self.catalog:
                    return True
            except Exception:
                pass

        err_msg = ""
        try:
            res = sync_pokefinder.sync_all()
            if res.get("unique_count", 0) > 0:
                self._load_catalog_from_disk()
                return True
            err_msg = "已找到 Poke Finder 擴充，但目前還沒有捕獲任何寶可夢。"
        except Exception as exc:
            err_msg = str(exc)

        dlg = SetupGuideDialog(self.root, err_msg)
        self.root.wait_window(dlg.win)
        if dlg.ready and CAUGHT_JSON.exists():
            self._load_catalog_from_disk()
            return bool(self.catalog)
        return False

    def get_affection(self, pokemon_key: str) -> int:
        aff = self.settings.get("affection")
        if not isinstance(aff, dict):
            return 0
        return int(aff.get(pokemon_key, 0))

    def add_affection(self, pet: DesktopPet, delta: int = 1) -> tuple[int, int, str]:
        aff = self.settings.setdefault("affection", {})
        key = pet.pokemon["key"]
        new_score = int(aff.get(key, 0)) + delta
        aff[key] = new_score
        self.save_settings()
        self.write_status()
        lv, hearts = get_affection_info(new_score)
        return new_score, lv, hearts

    def on_pet_ate_berry(self, pet: DesktopPet) -> None:
        self.sound.play_event("eat")
        score, lv, hearts = self.add_affection(pet, 1)
        pet.jump(-6.5)
        for _ in range(3):
            HeartParticle(
                self,
                int(pet.x + pet.w / 2 + random.randint(-18, 18)),
                int(pet.y + random.randint(0, 14)),
            )
        pet.say(f"🍓 真好吃！親密度 +1 ({hearts} Lv.{lv})", 2800)
        if self.pokedex_win and self.pokedex_win.win.winfo_exists():
            self.pokedex_win.refresh_from_catalog()

    def throw_berry(self, x: int | None = None, y: int | None = None) -> None:
        left, top, right, bottom = win_tracker.get_work_area()
        if x is None:
            x = random.randint(left + 120, max(left + 160, right - 120))
        if y is None:
            y = random.randint(top + 80, max(top + 120, (top + bottom) // 2))
        self.berries.append(BerryEntity(self, x, y))
        self.sound.play_event("throw")

    def sync_now(self, notify_pet: DesktopPet | None = None, silent: bool = False) -> None:
        try:
            old_n = len(self.catalog)
            res = sync_pokefinder.sync_all(incremental=True)
            self._load_catalog_from_disk()
            diff = len(self.catalog) - old_n
            msg = f"同步完成！共 {res['unique_count']} 種寶可夢" + (f"（新增 {diff} 種！）" if diff > 0 else "（已是最新）")
            if self.pokedex_win and self.pokedex_win.win.winfo_exists():
                self.pokedex_win.refresh_from_catalog()
            self.write_status()
            if notify_pet and notify_pet.alive:
                notify_pet.say(msg, 3500)
            elif not silent:
                parent = self.pokedex_win.win if (self.pokedex_win and self.pokedex_win.win.winfo_exists()) else None
                messagebox.showinfo("Poke Finder 存檔同步", msg, parent=parent)
        except Exception as exc:
            if not silent:
                parent = self.pokedex_win.win if (self.pokedex_win and self.pokedex_win.win.winfo_exists()) else None
                messagebox.showerror("同步失敗", str(exc), parent=parent)

    def spawn_pet(
        self,
        pokemon: dict[str, Any],
        start_x: int | None = None,
        start_y: int | None = None,
        play_sfx: bool = True,
    ) -> DesktopPet | None:
        if len(self.pets) >= MAX_PETS:
            parent = self.pokedex_win.win if (self.pokedex_win and self.pokedex_win.win.winfo_exists()) else None
            messagebox.showinfo("小隊已滿", f"桌面上最多可同時放 {MAX_PETS} 隻寶可夢喔！", parent=parent)
            return None
        pet = DesktopPet(self, pokemon, start_x=start_x, start_y=start_y, play_spawn_sfx=play_sfx)
        self.pets.append(pet)
        self.save_settings()
        self.write_status()
        return pet

    def spawn_pet_at(self, pokemon: dict[str, Any], drop_x: int, drop_y: int) -> DesktopPet | None:
        scale = int(self.settings.get("scale", 3))
        est_size = 32 * scale
        return self.spawn_pet(pokemon, start_x=drop_x - est_size // 2, start_y=drop_y - est_size // 2, play_sfx=True)

    def spawn_random_pet(self) -> DesktopPet | None:
        if not self.catalog:
            return None
        active_keys = {p.pokemon["key"] for p in self.pets}
        pool = [p for p in self.catalog if p["key"] not in active_keys] or self.catalog
        return self.spawn_pet(random.choice(pool))

    def remove_pet(self, pet: DesktopPet) -> None:
        if pet in self.pets:
            self.pets.remove(pet)
            pet.destroy()
            self.sound.play_event("dismiss")
            self.save_settings()
            self.write_status()

    def set_all_scale(self, scale: int) -> None:
        self.settings["scale"] = scale
        for p in self.pets:
            p.set_scale(scale)
        self.save_settings()

    def toggle_perch(self) -> None:
        self.perch_enabled = not self.perch_enabled
        self.save_settings()
        if self.pets:
            self.pets[0].say("🪟 可以跳上視窗標題列囉！" if self.perch_enabled else "⬇️ 改回只在工作列散步！", 2200)
        self.write_status()

    def toggle_sound(self) -> None:
        self.sound.enabled = not self.sound.enabled
        self.save_settings()
        if self.sound.enabled:
            self.sound.play_event("pet")
        if self.pets:
            self.pets[0].say("🔊 音效已開啟！" if self.sound.enabled else "🔇 已切換為靜音模式", 2000)
        self.write_status()

    def toggle_butler(self) -> None:
        self.butler_enabled = not self.butler_enabled
        self.save_settings()
        if self.pets:
            self.pets[0].say("🤖 負載與深夜管家已開啟" if self.butler_enabled else "🤖 負載與深夜管家已暫停", 2000)

    def toggle_hydration(self) -> None:
        self.hydration_enabled = not self.hydration_enabled
        self._last_hydration_ts = time.monotonic()
        self.save_settings()
        if self.pets:
            self.pets[0].say(
                f"💧 喝水提醒已開啟（每 {self.hydration_interval_min} 分鐘）" if self.hydration_enabled else "💧 喝水提醒已暫停",
                2400,
            )

    def set_hydration_interval(self, mins: int) -> None:
        self.hydration_interval_min = mins
        self._last_hydration_ts = time.monotonic()
        self.save_settings()
        if self.pets:
            self.pets[0].say(f"⏱️ 喝水提醒改為每 {mins} 分鐘一次！", 2200)

    def reset_hydration_timer(self) -> None:
        self._last_hydration_ts = time.monotonic()
        if self.pets:
            self.pets[0].say(f"🔁 已重新計時！（{self.hydration_interval_min} 分鐘後提醒喝水）", 2200)

    def trigger_hydration_reminder(self) -> None:
        self._last_hydration_ts = time.monotonic()
        self.sound.play_event("reminder")
        if self.pets:
            lead = self.pets[0]
            lead.jump(-8.0)
            lead.say(f"💧 已經坐了 {self.hydration_interval_min} 分鐘囉！起來伸個懶腰、喝口水吧～", 8500)

    def toggle_auto_sync(self) -> None:
        self.auto_sync_enabled = not self.auto_sync_enabled
        self.save_settings()
        if self.pets:
            self.pets[0].say("🔍 背景自動偵測新抓寶可夢：開啟" if self.auto_sync_enabled else "🔍 背景自動偵測：關閉", 2200)

    def open_pokedex(self, target_pet: DesktopPet | None = None) -> None:
        if target_pet is None and self.pets:
            target_pet = self.pets[0]
        if self.pokedex_win and self.pokedex_win.win.winfo_exists():
            self.pokedex_win.target_pet = target_pet
            self.pokedex_win.win.deiconify()
            self.pokedex_win.win.lift()
            return
        self.pokedex_win = PokedexWindow(self, target_pet)

    # ---------------- Periodic Loops (Window Tracking, Auto-Sync, Butler, Remote Queue) ----------------

    def _refresh_windows_loop(self) -> None:
        if self.perch_enabled:
            try:
                self.perch_windows = win_tracker.get_perchable_windows(self.pid)
            except Exception:
                pass
        else:
            self.perch_windows = []
        self.root.after(200, self._refresh_windows_loop)

    def _auto_sync_loop(self) -> None:
        if self.auto_sync_enabled and not self._sync_in_flight:
            if self._storage_dir is None:
                try:
                    _, sdir = sync_pokefinder.find_pokefinder_paths()
                    self._storage_dir = sdir
                    self._last_storage_sig = sync_pokefinder.get_storage_signature(sdir)
                except Exception:
                    pass
            elif self._storage_dir.exists():
                sig = sync_pokefinder.get_storage_signature(self._storage_dir)
                if sig and sig != self._last_storage_sig:
                    self._last_storage_sig = sig
                    self._sync_in_flight = True
                    threading.Thread(target=self._run_bg_incremental_sync, daemon=True).start()
        self.root.after(8000, self._auto_sync_loop)

    def _run_bg_incremental_sync(self) -> None:
        try:
            res = sync_pokefinder.sync_all(incremental=True)
            self._pending_sync_result = res
        except Exception:
            pass
        finally:
            self._sync_in_flight = False

    def _on_bg_sync_done(self, res: dict[str, Any]) -> None:
        try:
            self._load_catalog_from_disk()
            if self.pokedex_win and self.pokedex_win.win.winfo_exists():
                self.pokedex_win.refresh_from_catalog()
            new_catches = res.get("new_catches") or []
            if new_catches:
                c = new_catches[0]
                self.sound.play_event("catch")
                if self.pets:
                    lead = self.pets[0]
                    lead.jump(-9.5)
                    if c.get("is_shiny"):
                        lead.say(f"✨ 哇！！抓到閃光【{c['name_zh']}】啦！（總捕獲 {self.total_captures} 隻）", 5500)
                    elif c.get("is_new_species"):
                        lead.say(f"🎉 新圖鑑登入！【{c['name_zh']}】加入夥伴！（總 {len(self.catalog)} 種）", 5500)
                    else:
                        lead.say(f"🎊 恭喜又抓到【{c['name_zh']}】！（第 {self.total_captures} 次捕獲）", 4500)
            self.write_status()
        except Exception:
            pass

    def _system_butler_loop(self) -> None:
        if self._sys_stats_ready:
            self._sys_stats_ready = False
            self._evaluate_butler_alerts()

        # Check hydration timer directly on main thread
        if self.hydration_enabled:
            elapsed = time.monotonic() - self._last_hydration_ts
            if elapsed >= self.hydration_interval_min * 60:
                self.trigger_hydration_reminder()

        if not self._sys_in_flight:
            self._sys_in_flight = True
            threading.Thread(target=self._sample_system_stats_worker, daemon=True).start()

        self.root.after(10000, self._system_butler_loop)

    def _sample_system_stats_worker(self) -> None:
        cpu = 0.0
        ram = 0.0
        gpu: float | None = None
        try:
            import psutil

            cpu = float(psutil.cpu_percent(interval=None))
            ram = float(psutil.virtual_memory().percent)
        except Exception:
            pass

        if self._nvidia_smi_path:
            try:
                out = subprocess.check_output(
                    [
                        self._nvidia_smi_path,
                        "--query-gpu=utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    creationflags=CREATE_NO_WINDOW,
                    timeout=2,
                    text=True,
                ).strip()
                if out:
                    gpu = float(out.splitlines()[0].strip())
            except Exception:
                gpu = None

        self.sys_stats = {"cpu": round(cpu, 1), "ram": round(ram, 1), "gpu": gpu}
        self._sys_stats_ready = True
        self._sys_in_flight = False

    def _evaluate_butler_alerts(self) -> None:
        if not self.butler_enabled or not self.pets:
            return
        now = time.time()
        cpu = float(self.sys_stats.get("cpu") or 0.0)
        gpu = self.sys_stats.get("gpu")

        if cpu >= 85.0 or (gpu is not None and gpu >= 90.0):
            self._high_load_streak += 1
        else:
            self._high_load_streak = 0

        lead = self.pets[0]
        if self._high_load_streak >= 3 and (now - self._last_load_alert_ts) > 600:
            self._last_load_alert_ts = now
            gpu_part = f" / GPU {gpu:.0f}%" if gpu is not None else ""
            lead.say(f"💦 電腦負載好高（CPU {cpu:.0f}%{gpu_part}），記得隨時存檔喔！", 5500)
            return

        lt = time.localtime(now)
        if 0 <= lt.tm_hour < 5 and (now - self._last_sleep_alert_ts) > 2700:
            self._last_sleep_alert_ts = now
            lead.say(f"🥱 已經凌晨 {lt.tm_hour:02d}:{lt.tm_min:02d} 啦…{lead.pokemon['name_zh']} 想睡覺了，早點休息吧 💤", 6000)

    def _poll_remote_commands_loop(self) -> None:
        if self._pending_sync_result is not None:
            res = self._pending_sync_result
            self._pending_sync_result = None
            self._on_bg_sync_done(res)
        if self._sys_stats_ready:
            self._sys_stats_ready = False
            self._evaluate_butler_alerts()

        if REMOTE_CMD_JSON.exists():
            processing = DATA_DIR / f".remote_cmd.processing.{os.getpid()}"
            try:
                os.replace(REMOTE_CMD_JSON, processing)
                raw = processing.read_text(encoding="utf-8")
                processing.unlink(missing_ok=True)
                payload = json.loads(raw)
                cmds = payload if isinstance(payload, list) else [payload]
                for cmd in cmds:
                    if isinstance(cmd, dict):
                        self._execute_remote_command(cmd)
            except OSError:
                pass
            except Exception:
                try:
                    processing.unlink(missing_ok=True)
                except Exception:
                    pass
        self.root.after(500, self._poll_remote_commands_loop)

    def _execute_remote_command(self, cmd: dict[str, Any]) -> None:
        action = str(cmd.get("action", "")).lower().strip()
        if not action:
            return

        if action == "open_pokedex":
            self.open_pokedex()
            return

        if action == "say":
            text = str(cmd.get("text", "")).strip()
            if not text or not self.pets:
                return
            duration = int(cmd.get("duration") or 5500)
            pet_filter = str(cmd.get("pet", "")).strip().lower()
            targets = self.pets
            if pet_filter and pet_filter != "all":
                matched = [
                    p for p in self.pets
                    if pet_filter in p.pokemon["name_zh"].lower()
                    or pet_filter in p.pokemon["name_en"].lower()
                    or pet_filter in p.pokemon["key"].lower()
                ]
                targets = matched or [self.pets[0]]
            elif not pet_filter:
                targets = [self.pets[0]]
            for p in targets:
                p.jump(-7.5)
                p.say(text, duration)
            self.sound.play_event("pet")
            return

        if action == "switch":
            key = str(cmd.get("key", "")).strip()
            pk = self.by_key.get(key)
            if not pk and cmd.get("target"):
                pk = self._find_pokemon_fuzzy(str(cmd["target"]))
            if pk and self.pets:
                idx = int(cmd.get("index") or 0)
                idx = max(0, min(idx, len(self.pets) - 1))
                self.pets[idx].set_pokemon(pk)
            return

        if action == "spawn":
            target = str(cmd.get("target", "")).strip()
            key = str(cmd.get("key", "")).strip()
            if key and key in self.by_key:
                self.spawn_pet(self.by_key[key])
            elif target.lower() in ("", "random", "隨機"):
                self.spawn_random_pet()
            else:
                pk = self._find_pokemon_fuzzy(target)
                if pk:
                    self.spawn_pet(pk)
            return

        if action == "berry":
            cnt = max(1, min(5, int(cmd.get("count") or 1)))
            for i in range(cnt):
                self.root.after(i * 180, self.throw_berry)
            return

        if action == "sync":
            lead = self.pets[0] if self.pets else None
            self.sync_now(notify_pet=lead, silent=True)
            return

        if action == "water":
            self.trigger_hydration_reminder()
            return

        if action == "mode":
            mode = str(cmd.get("mode", "")).strip()
            if mode in ("wander", "follow", "idle"):
                for p in self.pets:
                    p._set_mode(mode)
                self.write_status()
            return

        if action == "sound":
            state = str(cmd.get("state", "")).strip().lower()
            if state == "cry":
                if self.pets:
                    self.sound.play_cry(self.pets[0].pokemon)
            elif state == "on":
                if not self.sound.enabled:
                    self.toggle_sound()
            elif state == "off":
                if self.sound.enabled:
                    self.toggle_sound()
            elif state == "toggle":
                self.toggle_sound()

    def _find_pokemon_fuzzy(self, query: str) -> dict[str, Any] | None:
        q = query.strip().lower().lstrip("#")
        if not q:
            return None
        for p in self.catalog:
            if q in (
                p["key"].lower(),
                p["pokemon_id"].lower(),
                p["name_zh"].lower(),
                p["name_en"].lower(),
                str(p["dex"]),
                str(p["dex"]).zfill(3),
            ):
                return p
        for p in self.catalog:
            if q in p["name_zh"].lower() or q in p["name_en"].lower() or q in p["key"].lower():
                return p
        return None

    def _status_heartbeat_loop(self) -> None:
        self.write_status()
        self.root.after(5000, self._status_heartbeat_loop)

    def write_status(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            pets_info = []
            for p in self.pets:
                aff = self.get_affection(p.pokemon["key"])
                lv, _ = get_affection_info(aff)
                pets_info.append(
                    {
                        "key": p.pokemon["key"],
                        "dex": p.pokemon["dex"],
                        "name_zh": p.pokemon["name_zh"],
                        "name_en": p.pokemon["name_en"],
                        "affection": aff,
                        "affection_lv": lv,
                        "perched": p.perched_hwnd is not None,
                    }
                )
            payload = {
                "updated_at": time.time(),
                "pid": self.pid,
                "unique_count": len(self.catalog),
                "total_captures": self.total_captures,
                "sound_enabled": self.sound.enabled,
                "perch_enabled": self.perch_enabled,
                "mode": self.settings.get("mode", "wander"),
                "system": self.sys_stats,
                "pets": pets_info,
            }
            tmp = PET_STATUS_JSON.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, PET_STATUS_JSON)
        except Exception:
            pass

    def quit_all(self) -> None:
        self.save_settings()
        for b in list(self.berries):
            b.consume()
        for p in list(self.pets):
            p.destroy()
        self.root.quit()

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    if "--allow-multi" not in sys.argv and not _acquire_single_instance_mutex():
        _enqueue_local_action({"action": "open_pokedex", "source": "second_launch"})
        raise SystemExit(0)
    PetManager().run()
