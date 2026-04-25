import os, json, sys, subprocess, time, urllib.request, urllib.parse
from datetime import datetime

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
SCAN_JSON = os.path.join(BASE_DIR, "scan_results.json")

sys.path.insert(0, BASE_DIR)
from market_cache import get_macro, get_sectors, cache_age_str, start_background_refresh

def _load_env():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
_load_env()

TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID  = os.environ.get("TELEGRAM_CHAT_ID", "")
PORTFOLIO_INR = int(os.environ.get("PORTFOLIO_INR", "1000000"))

def api(method, params=None):
    url  = f"https://api.telegram.org/bot{TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    req  = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  API error ({method}): {e}")
        return {"ok": False}

def send(chat_id, text, parse_mode=None):
    params = {"chat_id": chat_id, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    if len(text) <= 4000:
        api("sendMessage", params)
        return
    lines  = text.split("\n")
    chunk  = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > 3900:
            api("sendMessage", {"chat_id": chat_id, "text": chunk})
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        api("sendMessage", {"chat_id": chat_id, "text": chunk})

def typing(chat_id):
    api("sendChatAction", {"chat_id": chat_id, "action": "typing"})

def load_scan():
    if not os.path.exists(SCAN_JSON):
        return None
    with open(SCAN_JSON) as f:
        return json.load(f)

def grade_emoji(g):
    return {"A+": "\U0001f3c6", "A": "\U0001f947", "B+": "\U0001f948", "B": "\U0001f949", "C": "\U0001f4cc"}.get(g, "\U0001f4cc")

def fmt_setup(r, detailed=False):
    emoji = grade_emoji(r["grade"])
    vcp   = " VCP" if r["is_vcp"] else ""
    lines = [
        f"{emoji} {r['ticker']} [{r['grade']}]{vcp}",
        f"  Rs{r['price']:.2f} -> Entry: Rs{r['entry']:.2f}",
        f"  Stop: Rs{r['stop']:.2f} | Target: Rs{r['target_2r']:.2f}",
        f"  Risk: {r['risk_pct']}% | R: {r['r_multiple']} | RS: {r['rs_rank']}",
    ]
    if detailed:
        lines += [
            f"  MA50: {r['ma50']:.0f} | MA200: {r['ma200']:.0f}",
            f"  TT: {r['tt_score']} | Vol: {r['volume_ratio']}x",
            f"  Position: Rs{r.get('position_inr', 0):,.0f}",
        ]
    return "\n".join(lines)

def handle_help(chat_id):
    send(chat_id,
        "SwingAI v2 -- Command Menu\n"
        "==========================\n\n"
        "DAILY BRIEF\n"
        "/brief    -- Full 4-section daily brief\n"
        "/macro    -- Live macro (Nifty, VIX, breadth)\n"
        "/sectors  -- Sector rotation (what's leading)\n"
        "/allocate -- Capital allocation (deploy %)\n\n"
        "SETUPS\n"
        "/top      -- Today's A and A+ setups\n"
        "/vcp      -- VCP patterns only\n"
        "/all      -- All setups (top 15)\n"
        "/stock RELIANCE -- Deep analysis on any stock\n\n"
        "PORTFOLIO\n"
        "/portfolio -- Position sizes\n"
        "/status   -- Last scan stats\n"
        "/scan     -- Trigger fresh scan now\n\n"
        "OR JUST TYPE:\n"
        "  'should I buy FEDERALBNK'\n"
        "  'what sectors should I focus on'\n"
        "  'how much should I invest today'\n\n"
        "Minervini SEPA -- Not financial advice"
    )

def handle_status(chat_id):
    data = load_scan()
    if not data:
        send(chat_id, "No scan data yet. Type /scan to run a fresh one.")
        return
    r = data.get("results", [])
    send(chat_id,
        f"SwingAI Status\n"
        f"==============\n"
        f"Last scan: {data.get('scan_date', '---')}\n"
        f"Universe:  {data.get('universe_size', '---')} stocks\n"
        f"Setups:    {len(r)}\n"
        f"A+: {sum(1 for x in r if x['grade']=='A+')}  "
        f"A: {sum(1 for x in r if x['grade']=='A')}  "
        f"B+: {sum(1 for x in r if x['grade']=='B+')}\n"
        f"VCP: {sum(1 for x in r if x['is_vcp'])}\n\n"
        f"Cache: {cache_age_str()}\n"
        f"Type /top to see best setups."
    )

def handle_top(chat_id):
    data = load_scan()
    if not data:
        send(chat_id, "No scan data. Type /scan to run one.")
        return
    top = [r for r in data.get("results", []) if r["grade"] in ("A+", "A")]
    if not top:
        send(chat_id, "No A/A+ setups today. Market not ideal -- stay patient.")
        return
    lines = [f"Top {len(top)} Setups -- {data.get('scan_date', '---')}\n"]
    for r in top[:6]:
        lines.append(fmt_setup(r))
        lines.append("")
    lines.append("Minervini SEPA -- Not financial advice")
    send(chat_id, "\n".join(lines))

def handle_vcp(chat_id):
    data = load_scan()
    if not data:
        send(chat_id, "No scan data. Type /scan to run one.")
        return
    vcps = [r for r in data.get("results", []) if r["is_vcp"]]
    if not vcps:
        send(chat_id, "No VCP patterns in last scan.")
        return
    lines = [f"VCP Patterns ({len(vcps)}) -- {data.get('scan_date', '---')}\n"]
    for r in vcps[:6]:
        lines.append(fmt_setup(r))
        lines.append("")
    send(chat_id, "\n".join(lines))

def handle_all(chat_id):
    data = load_scan()
    if not data:
        send(chat_id, "No scan data. Type /scan to run one.")
        return
    results = data.get("results", [])
    lines = [f"All Setups ({len(results)}) -- {data.get('scan_date', '---')}\n"]
    for r in results[:15]:
        vcp = " VCP" if r["is_vcp"] else ""
        lines.append(f"{grade_emoji(r['grade'])} {r['ticker']} [{r['grade']}]{vcp}  Rs{r['price']:.0f}  E:{r['entry']:.0f}  RS:{r['rs_rank']}")
    if len(results) > 15:
        lines.append(f"\n+{len(results)-15} more. Use /top for A/A+ only.")
    send(chat_id, "\n".join(lines))

def handle_portfolio(chat_id):
    data = load_scan()
    if not data:
        send(chat_id, "No scan data. Type /scan to run one.")
        return
    top = [r for r in data.get("results", []) if r["grade"] in ("A+", "A")][:5]
    if not top:
        send(chat_id, "No A/A+ setups to size positions for.")
        return
    lines = [f"Position Sizing (Rs{PORTFOLIO_INR:,.0f} portfolio)\n1% risk rule\n"]
    for r in top:
        pos = r.get("position_inr", 0)
        shares = r.get("shares", "---")
        lines.append(
            f"{grade_emoji(r['grade'])} {r['ticker']} [{r['grade']}]\n"
            f"  {shares} shares @ Rs{r['entry']:.2f} = Rs{pos:,.0f}\n"
            f"  Stop: Rs{r['stop']:.2f} | Risk: {r['risk_pct']}%\n"
        )
    lines.append("Stop out = 1% of portfolio. Stay disciplined.")
    send(chat_id, "\n".join(lines))

def handle_stock(chat_id, ticker):
    if not ticker:
        send(chat_id, "Usage: /stock RELIANCE")
        return
    ticker = ticker.upper().strip()
    data = load_scan()
    if data:
        match = next((r for r in data.get("results", []) if r["ticker"].upper() == ticker), None)
        if match:
            lines = [f"SEPA Analysis: {ticker} (from last scan {data.get('scan_date', '---')})\n"]
            lines.append(fmt_setup(match, detailed=True))
            lines.append(f"\nGrade: {match['grade']} | TT: {match['tt_score']}")
            if match["is_vcp"]:
                lines.append("VCP Pattern Confirmed")
            send(chat_id, "\n".join(lines))
            return
    send(chat_id, f"Analyzing {ticker} live... (15-30 seconds)")
    typing(chat_id)
    try:
        import yfinance as yf
        from screener import check_trend_template, detect_vcp, grade_setup, calculate_levels, flatten_df
        raw = yf.download(ticker + ".NS", period="2y", interval="1d", progress=False, auto_adjust=True)
        if raw is None or raw.empty or len(raw) < 100:
            send(chat_id, f"Not enough data for {ticker}. Check the ticker symbol (NSE only).")
            return
        df      = flatten_df(raw).dropna()
        current = float(df["Close"].squeeze().iloc[-1])
        passes, score, details = check_trend_template(df)
        is_vcp, tightness      = detect_vcp(df)
        vol_s   = df["Volume"].squeeze()
        vol_r   = round(float(vol_s.iloc[-1]) / float(vol_s.tail(20).mean()), 2)
        close_s = df["Close"].squeeze()
        n       = min(252, len(close_s))
        low52   = float(close_s.iloc[-n:].min())
        hi52    = float(close_s.iloc[-n:].max())
        rs      = int((current - low52) / (hi52 - low52) * 100) if hi52 > low52 else 50
        grade   = grade_setup(score, is_vcp, tightness, vol_r, rs)
        lvls    = calculate_levels(df, current)
        send(chat_id,
            f"SEPA Analysis: {ticker} (live)\n"
            f"Grade:    {grade}\n"
            f"TT Score: {score}/8\n"
            f"Price:    Rs{current:.2f}\n"
            f"Entry:    Rs{lvls['entry']:.2f}\n"
            f"Stop:     Rs{lvls['stop']:.2f}\n"
            f"Target 2R:Rs{lvls['target_2r']:.2f}\n"
            f"R-Multiple: {lvls['r_multiple']}R\n"
            f"Risk:     {lvls['risk_pct']}%\n"
            f"VCP:      {'YES' if is_vcp else 'No'}\n"
            f"RS Rank:  {rs}\n"
            f"Vol Ratio:{vol_r}x"
        )
    except Exception as e:
        send(chat_id, f"Error analyzing {ticker}: {str(e)[:100]}")

def handle_macro(chat_id):
    typing(chat_id)
    try:
        macro = get_macro()
        if not macro:
            send(chat_id, "Macro data unavailable. Try /scan to refresh.")
            return
        send(chat_id, macro.get("telegram_block", "No macro data.") + f"\n\nData: {cache_age_str()}")
    except Exception as e:
        send(chat_id, f"Macro error: {str(e)[:100]}")

def handle_sectors(chat_id):
    typing(chat_id)
    try:
        sectors = get_sectors()
        if not sectors:
            send(chat_id, "Sector data unavailable. Try /scan to refresh.")
            return
        send(chat_id, sectors.get("telegram_block", "No sector data.") + f"\n\nData: {cache_age_str()}")
    except Exception as e:
        send(chat_id, f"Sectors error: {str(e)[:100]}")

def handle_allocate(chat_id):
    typing(chat_id)
    try:
        from capital_allocation import get_capital_allocation
        macro   = get_macro()
        sectors = get_sectors()
        if not macro or not sectors:
            send(chat_id, "Market data not ready. Try again in 30 seconds.")
            return
        scan  = load_scan() or {"results": []}
        alloc = get_capital_allocation(macro, sectors, scan, portfolio_inr=PORTFOLIO_INR)
        send(chat_id, alloc["telegram_block"] + f"\n\nData: {cache_age_str()}")
    except Exception as e:
        send(chat_id, f"Allocation error: {str(e)[:100]}")

def handle_brief(chat_id):
    typing(chat_id)
    try:
        from capital_allocation import get_capital_allocation
        from notify import format_telegram
        macro   = get_macro()
        sectors = get_sectors()
        if not macro or not sectors:
            send(chat_id, "Market data not ready. Try again in 30 seconds.")
            return
        scan  = load_scan() or {"results": [], "scan_date": "---", "universe_size": 0}
        alloc = get_capital_allocation(macro, sectors, scan, portfolio_inr=PORTFOLIO_INR)
        msg   = format_telegram(scan, macro=macro, sectors=sectors, allocation=alloc)
        send(chat_id, msg + f"\n\nData: {cache_age_str()}")
    except Exception as e:
        send(chat_id, f"Brief error: {str(e)[:100]}")

def handle_scan(chat_id):
    send(chat_id, "Full scan triggered. Scanning 499 Nifty 500 stocks...\nThis takes 8-13 minutes. I'll message you when done.")
    try:
        import threading
        def _run():
            subprocess.run(
                [sys.executable, os.path.join(BASE_DIR, "run.py"), "--portfolio", str(PORTFOLIO_INR)],
                capture_output=True, text=True, timeout=900
            )
            data = load_scan()
            if data:
                r = data.get("results", [])
                send(chat_id,
                    f"Scan complete!\n"
                    f"Date: {data.get('scan_date', '---')}\n"
                    f"Setups: {len(r)} | A+:{sum(1 for x in r if x['grade']=='A+')} A:{sum(1 for x in r if x['grade']=='A')}\n\n"
                    f"Type /top to see best setups."
                )
        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        send(chat_id, f"Could not start scan: {e}")

def handle_natural_language(chat_id, text):
    t = text.lower()
    if any(w in t for w in ["market", "buy now", "good time", "nifty", "vix", "breadth"]):
        handle_macro(chat_id); return True
    if any(w in t for w in ["sector", "rotation", "leading", "lagging", "bank", "metal", "fmcg"]):
        handle_sectors(chat_id); return True
    if any(w in t for w in ["how much", "invest today", "deploy", "allocation", "capital", "cash"]):
        handle_allocate(chat_id); return True
    if any(w in t for w in ["vcp", "volatility contraction", "pattern"]):
        handle_vcp(chat_id); return True
    if any(w in t for w in ["setup", "best stock", "top stock", "which stock"]):
        handle_top(chat_id); return True
    words = text.upper().split()
    triggers = ["BUY", "SELL", "ABOUT", "ANALYSE", "ANALYZE", "CHECK"]
    for i, w in enumerate(words):
        if w in triggers and i + 1 < len(words):
            candidate = words[i + 1].replace("?", "").replace(",", "")
            if len(candidate) >= 3 and candidate.isalpha():
                handle_stock(chat_id, candidate); return True
    if any(w in t for w in ["brief", "report", "daily", "summary"]):
        handle_brief(chat_id); return True
    return False

def handle_message(msg):
    chat_id = msg.get("chat", {}).get("id")
    text    = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return
    if CHAT_ID and str(chat_id) != str(CHAT_ID):
        send(chat_id, "Unauthorized. This bot is private.")
        return
    cmd  = text.split()[0].lower()
    args = text.split()[1:] if len(text.split()) > 1 else []
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {chat_id}: {text[:60]}")
    if cmd in ("/start", "/help"):       handle_help(chat_id)
    elif cmd == "/brief":                handle_brief(chat_id)
    elif cmd == "/macro":                handle_macro(chat_id)
    elif cmd == "/sectors":              handle_sectors(chat_id)
    elif cmd == "/allocate":             handle_allocate(chat_id)
    elif cmd == "/top":                  handle_top(chat_id)
    elif cmd == "/vcp":                  handle_vcp(chat_id)
    elif cmd == "/all":                  handle_all(chat_id)
    elif cmd == "/stock":                handle_stock(chat_id, args[0] if args else "")
    elif cmd == "/portfolio":            handle_portfolio(chat_id)
    elif cmd == "/status":               handle_status(chat_id)
    elif cmd == "/scan":                 handle_scan(chat_id)
    elif text.startswith("/"):           send(chat_id, f"Unknown: {cmd}. Type /help.")
    else:
        if not handle_natural_language(chat_id, text):
            send(chat_id, "Type /help for all commands.")

def run_bot():
    if not TOKEN:
        print("Set TELEGRAM_TOKEN in .env"); return
    print(f"SwingAI Bot v2 -- Running | Portfolio: Rs{PORTFOLIO_INR:,.0f}")
    start_background_refresh()
    offset = 0
    while True:
        try:
            resp = api("getUpdates", {"offset": offset, "timeout": 20, "limit": 10})
            if resp.get("ok"):
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message") or update.get("edited_message")
                    if msg: handle_message(msg)
        except KeyboardInterrupt:
            print("\n  Bot stopped."); break
        except Exception as e:
            print(f"  Polling error: {e}"); time.sleep(5)

if __name__ == "__main__":
    run_bot()
