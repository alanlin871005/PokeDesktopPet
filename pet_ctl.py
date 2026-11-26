"""
PokeDesktopPet 本機指令列工具（零額外開 Port）
- 透過原子寫入 data/remote_cmd.json 與讀取 data/pet_status.json，與執行中的桌寵溝通
- 供 Telegram 阿飛（AstrBot）或 Windows 腳本直接控制桌寵舉牌、換角、召喚、丟樹果與同步
- 僅使用 Python 標準函式庫，不開任何網路監聽埠
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any


def _ensure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def get_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        app_root = Path(sys.executable).resolve().parent
    else:
        app_root = Path(__file__).resolve().parent
    preferred = app_root / "data"
    if preferred.exists():
        return preferred
    fallback = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PokeDesktopPet" / "data"
    if fallback.exists():
        return fallback
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def _atomic_read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            time.sleep(0.03)
        except json.JSONDecodeError:
            return default
    return default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:6]}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for _ in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.04)
    os.replace(tmp, path)


def enqueue_command(data_dir: Path, cmd: dict[str, Any]) -> dict[str, Any]:
    cmd_file = data_dir / "remote_cmd.json"
    entry = {
        "id": uuid.uuid4().hex[:10],
        "ts": time.time(),
        "source": cmd.pop("source", "pet_ctl"),
        **cmd,
    }
    existing = _atomic_read_json(cmd_file, [])
    if isinstance(existing, dict):
        queue = [existing] if existing.get("action") else []
    elif isinstance(existing, list):
        queue = existing
    else:
        queue = []
    queue.append(entry)
    _atomic_write_json(cmd_file, queue)
    return entry


def load_catalog(data_dir: Path) -> list[dict[str, Any]]:
    caught_file = data_dir / "caught_pokemon.json"
    data = _atomic_read_json(caught_file, {})
    return data.get("pokemon", []) if isinstance(data, dict) else []


def match_pokemon(catalog: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    q = query.strip().lower().lstrip("#")
    if not q:
        return []

    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for p in catalog:
        dex_str = str(p.get("dex", ""))
        fields = [
            str(p.get("key", "")).lower(),
            str(p.get("pokemon_id", "")).lower(),
            str(p.get("slug", "")).lower(),
            str(p.get("name_zh", "")).lower(),
            str(p.get("name_en", "")).lower(),
            dex_str,
            dex_str.zfill(3),
        ]
        if q in fields:
            exact.append(p)
        elif any(q in f for f in fields):
            partial.append(p)
    return exact + partial


def _is_pet_running(status: dict[str, Any]) -> bool:
    updated_at = float(status.get("updated_at") or 0)
    if updated_at and (time.time() - updated_at) < 15:
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="pet_ctl.py",
        description="PokeDesktopPet 本機無 Port 指令控制器（供 Telegram 阿飛 / 腳本使用）",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p_say = sub.add_parser("say", help="讓桌寵舉牌冒泡說話")
    p_say.add_argument("text", help="要顯示的文字內容")
    p_say.add_argument("--pet", default="", help="指定哪隻寶可夢說話（預設主桌寵；all=全部）")
    p_say.add_argument("--duration", type=int, default=5500, help="氣泡顯示毫秒數（預設 5500）")
    p_say.add_argument("--tag", default="阿飛", help="來源標記（預設 阿飛；傳空字串可不加前綴）")

    p_sw = sub.add_parser("switch", help="把主桌寵切換成指定寶可夢")
    p_sw.add_argument("target", help="中文名、英文名、圖鑑編號或 key（例如 皮卡丘 / 超夢 / 25）")
    p_sw.add_argument("--index", type=int, default=0, help="要替換的場上桌寵索引（預設 0）")

    p_sp = sub.add_parser("spawn", help="召喚一隻寶可夢到桌面")
    p_sp.add_argument("target", nargs="?", default="random", help="寶可夢名稱／編號，或 random")

    p_br = sub.add_parser("berry", help="丟樹果到桌面上讓桌寵搶吃增加親密度")
    p_br.add_argument("--count", type=int, default=1, help="樹果數量（1～5）")

    sub.add_parser("sync", help="立刻從瀏覽器 Poke Finder 唯讀同步最新存檔")
    sub.add_parser("water", help="立刻觸發一次貼心喝水／休息提醒")
    sub.add_parser("status", help="查看目前桌寵狀態、場上夥伴與親密度")

    p_mode = sub.add_parser("mode", help="切換桌寵行為模式")
    p_mode.add_argument("mode", choices=["wander", "follow", "idle"], help="wander=自由散步 / follow=跟隨滑鼠 / idle=待在原地")

    p_snd = sub.add_parser("sound", help="控制音效開關或觸發叫聲彩蛋")
    p_snd.add_argument("state", choices=["on", "off", "toggle", "cry"], help="on / off / toggle / cry")

    p_ls = sub.add_parser("list", help="搜尋本機已同步的寶可夢圖鑑")
    p_ls.add_argument("query", nargs="?", default="", help="關鍵字或圖鑑編號")

    args = parser.parse_args(argv)
    data_dir = get_data_dir()

    if args.action == "list":
        catalog = load_catalog(data_dir)
        matches = match_pokemon(catalog, args.query) if args.query else catalog
        print(f"共找到 {len(matches)} 種已捕獲寶可夢（顯示前 30 筆）：")
        for p in matches[:30]:
            badge = "✨閃光 " if p.get("is_shiny") else ("⭐" if p.get("is_special") else "")
            print(f"- #{p.get('dex', 0):03d} {badge}{p['name_zh']} ({p['name_en']}) | key={p['key']} | x{p.get('count', 1)}")
        return 0

    if args.action == "status":
        status = _atomic_read_json(data_dir / "pet_status.json", {})
        if not status:
            print("尚未偵測到桌寵狀態紀錄（可能還沒啟動桌寵）。")
            return 0
        running = _is_pet_running(status)
        print(f"桌寵運行狀態：{'🟢 運作中' if running else '⚪ 離線（最後紀錄）'}")
        print(f"已收集：{status.get('unique_count', 0)} 種（總捕獲 {status.get('total_captures', 0)} 隻）")
        print(f"音效：{'開啟' if status.get('sound_enabled', True) else '靜音'}｜模式：{status.get('mode', '?')}｜視窗棲息：{'開啟' if status.get('perch_enabled', True) else '關閉'}")
        sys_info = status.get("system", {})
        if sys_info:
            gpu_str = f"｜GPU {sys_info['gpu']}%" if sys_info.get("gpu") is not None else ""
            print(f"系統負載：CPU {sys_info.get('cpu', '?')}%｜RAM {sys_info.get('ram', '?')}%{gpu_str}")
        pets = status.get("pets", [])
        print(f"目前場上（{len(pets)} 隻）：")
        for idx, pt in enumerate(pets):
            perch = "（站在視窗標題列上）" if pt.get("perched") else ""
            print(f"  [{idx}] {pt.get('name_zh')} (#{pt.get('dex', 0):03d}) · 親密度 Lv.{pt.get('affection_lv', 1)} ({pt.get('affection', 0)} 分) {perch}")
        return 0

    if args.action == "say":
        text = args.text.strip()
        if args.tag:
            text = f"📨 [{args.tag}] {text}"
        entry = enqueue_command(
            data_dir,
            {"action": "say", "text": text, "pet": args.pet, "duration": max(1500, min(args.duration, 20000))},
        )
        print(f"已送出舉牌指令（id={entry['id']}）：{text}")
        return 0

    if args.action in ("switch", "spawn"):
        target = args.target.strip()
        if args.action == "spawn" and target.lower() in ("", "random", "隨機"):
            entry = enqueue_command(data_dir, {"action": "spawn", "target": "random"})
            print(f"已送出隨機召喚指令（id={entry['id']}）")
            return 0
        catalog = load_catalog(data_dir)
        matches = match_pokemon(catalog, target)
        if not matches:
            print(f"找不到符合「{target}」的已捕獲寶可夢，請先用 list 指令查詢。")
            return 1
        picked = matches[0]
        payload: dict[str, Any] = {"action": args.action, "key": picked["key"], "target": picked["name_zh"]}
        if args.action == "switch":
            payload["index"] = args.index
        entry = enqueue_command(data_dir, payload)
        verb = "切換" if args.action == "switch" else "召喚"
        print(f"已送出{verb}指令（id={entry['id']}）→ {picked['name_zh']} ({picked['key']})")
        return 0

    if args.action == "berry":
        cnt = max(1, min(5, int(args.count)))
        entry = enqueue_command(data_dir, {"action": "berry", "count": cnt})
        print(f"已送出丟樹果指令（id={entry['id']}）：🍓 x{cnt}")
        return 0

    if args.action == "sync":
        entry = enqueue_command(data_dir, {"action": "sync"})
        print(f"已送出同步存檔指令（id={entry['id']}）")
        return 0

    if args.action == "water":
        entry = enqueue_command(data_dir, {"action": "water"})
        print(f"已送出喝水提醒指令（id={entry['id']}）")
        return 0

    if args.action == "mode":
        entry = enqueue_command(data_dir, {"action": "mode", "mode": args.mode})
        print(f"已送出行為模式切換指令（id={entry['id']}）：{args.mode}")
        return 0

    if args.action == "sound":
        entry = enqueue_command(data_dir, {"action": "sound", "state": args.state})
        print(f"已送出音效指令（id={entry['id']}）：{args.state}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
