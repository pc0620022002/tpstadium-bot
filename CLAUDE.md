# tpstadium-bot — 專案交接資訊

## 這個專案做什麼

每天下午 17:00（台灣時間）自動跑：
1. 爬 [台北市體育局公告頁面](https://sports.gov.taipei/News.aspx?n=E216AB320D1BDFF5&sms=9D72E82EC16F3E64)
2. 找出「最新月份臺北田徑場主場及暖身場活動一覽表」那則公告的子頁
3. 下載主場 PDF（檔名含「田徑場」，排除「暖身」）
4. 用 `pdfplumber` 解析表格，取出所有活動的日期與狀態
5. 找出該月所有週二，判斷是否有活動佔用
6. 透過 Telegram bot 推播給 user

**每天都會發**（不只在 PDF 有更新時）。PDF 有更新時標題會加 🆕。

## 位置

- 本機：`~/Documents/Projects/tpstadium-bot/`
- GitHub：`pc0620022002/tpstadium-bot`（**public**,2026-04-29 從 private 改 public 以符合 self-trigger relay 架構對 GHA Actions 無限額度的需求)
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
`state.json` 存上次看到的 PDF URL、上次通知日期、上次通知的 PDF URL。GHA 每次跑完會 auto-commit 這個檔案（workflow 裡用 `contents: write` permission）。

- `is_updated` = 這次看到的 PDF URL 跟上次不一樣 → 只影響訊息標題加不加 🆕，不決定要不要發
- **同日去重**：`last_notify_date == 今天` 且 `last_notified_pdf_url == 這次的 PDF URL` → 跳過不發。為了 17:00 + 18:00 雙 cron 備援設計
- **`--force` 旁路**：`check.py --force` 或 workflow_dispatch 勾 `force=true` → 繞過同日去重 **以及** 時段保險，強制重發。過渡期改 cron 時間 / 手動補發用

### 時段保險（程式層擋 GHA 殘留排程）
`check.py` 啟動會讀 `EXPECTED_HOURS_TAIPEI` 環境變數（workflow yaml 設為 `"17,18,19,20,21,22,23"`）。如果當前 Taipei 小時不在這個 list 內，**直接 exit 0 不執行**。這是為了擋 GHA 內部 schedule 卡舊 cron、在非預期時間觸發 workflow 的情況。

範圍寬到 17-23 是因為 cron 觸發點覆蓋 17:00 主要時段 + 18-23 fallback,所有合法觸發都該被允許。

**改推播時間時要同步改兩個地方**：
1. `.github/workflows/check.yml` 的 `cron` 行
2. `.github/workflows/check.yml` 的 `EXPECTED_HOURS_TAIPEI` env var

只改 cron 不改 env var → GHA 卡舊排程觸發時會發；只改 env var 不改 cron → 改完不會發任何時間。兩個一起改才正確。

## 觸發架構：self-trigger relay(2026-04-29 起,不依賴 GHA cron 準時性)

**為什麼不靠 cron**:GHA free-tier cron 不保證準時,實測偶爾延遲 10+ 分鐘、跳過整小時、甚至連續多次 skip。靠 cron 推播會錯過。

**機制**:每個 GHA run 進入後,計算到下次 Taipei 17:00 的等待秒數。
- 等待 ≤ 5h40m:直接 sleep 到目標時間 → 跑 `check.py` → 用 `GITHUB_TOKEN` 呼叫 GHA API 觸發下一個 workflow_dispatch run → exit
- 等待 > 5h40m(例如 17:01 剛跑完,要等 24h 才到下一個 17:00):partial sleep 5h40m → 直接 relay 接力 → 下一個 run 啟動會重新計算,最終某個 run 等待 < 5h40m 時就執行
- chain 永遠維持,不靠 cron

**Cold start**:cron `0,30 7,8 * * *` = Taipei 15:00 / 15:30 / 16:00 / 16:30,4 個冗餘觸發點。任一個中即可啟動 chain。**故意避開 17:00 後的時段**,以免 cron 觸發新 run 時 cancel 掉正在 sleep 等 17:00 的 chain run。

**關鍵 yaml 設定**:
- `permissions.actions: write`(self-trigger 需要)
- `concurrency.group: tpstadium-bot` + `cancel-in-progress: true`(確保只跑一個 run)
- `timeout-minutes: 355`(5h55m,GHA free-tier 6h 上限留 5min margin)
- `if: failure()` 自動 auto-relay + 推 TG 警告(crash 也不會打斷 chain)

## Failure modes 與對應保險(完整清單,改之前先看)

每個可能讓 user「漏掉通知」或「收到不該收的」的情境,都該有程式層保險。如果發現 user 真的漏了某天,先對照這張表找哪條保險破了,**而不是只解這次的現象**。

| Failure mode | 對應保險 | Code 在哪 |
|---|---|---|
| 月份換版 PDF(4 月 → 5 月) | `fetch_latest_news()` 找列表頁最新「臺北田徑場」「活動一覽表」連結,**完全自動偵測**,不需手動 | `check.py: fetch_latest_news` |
| GHA cron 不準時 / 延遲 / skip | self-trigger relay,run 內部精確 sleep 到 Taipei 17:00,不依賴 cron | yaml `Wait for 17:00 Taipei` step |
| chain 從沒啟動過 | cold start cron 4 個觸發點(Taipei 15:00 / 15:30 / 16:00 / 16:30) | yaml `schedule` |
| chain 中某個 run 失敗 | `if: failure()` 自動 auto-relay 觸發接班 run + 推 TG 警告 | yaml `Notify on workflow failure` |
| chain 中某個 run 被 timeout / cancel | `cancel-in-progress: true` 配合 cron 重啟 chain;auto-relay 補強 | yaml `concurrency` |
| GHA cron 殘留舊排程亂觸發 | `EXPECTED_HOURS_TAIPEI` hour gate(17-23),非預期時段 exit 0 | `check.py: main()` 開頭 |
| 體育局網站偶發 timeout / 5xx | `robust_get` retry 3 次 backoff 2/5/10s | `check.py: robust_get` |
| Telegram API 偶發失敗 | `send_telegram` retry 3 次 backoff 2/5s,4xx 不重試 | `check.py: send_telegram` |
| 同日多次觸發(cron + chain 同日重疊) | 同日去重(`last_notify_date == 今天` 且 PDF URL 沒變則跳過) | `check.py: main()` |
| 想立刻補發 / 過渡期 | workflow_dispatch 勾 `force=true`(跳過 sleep + 繞過去重) | yaml `force` input |
| PDF parse 0 events(image-based / 結構大變 / 解碼失敗) | Sanity check:不論 table 有無,events==0 一律推警告,**永遠不發「整月可練跑」** | `check.py: main()` parse 後 |
| events>0 但所有 dates 解析失敗(日期欄格式變) | Sanity check:`total_dates==0 && events>0` → 推警告,不走 build_message | `check.py: main()` parse 後 |
| 月初體育局還沒上新月份 PDF | `pdf_is_outdated` 偵測:PDF 月份 < 當月 → 推「⏳ 體育局尚未上線 N 月 PDF」清晰訊息 | `check.py: main()` 在 build_message 前 |
| `pdfplumber` / `requests` major 版本升級 break | `requirements.txt` 有 major version 上限 (`<3`, `<5`, `<0.12`) | `requirements.txt` |
| relay 三次都失敗 → chain 默默斷掉 | `RELAY_OK=0` 後 `exit 1` → 觸發 `if: failure()` auto-relay + TG 警告 | yaml `Wait for 17:00` 末段 |
| run 剛好在 17:00:00 整啟動會推到明天 | yaml 用 `-gt` 而非 `-ge` 比較 NOW vs TARGET | yaml `Wait for 17:00 Taipei` step |
| state.json push 失敗 retry 也救不了 | retry 3 次,失敗則推 TG 註記「下次可能重複推一次,不是新 bug」 | yaml step 3(commit + push state) |

**剩下沒做的(已知缺口,風險與 trade-off 後決定先不做)**:

1. **GHA 整天 0 個 run 觸發 + chain 已斷**:極端情況,目前沒解。可能解法:外部獨立 heartbeat 服務(cron-job.org / UptimeRobot 每天 trigger workflow_dispatch)。**先不做,等真的踩到再加**。
2. **Telegram bot token 失效時連 failure alert 也發不出**:user 完全不知道服務壞了。完整解需要外部監控(token 體系外的 alert)。**先不做**,實務上 token 自己失效機率極低。
3. **state.json git push 持續失敗(超過 retry 上限)→ 同日重複推送**:concurrency cancel-in-progress + retry 3 次已能擋大部分 case;極端 race 才會 fail。發生時 user 會收到重複訊息(不是漏訊息),屬於小麻煩不是嚴重問題。**先不做更激進保險**(改 GHA cache 是 breaking change)。

⚠️ **架構約束**:self-trigger relay sleep 模式會把每日 GHA minutes 用滿(~1440 min/day)。**只在 public repo 可行**(public 對 GHA Actions 是無限免費)。**如果未來把 repo 改回 private,這套架構會立刻燒爆 quota,必須改回多 cron 觸發點模式**(commit `622713a` 那個版本)。

## 重要踩過的坑（改之前先看）

1. **SSL 憑證問題**：`sports.gov.taipei` 的 cert 缺 Subject Key Identifier，Python 3.12+ 嚴格驗證會爆。所以 `check.py` 裡 `VERIFY_SSL = False`。不要改掉。
2. **需要 User-Agent**：沒帶 UA 會被 server 擋/timeout。`HEADERS` 裡的 UA 別拿掉。
3. **Telegram parse mode 用 HTML 不用 Markdown**：PDF 裡的活動名稱會有 `2025/26` 這種字串，Markdown parser 會爆 "can't parse entities"。已改成 HTML，並用 `html_escape()` escape user content。
4. **民國轉西元**：title 裡的 `115年4月` = 2026-04，`extract_year_month` 做 `roc + 1911`。
5. **GHA cron 變更生效有滯後**：改 yaml 的 cron 後，GitHub 內部排程不一定立即同步，可能繼續用舊排程跑幾次。2026-04-28 把 08:00 改 17:00，2026-04-29 早上 08:00 還是被觸發。**所以 `check.py` 加了 `EXPECTED_HOURS_TAIPEI` 時段保險**（見「狀態追蹤」段落下方）。如果以後改時間又遇到怪行為，先檢查這個 env var 跟 cron 有沒有同步改。Disable→Enable workflow 也能強制 GitHub 重新註冊 schedule。
6. **GHA private repo 對 sleep 計費,self-trigger relay sleep 5h40m 模式會在 1-2 天內燒爆 free tier 2000 min/月配額**。所以 repo 必須是 public(2026-04-29 已改)。如果未來改回 private,本架構會立刻爆 quota,需改回多 cron 觸發點模式。
7. **GHA cron 對 free tier 不保證準時**:可能延遲 5-30 分鐘、跳過整小時、甚至連續多次 skip。**不要把「每天 17:00 推播」綁在 cron 準時性上**。本專案 2026-04-29 改成 self-trigger relay 架構就是因為踩到這個。
8. **誤推「整月可練跑」是嚴重後果**:user 拿這個訊息決定是否去現場練跑,誤推會害他白跑。`check.py` 對任何 parse 失敗的訊號(events==0 / events 有但 dates 全空)一律推警告 + 中止,不發誤導訊息。
9. **GHA bot 用 `secrets.GITHUB_TOKEN` 觸發 workflow_dispatch 可以 chain**(實測 mlb-npb-tracker + tpstadium-bot 都驗證)。但需要 `permissions.actions: write`。如果未來 GitHub 改 token 政策禁止 self-trigger,chain 會斷,要改用 PAT。

## 2026-04-29 完整事件時間線(踩坑歷史,改之前先看)

避免未來重蹈覆轍。整段教訓的核心:**不要 reactive 一次只解一個現象,要 proactive 一次盤點所有 failure mode**。

| 時間 | 事件 | 我的反應 / 處理 |
|---|---|---|
| 2026-04-28 17:00 Taipei | user 沒收到推播 | 解釋成「過渡期同日去重」,**只**加 `--force` flag(修一半) |
| 2026-04-29 08:00 Taipei | user 收到不該收的推播(GHA 用舊 cron 觸發) | 解釋成「GHA cron 變更滯後」,叫 user 自己 disable/enable workflow(推鍋平台級操作)。事後加 `EXPECTED_HOURS_TAIPEI` hour gate |
| 2026-04-29 17:11 Taipei | user 17:00 又沒收到 | 加 13 個 cron 觸發點 + retry + failure alert(reactive 補強) |
| 2026-04-29 17:17 Taipei | user 手動 Force notify 才收到 | user 抱怨「這麼簡單的專案還要手動」「不要互相干涉」;改 self-trigger relay 架構 |
| 2026-04-29 17:50 Taipei | self-trigger relay push 完才意識到 private repo quota 災難 | 改 public repo,quota 爆問題消失 |
| 2026-04-29 19:00+ Taipei | user 要求「再積極挖風險」 | 深度 audit 找出 5 個真實 bug + month mismatch detection,一次補完 |

**核心教訓**:reactive 處理(每次只解當下現象)會讓同一個簡單需求拖兩天、user 受不了。Proactive audit(一次盤點所有可能失敗模式)才能根本解決。**這個原則寫進全域 `~/.claude/CLAUDE.md` 的「排查 / 修 bug 的積極性」一節**。

## 檔案

| 檔案 | 作用 |
|---|---|
| `check.py` | 主程式。單檔 script。執行會解析→推播→存 state |
| `requirements.txt` | `requests`、`beautifulsoup4`、`pdfplumber` |
| `.github/workflows/check.yml` | Self-trigger relay 架構：cold start cron `0,30 7,8 * * *`（Taipei 15:00/15:30/16:00/16:30）+ workflow_dispatch（含 `force` input）+ run 內 sleep 到 17:00 + 自動接力下個 run + auto-commit state + 失敗自動 auto-relay + TG 警告 |
| `state.json` | 記錄上次抓到的 PDF URL（由 GHA 或本機跑 產生/更新） |
| `README.md` | 使用說明 |

## Telegram bot 資訊

- Bot：`@TPstadium_schedule_bot`
- Bot token：存在 GitHub repo secret `TELEGRAM_BOT_TOKEN`
- Chat ID：`8550308094`（存在 secret `TELEGRAM_CHAT_ID`）

本機測試需要 token 時：`gh secret` 看不到值，要去 BotFather 重抓，或從 user 提供。

⚠️ **secrets 在 public repo 仍是加密的**(GitHub Secrets 不會公開,即使 repo 改 public),`echo "$TELEGRAM_BOT_TOKEN"` 在 workflow log 會被自動 mask。但 PR fork 跑 workflow 預設**沒有** secrets 存取權,所以開 PR 觸發 workflow 不會洩露 token。**不要在 workflow yaml 把 secret 印到 log 或 commit 進 file**。

## 本機操作

```bash
cd ~/Documents/Projects/tpstadium-bot
# venv 已經在 .venv/
.venv/bin/pip install -r requirements.txt   # 如有新增依賴

# 乾跑（不發 Telegram，直接 print）
.venv/bin/python check.py

# 真發 Telegram
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=8550308094 .venv/bin/python check.py

# 強制重發（繞過同日去重，過渡期 / 手動補發用）
TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=8550308094 .venv/bin/python check.py --force
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
- 通知時間改動（改 `.github/workflows/check.yml` 裡的 cron；記得 cron 是 UTC）。**改之前先看全域 `~/.claude/CLAUDE.md` 的「修改定期任務觸發時間時的過渡期」一節**，過渡期可能漏發,有 force flag 可補救
- 改成只通知當週的週二，不是整月
- 支援跨月 PDF（例如一份 PDF 涵蓋 4-5 月）— 目前 `parse_date_cell` 有處理跨月範圍但沒實測過
