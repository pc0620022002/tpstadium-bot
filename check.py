#!/usr/bin/env python3
"""Check Taipei Track Field schedule, notify Telegram when updated."""

import os
import sys
import re
import io
import json
import base64
import calendar
import urllib.parse
from datetime import date, datetime, timezone, timedelta

import requests
import urllib3
from bs4 import BeautifulSoup
import pdfplumber

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
VERIFY_SSL = False  # sports.gov.taipei cert is missing Subject Key Identifier
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

LISTING_URL = "https://sports.gov.taipei/News.aspx?n=E216AB320D1BDFF5&sms=9D72E82EC16F3E64"
STATE_FILE = "state.json"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def robust_get(url, timeout=30, max_retries=3):
    """requests.get + retry with backoff for transient failures.

    Retries on connection errors, timeouts, and 5xx. 4xx is permanent — raise.
    Backoff: 2s, 5s, 10s. 政府網站偶發慢或一時抽風,不要單次 fetch 失敗就整個 run 掛掉。
    """
    import time
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout, verify=VERIFY_SSL, headers=HEADERS)
            if 500 <= r.status_code < 600:
                log(f"robust_get: {url[:80]} 回 {r.status_code}, attempt {attempt + 1}/{max_retries}")
                last_exc = requests.HTTPError(f"{r.status_code} server error")
            else:
                r.raise_for_status()
                return r
        except (requests.ConnectionError, requests.Timeout) as e:
            log(f"robust_get: {url[:80]} {type(e).__name__}: {e}, attempt {attempt + 1}/{max_retries}")
            last_exc = e
        if attempt < max_retries - 1:
            time.sleep([2, 5, 10][attempt])
    raise last_exc if last_exc else RuntimeError(f"robust_get exhausted retries: {url}")


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def fetch_latest_news():
    """Find the latest 'XX年X月臺北田徑場…活動一覽表' entry on listing page."""
    r = robust_get(LISTING_URL, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if "臺北田徑場" in text and "活動一覽表" in text:
            href = a.get("href", "")
            return urllib.parse.urljoin(LISTING_URL, href), text
    return None, None


def decode_download_filename(n_param):
    try:
        return base64.b64decode(urllib.parse.unquote(n_param)).decode("utf-8")
    except Exception:
        return ""


def fetch_pdf_urls(news_url):
    """Return (main_field_pdf_url, warmup_pdf_url)."""
    r = robust_get(news_url, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")
    main_url, warmup_url = None, None
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if "Download.ashx" not in href:
            continue
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        filename = decode_download_filename(qs.get("n", [""])[0])
        full = href if href.startswith("http") else urllib.parse.urljoin(news_url, href)
        if "暖身" in filename:
            warmup_url = full
        elif "田徑場" in filename:
            main_url = full
    return main_url, warmup_url


def extract_year_month(title):
    m = re.search(r"(\d+)年(\d+)月", title)
    if not m:
        return None, None
    return int(m.group(1)) + 1911, int(m.group(2))


def download_pdf(url):
    r = robust_get(url, timeout=60)
    return r.content


def parse_date_cell(cell, year, month):
    """Parse cells like '4/24\\n(五)' or '4/28 至 30\\n(二至四)' or '4/30 至 5/2'."""
    if not cell:
        return []
    text = re.sub(r"\s", "", cell)

    m = re.search(r"(\d+)/(\d+)(?:至|-|~)(\d+)/(\d+)", text)
    if m:
        mo1, d1, mo2, d2 = (int(m.group(i)) for i in range(1, 5))
        result = []
        if mo1 == mo2:
            return [date(year, mo1, d) for d in range(d1, d2 + 1)]
        last = calendar.monthrange(year, mo1)[1]
        for d in range(d1, last + 1):
            result.append(date(year, mo1, d))
        next_year = year + 1 if mo2 < mo1 else year
        for d in range(1, d2 + 1):
            result.append(date(next_year, mo2, d))
        return result

    m = re.search(r"(\d+)/(\d+)(?:至|-|~)(\d+)(?!/)", text)
    if m:
        mo, d1, d2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return [date(year, mo, d) for d in range(d1, d2 + 1)]

    m = re.search(r"(\d+)/(\d+)", text)
    if m:
        return [date(year, int(m.group(1)), int(m.group(2)))]

    return []


def parse_events(pdf_bytes, year, month):
    events = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    if not row or len(row) < 4:
                        continue
                    idx, name, date_cell, status_cell = row[0], row[1], row[2], row[3]
                    if not idx or not str(idx).strip().isdigit():
                        continue
                    events.append({
                        "name": (name or "").replace("\n", "").strip(),
                        "status": re.sub(r"\s+", " ", (status_cell or "").replace("\n", " ")).strip(),
                        "dates": parse_date_cell(date_cell, year, month),
                    })
    return events


def tuesdays_in_month(year, month):
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, d) for d in range(1, last + 1) if date(year, month, d).weekday() == 1]


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(title, year, month, events, news_url, is_updated=False):
    by_date = {}
    for e in events:
        for d in e["dates"]:
            by_date.setdefault(d, []).append(e)

    header = f"📅 <b>{year}年{month}月 臺北田徑場（主場）週二租借狀況</b>"
    if is_updated:
        header += " 🆕"
    lines = [header, ""]
    for t in tuesdays_in_month(year, month):
        label = f"{t.month}/{t.day}（二）"
        if t not in by_date:
            lines.append(f"✅ {label} 無活動，可練跑")
        else:
            lines.append(f"❌ {label} 有活動")
            for e in by_date[t]:
                lines.append(f"　• {html_escape(e['name'])}")
                lines.append(f"　　狀態：{html_escape(e['status'])}")
    lines.append("")
    lines.append(f"🔗 來源：{html_escape(news_url)}")
    lines.append(f"📄 {html_escape(title)}")
    return "\n".join(lines)


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; printing instead")
        print(text)
        return
    import time
    last_exc = None
    for attempt in range(3):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
                timeout=30,
            )
            if r.status_code == 200:
                return
            log(f"Telegram error: {r.status_code} {r.text} (attempt {attempt + 1}/3)")
            if 400 <= r.status_code < 500:
                # 4xx 是 client error（token / chat_id / message format 壞掉），retry 沒意義
                r.raise_for_status()
            last_exc = requests.HTTPError(f"Telegram {r.status_code}: {r.text}")
        except (requests.ConnectionError, requests.Timeout) as e:
            log(f"Telegram {type(e).__name__}: {e} (attempt {attempt + 1}/3)")
            last_exc = e
        if attempt < 2:
            time.sleep([2, 5][attempt])
    raise last_exc if last_exc else RuntimeError("send_telegram exhausted retries")


def main():
    force = "--force" in sys.argv[1:]
    if force:
        log("Force mode: 繞過同日去重邏輯與時段檢查")

    # 時段保險：擋掉 GHA 卡住舊排程在非預期時間觸發的情況
    # 預期觸發時段透過 EXPECTED_HOURS_TAIPEI 環境變數設定（"17,18" 表示只允許 17 或 18 點 Taipei）
    # 改時間時：改 yaml 的 cron 同時改這個 env var，就不會被 GHA 殘留排程亂觸發
    expected_hours_str = os.environ.get("EXPECTED_HOURS_TAIPEI", "").strip()
    if expected_hours_str and not force:
        try:
            expected_hours = [int(h.strip()) for h in expected_hours_str.split(",") if h.strip()]
        except ValueError:
            log(f"EXPECTED_HOURS_TAIPEI 格式錯誤 ({expected_hours_str!r})，略過時段檢查")
            expected_hours = []
        if expected_hours:
            taipei_hour = datetime.now(timezone(timedelta(hours=8))).hour
            if taipei_hour not in expected_hours:
                log(f"目前 Taipei 時間 {taipei_hour}:xx 不在預期時段 {expected_hours}；可能是 GHA 殘留舊排程，跳過。")
                return 0

    state = load_state()

    news_url, title = fetch_latest_news()
    if not news_url:
        log("No news entry found")
        return 1
    log(f"Latest news: {title}")
    log(f"Sub-page: {news_url}")

    main_pdf_url, warmup_url = fetch_pdf_urls(news_url)
    if not main_pdf_url:
        log("Main field PDF not found on sub-page")
        return 1
    log(f"Main PDF: {main_pdf_url}")

    is_updated = state.get("main_field_url") != main_pdf_url
    log(f"PDF updated: {is_updated}")

    # 今天已經對同一份 PDF 發過了就跳過（為了 17:00 + 18:00 雙 cron 備援設計）
    # workflow_dispatch 帶 --force 時繞過此檢查（過渡期 / 手動補發用）
    today_str = date.today().isoformat()
    if (not force
            and state.get("last_notify_date") == today_str
            and state.get("last_notified_pdf_url") == main_pdf_url):
        log(f"Already notified today ({today_str}) for the same PDF; skipping. Use --force to override.")
        return 0

    year, month = extract_year_month(title)
    if not year:
        log("Cannot parse year/month from title:", title)
        return 1

    pdf_bytes = download_pdf(main_pdf_url)
    events = parse_events(pdf_bytes, year, month)
    log(f"Parsed {len(events)} events")
    for e in events:
        log(" ", e["dates"], "|", e["name"], "|", e["status"])

    # Sanity check: 如果 PDF 有實質 table 但 parse 出 0 events,可能 PDF 結構變了。
    # 不直接發「整月可練跑」誤導訊息,改發警告讓使用者知道有問題。
    # 真的整月沒活動的場景極罕見;發誤導訊息害使用者白跑現場比較糟。
    if not events:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            substantive_tables = [
                t for page in pdf.pages
                for t in (page.extract_tables() or [])
                if t and len(t) > 1
            ]
        if substantive_tables:
            warn = (
                f"⚠️ tpstadium-bot 警告:\n"
                f"{year}年{month}月 PDF 偵測到 {len(substantive_tables)} 個 table、但 parse 出 0 個活動。\n"
                f"PDF 結構可能改了,需要人工檢查 check.py 的 parse_events / parse_date_cell。\n"
                f"PDF: {html_escape(main_pdf_url)}"
            )
            log("PDF parse 0 events but tables present — sending warning instead of misleading 'all clear'")
            send_telegram(warn)
            return 1

    msg = build_message(title, year, month, events, news_url, is_updated)
    log("--- message ---")
    log(msg)
    log("---")

    send_telegram(msg)

    state["main_field_url"] = main_pdf_url
    state["warmup_url"] = warmup_url
    state["last_title"] = title
    state["last_news_url"] = news_url
    state["last_notify_date"] = today_str
    state["last_notified_pdf_url"] = main_pdf_url
    save_state(state)
    log("State saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
