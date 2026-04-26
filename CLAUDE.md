# tpstadium-bot — 專案交接資訊

## 這個專案做什麼

每天早上 08:00（台灣時間）自動跑：
1. 爬 [台北市體育局公告頁面](https://sports.gov.taipei/News.aspx?n=E216AB320D1BDFF5&sms=9D72E82EC16F3E64)
2. 找出「最新月份臺北田徑場主場及暖身場活動一覽表」那則公告的子頁
3. 下載主場 PDF（檔名含「田徑場」，排除「暖身」）
4. 用 `pdfplumber` 解析表格，取出所有活動的日期與狀態
5. 找出該月所有週二，判斷是否有活動佔用
6. 透過 Telegram bot 推播給 user

**每天都會發**（不只在 PDF 有更新時）。PDF 有更新時標題會加 🆕。

## 位置

- 本機：`~/Documents/Projects/tpstadium-bot/`
- GitHub：`pc0620022002/tpstadium-bot`（private）
- Runtime：GitHub Actions（`.github/workflows/check.yml`）

## 架構與關鍵設計

### 爬蟲流程
列表頁 `News.aspx?n=E216AB320D1BDFF5&sms=9D72E82EC16F3E64` →
找到含「臺北田徑場」「活動一覽表」的 link →
進到 `News_Content.aspx?...&s=<ID>` 子頁 →
找兩個 `Download.ashx` 連結（主場 + 暖身場），依檔名區分（filename 在 URL 的 `n` 參數裡，base64 編碼）。

### PDF 解析
- 用 `pdfplumber.extract_tables()`，每列取 `[項次, 檔期名稱, 日期, 檔期地點及開放時段]`
- 日期格式：`M/D (週)` 單日、`M/D 至 D (週至週)` 同月範圍、理論上會有 `M/D 至 M/D` 跨月範圍（code 有處理）
- 狀態原文直接 show（例如 `全天暫停開放`、`開放時段：0500-0900, 暫停開放：0900-2200`），不做「能不能練跑」的額外判斷

### 狀態追蹤
`state.json` 存上次看到的 PDF URL。GHA 每次跑完會 auto-commit 這個檔案（workflow 裡用 `contents: write` permission）。
現在 `is_updated` 只影響 message 是否加 🆕，不決定要不要發。

## 重要踩過的坑（改之前先看）

1. **SSL 憑證問題**：`sports.gov.taipei` 的 cert 缺 Subject Key Identifier，Python 3.12+ 嚴格驗證會爆。所以 `check.py` 裡 `VERIFY_SSL = False`。不要改掉。
2. **需要 User-Agent**：沒帶 UA 會被 server 擋/timeout。`HEADERS` 裡的 UA 別拿掉。
3. **Telegram parse mode 用 HTML 不用 Markdown**：PDF 裡的活動名稱會有 `2025/26` 這種字串，Markdown parser 會爆 "can't parse entities"。已改成 HTML，並用 `html_escape()` escape user content。
4. **民國轉西元**：title 裡的 `115年4月` = 2026-04，`extract_year_month` 做 `roc + 1911`。

## 檔案

| 檔案 | 作用 |
|---|---|
| `check.py` | 主程式。單檔 script。執行會解析→推播→存 state |
| `requirements.txt` | `requests`、`beautifulsoup4`、`pdfplumber` |
| `.github/workflows/check.yml` | Cron `0 0 * * *`（UTC = 08:00 Taipei）+ manual dispatch + auto-commit state |
| `state.json` | 記錄上次抓到的 PDF URL（由 GHA 或本機跑 產生/更新） |
| `README.md` | 使用說明 |

## Telegram bot 資訊

- Bot：`@TPstadium_schedule_bot`
- Bot token：存在 GitHub repo secret `TELEGRAM_BOT_TOKEN`
- Chat ID：`8550308094`（存在 secret `TELEGRAM_CHAT_ID`）

本機測試需要 token 時：`gh secret` 看不到值，要去 BotFather 重抓，或從 user 提供。

## 本機操作

```bash
cd ~/Documents/Projects/tpstadium-bot
# venv 已經在 .venv/
.venv/bin/pip install -r requirements.txt   # 如有新增依賴

# 乾跑（不發 Telegram，直接 print）
.venv/bin/python check.py

# 真發 Telegram
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=8550308094 .venv/bin/python check.py
```

## GitHub 操作

`gh` CLI 沒登入，要操作 repo（設 secrets、觸發 workflow、看 log）時：
1. 到 https://github.com/settings/tokens/new?scopes=repo,workflow 建一個 PAT
2. `export GH_TOKEN=ghp_...` 後直接用 `gh <cmd> -R pc0620022002/tpstadium-bot`
3. 用完刪掉 PAT

常用指令：
```bash
gh workflow run check.yml -R pc0620022002/tpstadium-bot
gh run list -R pc0620022002/tpstadium-bot --limit 5
gh run view <RUN_ID> -R pc0620022002/tpstadium-bot --log
gh secret list -R pc0620022002/tpstadium-bot
```

## 已驗證可運作

- 4 月 PDF 解析結果：4/7、4/14、4/21 ✅ 無活動；4/28 ❌ 114 學年度臺北市天使盃樂樂棒球（全天暫停開放）
- GHA run 24818627111（最近一次手動觸發）成功推播

## 可能的後續需求

- 加暖身場資訊（目前 `state["warmup_url"]` 有存但沒解析）
- 通知時間改動（改 `.github/workflows/check.yml` 裡的 cron；記得 cron 是 UTC）
- 改成只通知當週的週二，不是整月
- 支援跨月 PDF（例如一份 PDF 涵蓋 4-5 月）— 目前 `parse_date_cell` 有處理跨月範圍但沒實測過
