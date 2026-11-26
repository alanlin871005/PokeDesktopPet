"""
原版音效與 8-bit 叫聲彩蛋播放模組
- 唯讀讀取使用者本機瀏覽器 Poke Finder 擴充中的 .wav 原版音效（絕不內建或打包素材）
- 支援依圖鑑編號與屬性於執行期合成柔和 8-bit 復古叫聲彩蛋至暫存快取
- 以 Windows 內建 winsound 非同步播放（絕不卡住桌面動畫，支援一鍵靜音）
"""

from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path
from typing import Any, Callable

try:
    import winsound
except ImportError:
    winsound = None  # type: ignore[assignment]


class SoundEngine:
    """Non-blocking Windows sound effects + chiptune cry easter egg player."""

    EVENT_WAV_MAP: dict[str, tuple[str, ...]] = {
        "spawn": ("content.wav", "content3.wav"),
        "throw": ("content.wav",),
        "eat": ("content3.wav", "content5.wav"),
        "catch": ("content3.wav", "content.wav"),
        "pet": ("content5.wav", "content2.wav", "content4.wav"),
        "jump": ("content6.wav", "content4.wav"),
        "dismiss": ("content6.wav",),
        "reminder": ("content2.wav", "content5.wav"),
    }

    def __init__(self, data_dir: Path, get_ext_dir_fn: Callable[[], Path | None]) -> None:
        self.data_dir = data_dir
        self._get_ext_dir = get_ext_dir_fn
        self._assets_dir: Path | None = None
        self._assets_checked = False
        self.enabled = True
        self._pet_cycle = 0

    def refresh_assets_dir(self) -> Path | None:
        ext_dir = self._get_ext_dir()
        if ext_dir is not None:
            cand = ext_dir / "assets"
            if cand.is_dir():
                self._assets_dir = cand
        self._assets_checked = True
        return self._assets_dir

    def _resolve_event_wav(self, event: str) -> Path | None:
        if not self._assets_checked:
            self.refresh_assets_dir()
        if self._assets_dir is None or not self._assets_dir.exists():
            return None
        names = self.EVENT_WAV_MAP.get(event, ("content5.wav",))
        if event == "pet":
            idx = self._pet_cycle % len(names)
            self._pet_cycle += 1
            ordered = names[idx:] + names[:idx]
        else:
            ordered = names
        for name in ordered:
            p = self._assets_dir / name
            if p.is_file():
                return p
        return None

    def _play_file_async(self, wav_path: Path) -> None:
        if not self.enabled or winsound is None or not wav_path.is_file():
            return
        try:
            flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            winsound.PlaySound(str(wav_path), flags)
        except Exception:
            pass

    def play_event(self, event: str) -> None:
        if not self.enabled:
            return
        wav = self._resolve_event_wav(event)
        if wav is not None:
            self._play_file_async(wav)
            return
        # Soft synthesized fallback if extension wav assets are unavailable
        fb = self._ensure_fallback_sfx(event)
        if fb is not None:
            self._play_file_async(fb)

    def play_cry(self, pokemon: dict[str, Any]) -> None:
        if not self.enabled:
            return
        cry_path = self._ensure_cry_wav(pokemon)
        if cry_path is not None:
            self._play_file_async(cry_path)

    def _ensure_fallback_sfx(self, event: str) -> Path | None:
        sfx_dir = self.data_dir / "cache" / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)
        out = sfx_dir / f"sfx_{event}.wav"
        if out.exists():
            return out
        patterns: dict[str, list[tuple[float, float, float]]] = {
            "spawn": [(523.25, 0.07, 0.20), (659.25, 0.08, 0.20), (783.99, 0.12, 0.18)],
            "throw": [(440.0, 0.06, 0.16), (620.0, 0.08, 0.16)],
            "eat": [(587.33, 0.06, 0.18), (783.99, 0.07, 0.20), (1046.5, 0.14, 0.18)],
            "catch": [(523.25, 0.08, 0.20), (659.25, 0.08, 0.20), (783.99, 0.08, 0.20), (1046.5, 0.22, 0.22)],
            "pet": [(659.25, 0.06, 0.16), (880.0, 0.09, 0.15)],
            "jump": [(392.0, 0.05, 0.14), (523.25, 0.07, 0.14)],
            "dismiss": [(523.25, 0.07, 0.15), (349.23, 0.10, 0.13)],
            "reminder": [(659.25, 0.09, 0.18), (523.25, 0.09, 0.16), (783.99, 0.16, 0.18)],
        }
        notes = patterns.get(event, [(660.0, 0.08, 0.16)])
        _write_notes_wav(out, notes, wave_kind="triangle")
        return out

    def _ensure_cry_wav(self, pokemon: dict[str, Any]) -> Path | None:
        cries_dir = self.data_dir / "cache" / "cries"
        cries_dir.mkdir(parents=True, exist_ok=True)
        key = str(pokemon.get("key") or pokemon.get("pokemon_id") or "default")
        safe = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in key)
        out = cries_dir / f"{safe}.wav"
        if out.exists():
            return out

        pid = str(pokemon.get("pokemon_id", "")).lower()
        dex = int(pokemon.get("dex") or 25)
        types = pokemon.get("types") or []

        if "pikachu" in pid:
            # Iconic cheerful "Pi-ka-CHU!" chiptune contour
            notes = [
                (880.0, 0.08, 0.20),
                (0.0, 0.03, 0.0),
                (987.77, 0.08, 0.20),
                (0.0, 0.03, 0.0),
                (1174.66, 0.10, 0.22),
                (1318.51, 0.14, 0.20),
            ]
            _write_notes_wav(out, notes, wave_kind="pulse")
            return out

        if "mewtwo" in pid or pokemon.get("is_legendary"):
            # Deep mysterious psychic/legendary sweep
            _write_sweep_wav(out, start_hz=260.0 + (dex % 40), end_hz=640.0, dur=0.42, vibrato=18.0)
            return out

        seed = int.from_bytes(hashlib.sha256(f"{dex}:{pid}".encode("utf-8")).digest()[:4], "little")
        base_hz = 340.0 + (seed % 320)
        if "water" in types:
            notes = [(base_hz, 0.07, 0.18), (base_hz * 1.25, 0.08, 0.18), (base_hz * 1.5, 0.12, 0.16)]
            _write_notes_wav(out, notes, wave_kind="sine")
        elif "electric" in types:
            notes = [(base_hz * 1.4, 0.06, 0.18), (base_hz * 1.8, 0.06, 0.18), (base_hz * 2.1, 0.11, 0.16)]
            _write_notes_wav(out, notes, wave_kind="pulse")
        elif "ghost" in types or "dark" in types:
            _write_sweep_wav(out, start_hz=base_hz * 1.3, end_hz=base_hz * 0.72, dur=0.36, vibrato=14.0)
        elif "dragon" in types:
            _write_sweep_wav(out, start_hz=190.0 + (dex % 60), end_hz=420.0, dur=0.38, vibrato=10.0)
        else:
            step1 = 1.0 + ((seed >> 4) % 5) * 0.1
            step2 = 1.0 + ((seed >> 8) % 6) * 0.12
            notes = [
                (base_hz, 0.08, 0.17),
                (base_hz * step1, 0.09, 0.18),
                (base_hz * step2, 0.13, 0.16),
            ]
            _write_notes_wav(out, notes, wave_kind="triangle")
        return out


def _sample_wave(phase: float, kind: str) -> float:
    frac = phase % 1.0
    if kind == "sine":
        return math.sin(2.0 * math.pi * frac)
    if kind == "triangle":
        return 1.0 - 4.0 * abs(round(frac - 0.25) - (frac - 0.25))
    # Soft 25% pulse wave for Game Boy feel without harsh clipping
    return 0.75 if frac < 0.28 else -0.75


def _write_notes_wav(path: Path, notes: list[tuple[float, float, float]], wave_kind: str = "triangle") -> None:
    sr = 22050
    pcm = bytearray()
    for freq, dur, amp in notes:
        total = max(1, int(sr * dur))
        fade = max(1, int(sr * 0.012))
        for i in range(total):
            if freq <= 0:
                val = 0.0
            else:
                env = 1.0
                if i < fade:
                    env = i / fade
                elif i > total - fade:
                    env = (total - i) / fade
                val = _sample_wave(freq * (i / sr), wave_kind) * amp * env
            sample = max(-32767, min(32767, int(val * 32767)))
            pcm.extend(struct.pack("<h", sample))

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(pcm))


def _write_sweep_wav(path: Path, start_hz: float, end_hz: float, dur: float, vibrato: float = 12.0) -> None:
    sr = 22050
    total = max(1, int(sr * dur))
    fade = max(1, int(sr * 0.02))
    phase = 0.0
    pcm = bytearray()
    for i in range(total):
        t = i / sr
        prog = i / total
        freq = start_hz + (end_hz - start_hz) * prog + math.sin(2.0 * math.pi * vibrato * t) * 18.0
        phase += max(40.0, freq) / sr
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > total - fade:
            env = (total - i) / fade
        val = _sample_wave(phase, "triangle") * 0.22 * env
        sample = max(-32767, min(32767, int(val * 32767)))
        pcm.extend(struct.pack("<h", sample))

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(pcm))
