"""
Poke Finder 瀏覽器擴充存檔同步器（唯讀）
- 自動掃描 Chrome / Edge / Brave 的 Poke Finder 擴充（cihconljhkbpanliediapecopanoccem）
- 唯讀複製並解碼 LevelDB（支援 Snappy 壓縮與 WAL log），絕不修改瀏覽器存檔
- 靜態解析擴充內建圖鑑與 GIF 動態精靈圖，僅匯出使用者本人已抓到的寶可夢
- 支援 PyInstaller `sys.frozen` 攜帶模式與背景增量同步
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any

EXT_ID = "cihconljhkbpanliediapecopanoccem"
CHROME_WEB_STORE_URL = f"https://chromewebstore.google.com/detail/{EXT_ID}"


class PokeFinderNotFoundError(FileNotFoundError):
    """Raised when Poke Finder extension or its local save data cannot be found."""


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_data_dir() -> Path:
    preferred = get_app_root() / "data"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return preferred
    except OSError:
        fallback = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PokeDesktopPet" / "data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


APP_ROOT = get_app_root()
DATA_DIR = get_data_dir()
SPRITES_DIR = DATA_DIR / "sprites"
CAUGHT_JSON = DATA_DIR / "caught_pokemon.json"

SPECIAL_PIKACHU_ZH: dict[str, tuple[str, str]] = {
    "alola": ("阿羅拉帽皮卡丘", "Alola Cap Pikachu"),
    "belle": ("貴婦皮卡丘", "Pikachu Belle"),
    "cosplay": ("換裝皮卡丘", "Cosplay Pikachu"),
    "hoenn": ("豐緣帽皮卡丘", "Hoenn Cap Pikachu"),
    "kalos": ("卡洛斯帽皮卡丘", "Kalos Cap Pikachu"),
    "libre": ("摔角手皮卡丘", "Pikachu Libre"),
    "original": ("初始帽皮卡丘", "Original Cap Pikachu"),
    "partner": ("搭檔帽皮卡丘", "Partner Cap Pikachu"),
    "phd": ("博士皮卡丘", "Pikachu Ph.D."),
    "pop_star": ("偶像皮卡丘", "Pikachu Pop Star"),
    "rock_star": ("搖滾皮卡丘", "Pikachu Rock Star"),
    "sinnoh": ("神奧帽皮卡丘", "Sinnoh Cap Pikachu"),
    "unova": ("合眾帽皮卡丘", "Unova Cap Pikachu"),
}


# ---------------- Pure-Python LevelDB + Snappy Reader ----------------


def _snappy_decompress(data: bytes) -> bytes:
    i = 0
    n = len(data)
    while i < n:
        b = data[i]
        i += 1
        if not (b & 0x80):
            break
    out = bytearray()
    while i < n:
        tag = data[i]
        i += 1
        ttype = tag & 0x03
        if ttype == 0:
            l = tag >> 2
            if l < 60:
                length = l + 1
            else:
                nb = l - 59
                if i + nb > n:
                    raise ValueError("Truncated snappy literal length")
                length = int.from_bytes(data[i : i + nb], "little") + 1
                i += nb
            out.extend(data[i : i + length])
            i += length
        else:
            if ttype == 1:
                if i >= n:
                    raise ValueError("Truncated snappy copy1")
                length = ((tag >> 2) & 0x07) + 4
                offset = ((tag & 0xE0) << 3) | data[i]
                i += 1
            elif ttype == 2:
                if i + 2 > n:
                    raise ValueError("Truncated snappy copy2")
                length = (tag >> 2) + 1
                offset = int.from_bytes(data[i : i + 2], "little")
                i += 2
            else:
                if i + 4 > n:
                    raise ValueError("Truncated snappy copy4")
                length = (tag >> 2) + 1
                offset = int.from_bytes(data[i : i + 4], "little")
                i += 4
            if offset <= 0 or offset > len(out):
                raise ValueError("Invalid snappy offset")
            for _ in range(length):
                out.append(out[-offset])
    return bytes(out)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    val = 0
    shift = 0
    n = len(buf)
    while pos < n:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
    raise EOFError("Truncated varint")


def _parse_ldb_block(block: bytes) -> list[tuple[bytes, int, int, bytes]]:
    if len(block) < 4:
        return []
    num_restarts = struct.unpack("<I", block[-4:])[0]
    limit = len(block) - 4 - num_restarts * 4
    pos = 0
    prev_key = b""
    entries: list[tuple[bytes, int, int, bytes]] = []
    while pos < limit:
        try:
            shared, pos = _read_varint(block, pos)
            non_shared, pos = _read_varint(block, pos)
            vlen, pos = _read_varint(block, pos)
            key = prev_key[:shared] + block[pos : pos + non_shared]
            pos += non_shared
            val = block[pos : pos + vlen]
            pos += vlen
            prev_key = key
            if len(key) >= 8:
                seq_type = struct.unpack("<Q", key[-8:])[0]
                entries.append((key[:-8], seq_type >> 8, seq_type & 0xFF, val))
        except Exception:
            break
    return entries


def _parse_ldb_file(path: Path) -> list[tuple[bytes, int, int, bytes]]:
    data = path.read_bytes()
    if len(data) < 48 or data[-8:] != b"\x57\xfb\x80\x8b\x24\x75\x47\xdb":
        return []
    pos = len(data) - 48
    _, pos = _read_varint(data, pos)
    _, pos = _read_varint(data, pos)
    idx_off, pos = _read_varint(data, pos)
    idx_size, pos = _read_varint(data, pos)

    def read_block(off: int, size: int) -> bytes:
        raw = data[off : off + size]
        ctype = data[off + size]
        return _snappy_decompress(raw) if ctype == 1 else raw

    out: list[tuple[bytes, int, int, bytes]] = []
    for _, _, _, handle in _parse_ldb_block(read_block(idx_off, idx_size)):
        hp = 0
        boff, hp = _read_varint(handle, hp)
        bsize, hp = _read_varint(handle, hp)
        out.extend(_parse_ldb_block(read_block(boff, bsize)))
    return out


def _parse_log_file(path: Path) -> list[tuple[bytes, int, int, bytes]]:
    data = path.read_bytes()
    pos = 0
    records: list[bytes] = []
    cur = bytearray()
    while pos + 7 <= len(data):
        rem = 32768 - (pos % 32768)
        if rem < 7:
            pos += rem
            continue
        _, length, rtype = struct.unpack("<IHB", data[pos : pos + 7])
        pos += 7
        if rtype == 0 or pos + length > len(data):
            break
        chunk = data[pos : pos + length]
        pos += length
        if rtype == 1:
            records.append(chunk)
        elif rtype == 2:
            cur = bytearray(chunk)
        elif rtype == 3:
            cur.extend(chunk)
        elif rtype == 4:
            cur.extend(chunk)
            records.append(bytes(cur))
            cur = bytearray()
    out: list[tuple[bytes, int, int, bytes]] = []
    for rec in records:
        if len(rec) < 12:
            continue
        seq, count = struct.unpack("<QI", rec[:12])
        q = 12
        for idx in range(count):
            if q >= len(rec):
                break
            vtype = rec[q]
            q += 1
            try:
                klen, q = _read_varint(rec, q)
                if q + klen > len(rec):
                    break
                key = rec[q : q + klen]
                q += klen
                if vtype == 1:
                    vlen, q = _read_varint(rec, q)
                    if q + vlen > len(rec):
                        break
                    val = rec[q : q + vlen]
                    q += vlen
                else:
                    val = b""
                out.append((key, seq + idx, vtype, val))
            except Exception:
                break
    return out


def read_chrome_extension_storage(storage_dir: Path) -> dict[str, Any]:
    """Safely copy non-LOCK files to temp dir and decode latest LevelDB values."""
    with tempfile.TemporaryDirectory(prefix="pokefinder_sync_") as td:
        tmp = Path(td)
        for f in storage_dir.iterdir():
            if f.is_file() and f.name != "LOCK" and f.suffix in (".ldb", ".log"):
                try:
                    shutil.copy2(f, tmp / f.name)
                except OSError:
                    pass
        latest: dict[bytes, tuple[int, int, bytes]] = {}
        for f in sorted(tmp.iterdir()):
            try:
                recs = _parse_ldb_file(f) if f.suffix == ".ldb" else _parse_log_file(f)
            except Exception:
                continue
            for k, seq, vtype, val in recs:
                if k not in latest or seq > latest[k][0]:
                    latest[k] = (seq, vtype, val)

    decoded: dict[str, Any] = {}
    for k, (_, vtype, val) in latest.items():
        if vtype != 1:
            continue
        ks = k.decode("utf-8", errors="replace")
        try:
            decoded[ks] = json.loads(val.decode("utf-8"))
        except Exception:
            pass
    return decoded


# ---------------- Poke Finder Extension Discovery & Parser ----------------


def _browser_user_data_roots() -> list[Path]:
    local_app = Path(os.environ.get("LOCALAPPDATA", ""))
    return [
        local_app / "Google" / "Chrome" / "User Data",
        local_app / "Microsoft" / "Edge" / "User Data",
        local_app / "BraveSoftware" / "Brave-Browser" / "User Data",
    ]


def _iter_profile_dirs(root: Path) -> list[Path]:
    profiles: list[Path] = []
    for name in ("Default", "Guest Profile"):
        cand = root / name
        if cand.is_dir():
            profiles.append(cand)
    profiles.extend(sorted([p for p in root.glob("Profile *") if p.is_dir()]))
    return profiles


def find_pokefinder_ext_dir() -> Path | None:
    """Locate any installed Poke Finder extension directory (even before first capture)."""
    for root in _browser_user_data_roots():
        if not root.exists():
            continue
        for profile in _iter_profile_dirs(root):
            ext_base = profile / "Extensions" / EXT_ID
            if not ext_base.exists():
                continue
            versions = sorted(
                [d for d in ext_base.iterdir() if d.is_dir() and (d / "background.js").exists()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if versions:
                return versions[0]
    return None


def find_pokefinder_paths() -> tuple[Path, Path]:
    """Locate the best Chrome/Edge/Brave Poke Finder extension dir and its LevelDB storage dir."""
    candidates: list[tuple[int, float, Path, Path]] = []
    for root in _browser_user_data_roots():
        if not root.exists():
            continue
        for profile in _iter_profile_dirs(root):
            ext_base = profile / "Extensions" / EXT_ID
            storage = profile / "Local Extension Settings" / EXT_ID
            if not (ext_base.exists() and storage.exists()):
                continue
            versions = sorted(
                [d for d in ext_base.iterdir() if d.is_dir() and (d / "background.js").exists()],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not versions:
                continue
            db_files = [f for f in storage.iterdir() if f.is_file() and f.suffix in (".ldb", ".log")]
            if not db_files:
                continue
            total_size = sum(f.stat().st_size for f in db_files)
            newest_mtime = max(f.stat().st_mtime for f in db_files)
            candidates.append((total_size, newest_mtime, versions[0], storage))

    if candidates:
        candidates.sort(key=lambda item: (item[0] > 0, item[1], item[0]), reverse=True)
        _, _, ext_dir, storage = candidates[0]
        return ext_dir, storage

    raise PokeFinderNotFoundError(
        "找不到 Chrome / Edge / Brave 中的「Poke Finder」擴充或存檔資料。\n"
        "請先在瀏覽器安裝 Poke Finder 擴充並至少捕捉 1 隻寶可夢後再同步。"
    )


def get_storage_signature(storage_dir: Path) -> tuple[tuple[str, int, int], ...]:
    """Fast file signature for background change detection (without copying or parsing)."""
    if not storage_dir.exists():
        return ()
    sig: list[tuple[str, int, int]] = []
    for f in sorted(storage_dir.iterdir()):
        if f.is_file() and f.suffix in (".ldb", ".log"):
            try:
                st = f.stat()
                sig.append((f.name, st.st_mtime_ns, st.st_size))
            except OSError:
                pass
    return tuple(sig)


def _extract_var_assets(bg: str) -> dict[str, str]:
    """Extract variable declarations holding inline data:image/gif;base64 or asset paths."""
    var_map: dict[str, str] = {}
    pat_b64 = re.compile(
        r'(?:^|[,;\s])([A-Za-z_$][A-Za-z0-9_$]*)=([`"\'])(data:image/gif;base64,[A-Za-z0-9+/=]+)\2'
    )
    for m in pat_b64.finditer(bg):
        var_map[m.group(1)] = m.group(3)

    pat_file = re.compile(
        r'(?:^|[,;\s])([A-Za-z_$][A-Za-z0-9_$]*)=([`"\'])((?:/?assets/)?[^`"\']+?\.gif)\2'
    )
    for m in pat_file.finditer(bg):
        var_map.setdefault(m.group(1), m.group(3))
    return var_map


def _extract_media_map(bg: str, var_map: dict[str, str]) -> dict[str, str]:
    """Extract all Object.assign({"../../media/...gif": varName}) mappings."""
    media_map: dict[str, str] = {}
    for m in re.finditer(r'Object\.assign\(\{(\"(?:\.\./)+media/[^}]*)\}\)', bg):
        body = m.group(1)
        for pair in re.finditer(r'\"((?:\.\./)+media/[^\"]+\.gif)\":([A-Za-z_$][A-Za-z0-9_$]*)', body):
            rel = re.sub(r'^(?:\.\./)+', "", pair.group(1))
            val = var_map.get(pair.group(2))
            if val:
                media_map[rel] = val
    return media_map


def _extract_standard_catalog(bg: str) -> dict[str, dict[str, Any]]:
    """Parse standard Pokémon entries from background.js catalog declaratively."""
    catalog: dict[str, dict[str, Any]] = {}
    start = bg.find("pokemon:[{id:`")
    if start != -1:
        end = bg.find("]}", start)
        chunk = bg[start : (end + 2 if end != -1 else start + 2_000_000)]
        parts = chunk.split("{id:`")[1:]
        for part in parts:
            pid_m = re.match(r"([^`]+)`", part)
            dex_m = re.search(r"nationalDexNumber:(\d+)", part)
            slug_m = re.search(r"slug:`([^`]+)`", part)
            name_m = re.search(r"name:`([^`]+)`", part)
            names_m = re.search(r"names:\{([^}]*)\}", part)
            gen_m = re.search(r"generation:(\d+)", part)
            types_m = re.search(r"types:\[([^\]]*)\]", part)
            leg_m = re.search(r"isLegendary:(!\d)", part)
            myth_m = re.search(r"isMythical:(!\d)", part)
            stats_m = re.search(r"baseStats:\{([^}]*)\}", part)
            reg_m = re.search(r"regular:\{idle:`([^`]*)`,walk:`([^`]*)`\}", part)
            shi_m = re.search(r"shiny:\{idle:`([^`]*)`,walk:`([^`]*)`\}", part)
            if not (pid_m and dex_m and slug_m and name_m and reg_m):
                continue
            pid = pid_m.group(1)
            names_raw = names_m.group(1) if names_m else ""
            zh_tw = re.search(r'"zh-TW":`([^`]+)`', names_raw)
            ja = re.search(r"ja:`([^`]+)`", names_raw)
            types = re.findall(r"`([^`]+)`", types_m.group(1)) if types_m else []
            stats: dict[str, int] = {}
            if stats_m:
                for sm in re.finditer(r"([A-Za-z]+):(\d+)", stats_m.group(1)):
                    stats[sm.group(1)] = int(sm.group(2))
            catalog[pid] = {
                "id": pid,
                "dex": int(dex_m.group(1)),
                "slug": slug_m.group(1),
                "name_en": name_m.group(1),
                "name_zh": zh_tw.group(1) if zh_tw else name_m.group(1),
                "name_ja": ja.group(1) if ja else "",
                "generation": int(gen_m.group(1)) if gen_m else 1,
                "types": types,
                "is_legendary": bool(leg_m and leg_m.group(1) == "!0"),
                "is_mythical": bool(myth_m and myth_m.group(1) == "!0"),
                "stats": stats,
                "regular_idle": reg_m.group(1),
                "regular_walk": reg_m.group(2),
                "shiny_idle": shi_m.group(1) if shi_m else reg_m.group(1),
                "shiny_walk": shi_m.group(2) if shi_m else reg_m.group(2),
            }

    # Parse celestial entries (e.g., shadow-mewtwo)
    cel_pat = re.compile(r'\{slug:`([^`]+)`,baseId:`([^`]+)`,names:\{([^}]*)\}\}')
    for m in cel_pat.finditer(bg):
        slug = m.group(1)
        base_id = m.group(2)
        names_raw = m.group(3)
        zh_tw = re.search(r'"zh-TW":`([^`]+)`', names_raw)
        en = re.search(r"en:`([^`]+)`", names_raw)
        base = catalog.get(base_id, {})
        cid = f"celestial:{slug}"
        catalog[cid] = {
            "id": cid,
            "dex": base.get("dex", 150),
            "slug": slug,
            "name_en": en.group(1) if en else slug,
            "name_zh": zh_tw.group(1) if zh_tw else (en.group(1) if en else slug),
            "name_ja": "",
            "generation": base.get("generation", 1),
            "types": base.get("types", ["psychic"]),
            "is_legendary": True,
            "is_mythical": False,
            "is_special": True,
            "stats": base.get("stats", {}),
            "regular_idle": f"media/celestial/{slug}/clips/idle.gif",
            "regular_walk": f"media/celestial/{slug}/clips/walk.gif",
            "shiny_idle": f"media/celestial/{slug}/clips/idle.gif",
            "shiny_walk": f"media/celestial/{slug}/clips/walk.gif",
        }
    return catalog


def _write_gif(asset_val: str | None, ext_dir: Path, out_path: Path) -> bool:
    if not asset_val:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if asset_val.startswith("data:image/gif;base64,"):
        raw = base64.b64decode(asset_val.split(",", 1)[1])
        out_path.write_bytes(raw)
        return True
    candidate = ext_dir / asset_val.lstrip("/")
    if candidate.exists():
        shutil.copy2(candidate, out_path)
        return True
    alt = ext_dir / "assets" / Path(asset_val).name
    if alt.exists():
        shutil.copy2(alt, out_path)
        return True
    return False


def resolve_sprite_path(raw_path: str) -> Path:
    """Resolve a sprite path cleanly whether stored relatively or legacy-absolute."""
    p = Path(raw_path)
    if p.is_absolute() and p.exists():
        return p
    rel = DATA_DIR / raw_path
    if rel.exists():
        return rel
    by_name = SPRITES_DIR / p.name
    if by_name.exists():
        return by_name
    return rel


def _make_safe_key(pid: str, is_shiny: bool) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", pid) + ("_shiny" if is_shiny else "")


def sync_all(incremental: bool = False) -> dict[str, Any]:
    """Run full or incremental read-only sync from browser Poke Finder to local data/."""
    ext_dir, storage_dir = find_pokefinder_paths()
    storage = read_chrome_extension_storage(storage_dir)
    player_state = storage.get("player-state", {})
    companion_state = storage.get("companion-state", [])
    captures = player_state.get("captures", []) if isinstance(player_state, dict) else []

    # Load previous catalog for diffing and fast incremental metadata reuse
    prev_by_key: dict[str, dict[str, Any]] = {}
    if CAUGHT_JSON.exists():
        try:
            prev_payload = json.loads(CAUGHT_JSON.read_text(encoding="utf-8"))
            for item in prev_payload.get("pokemon", []):
                prev_by_key[item["key"]] = item
        except Exception:
            prev_by_key = {}

    grouped: dict[tuple[str, bool], dict[str, Any]] = {}
    for cap in captures:
        if not isinstance(cap, dict):
            continue
        pid = str(cap.get("pokemonId", "")).strip()
        if not pid:
            continue
        is_shiny = bool(cap.get("isShiny", False))
        key = (pid, is_shiny)
        caught_at = float(cap.get("caughtAt") or 0)
        if key not in grouped:
            grouped[key] = {
                "pokemon_id": pid,
                "is_shiny": is_shiny,
                "count": 1,
                "first_caught_at": caught_at,
                "last_caught_at": caught_at,
                "generation": cap.get("generation"),
            }
        else:
            grouped[key]["count"] += 1
            if caught_at and caught_at < grouped[key]["first_caught_at"]:
                grouped[key]["first_caught_at"] = caught_at
            if caught_at > grouped[key]["last_caught_at"]:
                grouped[key]["last_caught_at"] = caught_at

    companion_fallback: dict[str, dict[str, Any]] = {}
    active_companion_ids: list[str] = []
    if isinstance(companion_state, list):
        for comp in companion_state:
            if isinstance(comp, dict) and comp.get("pokemonId"):
                cid = str(comp["pokemonId"])
                active_companion_ids.append(cid)
                companion_fallback[cid] = comp

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SPRITES_DIR.mkdir(parents=True, exist_ok=True)

    # Check if we need to parse background.js at all when incremental=True
    need_bg_parse = not incremental
    if incremental:
        for pid, is_shiny in grouped:
            skey = _make_safe_key(pid, is_shiny)
            idle_file = SPRITES_DIR / f"{skey}_idle.gif"
            walk_file = SPRITES_DIR / f"{skey}_walk.gif"
            if skey not in prev_by_key or not idle_file.exists() or not walk_file.exists():
                need_bg_parse = True
                break

    var_map: dict[str, str] = {}
    media_map: dict[str, str] = {}
    catalog: dict[str, dict[str, Any]] = {}
    if need_bg_parse:
        bg_text = (ext_dir / "background.js").read_text(encoding="utf-8", errors="ignore")
        var_map = _extract_var_assets(bg_text)
        media_map = _extract_media_map(bg_text, var_map)
        catalog = _extract_standard_catalog(bg_text)

    exported: list[dict[str, Any]] = []
    missing_sprites: list[str] = []
    new_catches: list[dict[str, Any]] = []

    for (pid, is_shiny), rec in grouped.items():
        safe_key = _make_safe_key(pid, is_shiny)
        idle_file = SPRITES_DIR / f"{safe_key}_idle.gif"
        walk_file = SPRITES_DIR / f"{safe_key}_walk.gif"
        prev_item = prev_by_key.get(safe_key)

        if not need_bg_parse and prev_item and idle_file.exists() and walk_file.exists():
            entry = dict(prev_item)
            entry["count"] = rec["count"]
            entry["last_caught_at"] = rec["last_caught_at"]
            entry["idle_gif"] = f"sprites/{safe_key}_idle.gif"
            entry["walk_gif"] = f"sprites/{safe_key}_walk.gif"
            exported.append(entry)
            if rec["count"] > int(prev_item.get("count", 0)):
                new_catches.append(
                    {
                        "key": safe_key,
                        "pokemon_id": pid,
                        "name_zh": entry["name_zh"],
                        "is_shiny": is_shiny,
                        "added_count": rec["count"] - int(prev_item.get("count", 0)),
                        "is_new_species": False,
                        "last_caught_at": rec["last_caught_at"],
                    }
                )
            continue

        meta = catalog.get(pid)
        is_special = pid.startswith("special:") or pid.startswith("celestial:")

        if meta is None and pid.startswith("special:pikachu-"):
            variant = pid.split("special:pikachu-", 1)[1]
            zh_name, en_name = SPECIAL_PIKACHU_ZH.get(
                variant, (f"限定皮卡丘 ({variant})", f"Pikachu ({variant})")
            )
            base_pika = catalog.get("1:pikachu", {})
            meta = {
                "id": pid,
                "dex": 25,
                "slug": f"pikachu-{variant}",
                "name_en": en_name,
                "name_zh": zh_name,
                "name_ja": "ピカチュウ",
                "generation": 1,
                "types": ["electric"],
                "is_legendary": False,
                "is_mythical": False,
                "is_special": True,
                "stats": base_pika.get("stats", {"hp": 35, "attack": 55, "defense": 40, "speed": 90}),
                "regular_idle": f"media/special/pikachu-cap-festival/{variant}/default_idle_8fps.gif",
                "regular_walk": f"media/special/pikachu-cap-festival/{variant}/default_walk_8fps.gif",
                "shiny_idle": f"media/special/pikachu-cap-festival/{variant}/shiny_idle_8fps.gif",
                "shiny_walk": f"media/special/pikachu-cap-festival/{variant}/shiny_walk_8fps.gif",
            }
        elif meta is None:
            meta = {
                "id": pid,
                "dex": 0,
                "slug": pid.replace(":", "_"),
                "name_en": pid,
                "name_zh": companion_fallback.get(pid, {}).get("name", pid),
                "name_ja": "",
                "generation": rec.get("generation") or 1,
                "types": [],
                "is_legendary": False,
                "is_mythical": False,
                "is_special": is_special,
                "stats": {},
                "regular_idle": "",
                "regular_walk": "",
                "shiny_idle": "",
                "shiny_walk": "",
            }

        ok_idle = incremental and idle_file.exists()
        ok_walk = incremental and walk_file.exists()

        if not ok_idle:
            idle_rel = meta["shiny_idle"] if is_shiny else meta["regular_idle"]
            idle_val = media_map.get(idle_rel)
            if not idle_val and pid in companion_fallback:
                idle_val = companion_fallback[pid].get("idleUrl")
            ok_idle = _write_gif(idle_val, ext_dir, idle_file)

        if not ok_walk:
            walk_rel = meta["shiny_walk"] if is_shiny else meta["regular_walk"]
            walk_val = media_map.get(walk_rel)
            if not walk_val and pid in companion_fallback:
                walk_val = companion_fallback[pid].get("walkUrl")
            ok_walk = _write_gif(walk_val, ext_dir, walk_file)

        if not ok_walk and ok_idle:
            shutil.copy2(idle_file, walk_file)
            ok_walk = True
        if not ok_idle and ok_walk:
            shutil.copy2(walk_file, idle_file)
            ok_idle = True

        if not ok_idle:
            missing_sprites.append(pid)
            continue

        entry = {
            "key": safe_key,
            "pokemon_id": pid,
            "dex": meta["dex"],
            "slug": meta["slug"],
            "name_zh": meta["name_zh"],
            "name_en": meta["name_en"],
            "generation": meta["generation"],
            "types": meta["types"],
            "is_shiny": is_shiny,
            "is_special": bool(meta.get("is_special") or is_special),
            "is_legendary": bool(meta.get("is_legendary", False)),
            "is_mythical": bool(meta.get("is_mythical", False)),
            "stats": meta.get("stats", {}),
            "count": rec["count"],
            "last_caught_at": rec["last_caught_at"],
            "idle_gif": f"sprites/{safe_key}_idle.gif",
            "walk_gif": f"sprites/{safe_key}_walk.gif",
        }
        exported.append(entry)

        prev_cnt = int(prev_item.get("count", 0)) if prev_item else 0
        if rec["count"] > prev_cnt:
            new_catches.append(
                {
                    "key": safe_key,
                    "pokemon_id": pid,
                    "name_zh": entry["name_zh"],
                    "is_shiny": is_shiny,
                    "added_count": rec["count"] - prev_cnt,
                    "is_new_species": prev_item is None,
                    "last_caught_at": rec["last_caught_at"],
                }
            )

    exported.sort(
        key=lambda x: (
            0 if x["is_special"] else 1,
            0 if x["is_shiny"] else 1,
            x["dex"] if x["dex"] > 0 else 9999,
            x["name_zh"],
        )
    )
    new_catches.sort(key=lambda x: x["last_caught_at"], reverse=True)

    payload = {
        "extension_version": ext_dir.name,
        "total_captures": len(captures),
        "unique_count": len(exported),
        "active_companions": active_companion_ids,
        "missing_sprites": missing_sprites,
        "pokemon": exported,
    }
    tmp_json = CAUGHT_JSON.with_suffix(".tmp")
    tmp_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_json, CAUGHT_JSON)

    payload["new_catches"] = new_catches
    return payload


if __name__ == "__main__":
    result = sync_all()
    print(f"同步完成！擴充版本: {result['extension_version']}")
    print(f"總捕獲數: {result['total_captures']} | 可用獨特寶可夢: {result['unique_count']} 隻")
    print(f"目前 Poke Finder 夥伴: {result['active_companions']}")
    if result["missing_sprites"]:
        print(f"缺少圖檔: {result['missing_sprites']}")
    else:
        print("全部已捕獲寶可夢動畫圖檔 100% 匯出成功！")
