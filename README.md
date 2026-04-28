# Taipei Track Field Schedule Notifier

每天下午 17:00（台灣時間，加上 18:00 backup）檢查台北市政府體育局網頁，找「臺北田徑場月份活動一覽表」最新 PDF，解析主場 PDF，判斷該月每個週二是否有租借，把結果推到 Telegram。**每天都發**(用來確認服務還活著);PDF 有更新時標題會加 🆕;同一份 PDF 同一天不重複發(雙 cron 容錯)。

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
