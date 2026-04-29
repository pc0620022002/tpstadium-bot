# Taipei Track Field Schedule Notifier

每天下午 17:00（台灣時間）檢查台北市政府體育局網頁，找「臺北田徑場月份活動一覽表」最新 PDF，解析主場 PDF，判斷該月每個週二是否有租借，把結果推到 Telegram。

**重要行為**:
- **每天都發**(用來確認服務還活著);PDF 有更新時標題會加 🆕;同一份 PDF 同一天不重複發
- **月份切換 100% 自動**:程式自動偵測列表頁最新「臺北田徑場活動一覽表」,4 月→5 月→6 月... 完全不需手動
- **月初體育局還沒上新月份 PDF**:程式偵測到 PDF 月份 < 當月會推「⏳ 體育局尚未上線 N 月 PDF」清晰訊息(不會推上個月舊資料誤導 user)
- **PDF 結構大變或解析失敗**:推 TG 警告而**不發**「整月可練跑」誤導訊息(避免 user 跑現場踩雷)
- **任何環節失敗** → 自動推 TG 警告 + auto-relay 接班 run

透過 GitHub Actions self-trigger relay 架構運行(每個 run sleep 到 17:00 後執行,跑完用 `GITHUB_TOKEN` trigger 下一個 run 接力,不依賴 GHA cron 準時性。repo 必須是 public 才能用此架構,sleep 時間在 private repo 會吃光 free tier 配額)。

## Setup

### 1. 建 GitHub repo 並 push

```bash
cd ~/Documents/Projects/tpstadium-bot
git init
git add .
git commit -m "init"
git branch -M main
gh repo create tpstadium-bot --private --source=. --push
```

（或在 github.com 手動開 repo 後 `git remote add origin … && git push -u origin main`）

### 2. 設 Secrets

到 GitHub repo → Settings → Secrets and variables → Actions → New repository secret，新增兩個：

- `TELEGRAM_BOT_TOKEN` — Bot token
- `TELEGRAM_CHAT_ID` — 你的 chat ID

### 3. 驗證

- Actions 分頁 → 選 "Check Taipei Track Field Schedule" → Run workflow → 勾 "Force notify" → Run。應該會在 Telegram 收到訊息。
- 之後每天 09:00 UTC(17:00 台灣)+ 10:00 UTC(18:00 台灣 backup)自動跑。每天都會發,跨日才會發新的;同日同一份 PDF 不會重發。

## 本機跑

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx .venv/bin/python check.py
```

加 `--force` 可以繞過「同日同 PDF 已通知」的去重邏輯,強制再發一次(過渡期或手動補發用)。
