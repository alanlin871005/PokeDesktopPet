# PokeDesktopPet — 寶可夢 Windows 透明互動桌寵

一款專為 Chrome / Edge / Brave 瀏覽器擴充功能 **Poke Finder** 打造的 Windows 透明像素桌面寵物。  
不綁定帳號、不竄改瀏覽器存檔、**不內建任何他人存檔或版權素材**——直接從你自己的瀏覽器唯讀同步已捕獲的寶可夢，讓牠們跳出網頁陪你一起工作！

## ✨ 完整功能亮點

1. **唯讀同步你自己的 Poke Finder 圖鑑**
   - 自動掃描本機 Chrome / Edge / Brave 的 Poke Finder 擴充存檔（LevelDB + Snappy 純 Python 唯讀解碼，絕不寫入或影響瀏覽器）。
   - 支援閃光（Shiny）、特殊造型（如帽皮卡丘、暗影超夢）與多隻同場（最多 6 隻）。
   - 若首次啟動尚未安裝 Poke Finder，會顯示友善引導視窗（不閃退）。
2. **圖鑑盒長按拖曳召喚**
   - 雙擊桌寵或右鍵打開「我的寶可夢圖鑑盒」，支援搜尋、世代／閃光／特殊篩選與 PokéAPI 免 Key 百科查詢。
   - **長按任一寶可夢卡片直接拖出圖鑑視窗外放開**，即可在滑鼠落點即時召喚登場。
3. **跳上視窗標題列 & 拋物線丟樹果互動**
   - 透過 Win32 `EnumWindows` + `DwmGetWindowAttribute` 偵測桌面可視視窗上緣，寶可夢會跳上視窗標題列散步、隨著視窗移動或自行跳回工作列。
   - 右鍵選擇 **🍓 丟一顆樹果**，桌寵會主動衝過去搶吃樹果、冒出愛心粒子並累積 **💖 親密度等級**。
4. **背景自動偵測捕獲 & 貼心管家模式**
   - **自動背景增量同步**：在瀏覽器抓到新寶可夢時，桌寵會自動同步並跳起來祝賀（閃光另有特別提示）。
   - **系統負載與深夜提醒**：輕量監控 CPU / RAM / GPU（可選），高負載時冒汗提醒存檔；凌晨 00:00–05:00 會打哈欠催你睡覺。
   - **久坐喝水番茄鐘**：可自由開關並選擇 `30 / 45 / 60` 分鐘提醒喝水伸展。
5. **原版音效 & 8-bit 叫聲彩蛋**
   - 執行期唯讀讀取你本機 Poke Finder 擴充內的 `.wav` 原版音效（摸頭、登場、吃樹果、新捕獲），並附帶執行期合成的 8-bit 寶可夢叫聲彩蛋與一鍵靜音開關。
6. **零額外開 Port 本機遙控（`pet_ctl.py`）**
   - 透過本機檔案佇列 `data/remote_cmd.json` 輪詢（不開任何網路監聽埠），讓本機腳本或 AI 助手（如 Telegram + AstrBot）直接控制桌寵舉牌說話、換角、召喚或丟樹果。

---

## 🚀 快速開始（朋友下載免安裝版）

1. 前往本倉庫右側的 **[Releases](../../releases)** 下載最新版的 `PokeDesktopPet.exe`。
2. 確認你的 Chrome / Edge / Brave 已安裝 **[Poke Finder](https://chromewebstore.google.com/detail/cihconljhkbpanliediapecopanoccem)** 擴充並至少捕捉過 **1 隻** 寶可夢。
3. 直接雙擊 `PokeDesktopPet.exe` 即可使用（程式會在同層建立 `data/` 保存你的個人設定與同步快取）。

> 💡 小提醒：單檔 `.exe` 具備防雙開保護，若桌寵已在運行，再次雙擊會直接幫你喚出「我的寶可夢圖鑑盒」。

---

## 🖱️ 常用操作說明

| 操作 | 效果 |
|---|---|
| **左鍵點擊** | 摸摸頭，寶可夢會跳起來冒出心情台詞與音效 |
| **左鍵拖曳** | 把牠抓起來丟到任何視窗標題列上方或桌面角落 |
| **左鍵雙擊** | 打開「我的寶可夢圖鑑盒」 |
| **圖鑑卡片長按拖出視窗外** | 顯示半透明預覽，放開即在游標處召喚登場 |
| **右鍵選單** | 丟樹果、聽叫聲彩蛋、切換行為模式、縮放 2x–5x、音效開關、喝水提醒、手動同步、收回／關閉 |

---

## 🤖 本機指令遙控（`pet_ctl.py`，零額外開 Port）

若要透過終端機、排程或本機 AI 機器人控制桌寵，請使用隨附的純標準庫腳本 `pet_ctl.py`：

```bash
# 查看目前桌寵狀態與親密度
python pet_ctl.py status

# 搜尋已捕獲的寶可夢
python pet_ctl.py list 皮卡丘

# 讓主桌寵舉牌說話
python pet_ctl.py say "記得起身喝口水休息一下！"

# 切換主桌寵（支援中文名、英文名或圖鑑編號）
python pet_ctl.py switch 暗影超夢
python pet_ctl.py switch 25

# 召喚新夥伴或丟樹果
python pet_ctl.py spawn 快龍
python pet_ctl.py berry --count 2

# 立即同步瀏覽器存檔或切換行為模式
python pet_ctl.py sync
python pet_ctl.py mode follow
python pet_ctl.py sound off
```

---

## 🛠️ 從原始碼執行與自行打包

需求：Windows 10 / 11、Python 3.11+

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 直接啟動
python pet_app.py

# 自行打包成單檔 .exe
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name PokeDesktopPet --hidden-import PIL._tkinter_finder pet_app.py
```

---

## 🔒 隱私與版權隔離說明

- 本倉庫嚴格排除 `data/`、`sprites/`、`caught_pokemon.json`、`settings.json` 及任何瀏覽器擴充圖像／音訊素材。
- 程式不會修改瀏覽器檔案，僅在執行期唯讀複製瀏覽器 LevelDB 暫存副本來同步使用者自己的捕獲紀錄。
- 若您不希望上傳個人紀錄，請勿移除 `.gitignore` 中的 `data/` 規則。

## 📄 License

[MIT License](./LICENSE)
