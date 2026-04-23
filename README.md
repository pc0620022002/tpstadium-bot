# Taipei Track Field Schedule Notifier

每天早上 08:00（台灣時間）檢查台北市政府體育局網頁，當「臺北田徑場月份活動一覽表」有新的或更新版 PDF 時，解析主場 PDF，判斷該月每個週二是否有租借，把結果推到 Telegram。

## Setup

### 1. 建 GitHub repo 並 push

```bash
cd ~/tpstadium-bot
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
- 之後每天 00:00 UTC（08:00 台灣）自動跑。只有 PDF URL 變動時才通知。

## 本機跑

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx .venv/bin/python check.py --force
```

不加 `--force` 時，若 URL 沒變會跳過通知。
