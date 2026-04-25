"""
SwingAI v2 - Notification Engine
Full 4-section daily brief via Telegram + Gmail
"""
import json, os, smtplib, urllib.request, urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
SCAN_JSON = os.path.join(BASE_DIR, "scan_results.json")

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

GMAIL_USER       = os.environ.get("GMAIL_USER", "")
GMAIL_PASS       = os.environ.get("GMAIL_PASS", "")
TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
RECIPIENTS       = [r.strip() for r in os.environ.get("RECIPIENTS", "").split(",") if r.strip()]

def load_scan():
    if not os.path.exists(SCAN_JSON):
        raise FileNotFoundError("scan_results.json not found.")
    with open(SCAN_JSON) as f:
        return json.load(f)

def format_telegram(data, macro=None, sectors=None, allocation=None):
    results = data.get("results", [])
    date    = data.get("scan_date", datetime.now().strftime("%Y-%m-%d"))
    aplus   = [r for r in results if r["grade"] == "A+"]
    a_grade = [r for r in results if r["grade"] == "A"]
    bplus   = [r for r in results if r["grade"] == "B+"]
    vcps    = [r for r in results if r["is_vcp"]]
    top     = aplus + a_grade

    lines = [f"SwingAI Daily Brief -- {date}", "Say What Data Says", "=" * 30, ""]

    if macro:
        n5 = macro.get("nifty500", {})
        n50 = macro.get("nifty50", {})
        vix = macro.get("vix", {})
        breadth = macro.get("breadth", {})
        chg_1d = n5.get("chg_1d")
        chg_str = f" ({'+' if chg_1d and chg_1d > 0 else ''}{chg_1d}%)" if chg_1d else ""
        lines += [
            "SECTION 1 -- MACRO VIEW",
            f"Market: {macro.get('macro_label','---')} ({macro.get('macro_score','---')}/100)",
            "-" * 28,
            f"Nifty 500: Rs{n5.get('price','---')}{chg_str}",
            f"Trend: {n5.get('stage','---')}",
            f"VIX: {vix.get('value','---')} -- {vix.get('signal','---')}",
            f"Breadth (above 200MA): {breadth.get('above_200_pct','---')}%",
            f"Signal: {breadth.get('signal','---')}", "",
        ]
    else:
        lines += ["SECTION 1 -- MACRO VIEW", "Data unavailable", ""]

    if sectors:
        def _arrow(val):
            if val is None: return "---"
            return f"{'+' if val>0 else ''}{val:.1f}%"
        lines += ["SECTION 2 -- SECTOR ROTATION", f"Rotation: {sectors.get('rotation_type','---')}", "-" * 28, "Top Sectors:"]
        for s in sectors.get("leaders", []):
            lines.append(f"  {s['sector']:<16} 1M:{_arrow(s.get('momentum_1m'))} 3M:{_arrow(s.get('momentum_3m'))}")
        lines += ["", "Bottom Sectors:"]
        for s in sectors.get("laggards", []):
            lines.append(f"  {s['sector']:<16} 1M:{_arrow(s.get('momentum_1m'))} 3M:{_arrow(s.get('momentum_3m'))}")
        lines += ["", f"Signal: {sectors.get('rotation_signal','---')}", ""]
    else:
        lines += ["SECTION 2 -- SECTOR ROTATION", "Data unavailable", ""]

    if allocation:
        gs = allocation.get("grade_sizing", {})
        lines += [
            "SECTION 3 -- CAPITAL ALLOCATION",
            f"Health: {allocation.get('health_score','---')}/100 -- {allocation.get('tier_label','---')}",
            "-" * 28,
            f"Deploy: Rs{allocation.get('deploy_inr',0):,.0f} ({allocation.get('deploy_pct',0)}%)",
            f"Cash:   Rs{allocation.get('cash_inr',0):,.0f} ({allocation.get('cash_pct',0)}%)",
            f"Max Pos: {allocation.get('max_positions','---')} | Risk/trade: Rs{allocation.get('risk_per_trade_inr',0):,.0f}",
            "Rules:",
        ] + [f"  {r}" for r in allocation.get("key_rules", [])] + [""]
    else:
        lines += ["SECTION 3 -- CAPITAL ALLOCATION", "Data unavailable", ""]

    lines += [
        "SECTION 4 -- STOCK SETUPS (MINERVINI SEPA)",
        f"Setups: {len(results)} | A+:{len(aplus)} A:{len(a_grade)} B+:{len(bplus)} VCP:{len(vcps)}",
        "-" * 28,
    ]
    if not top:
        lines.append("No A/A+ setups today. Stay patient.")
    else:
        for r in top[:6]:
            vcp = " [VCP]" if r["is_vcp"] else ""
            lines += [
                f"[{r['grade']}] {r['ticker']}{vcp}",
                f"  Rs{r['price']:.2f} -> Entry:Rs{r['entry']:.2f} Stop:Rs{r['stop']:.2f}",
                f"  Risk:{r['risk_pct']}% R:{r['r_multiple']} RS:{r['rs_rank']}", "",
            ]
    lines.append("Minervini SEPA -- Not financial advice")
    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3950] + "\n[truncated]"
    return msg

def send_telegram(data, macro=None, sectors=None, allocation=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("  Telegram not configured."); return False
    msg = format_telegram(data, macro=macro, sectors=sectors, allocation=allocation)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": msg}).encode()
    try:
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        if result.get("ok"):
            print("  Telegram sent"); return True
        print(f"  Telegram error: {result}"); return False
    except Exception as e:
        print(f"  Telegram failed: {e}"); return False

def send_email(data, macro=None, sectors=None, allocation=None):
    if not GMAIL_USER or not GMAIL_PASS:
        print("  Gmail not configured."); return False
    to_list = RECIPIENTS if RECIPIENTS else [GMAIL_USER]
    date    = data.get("scan_date", "today")
    n       = len(data.get("results", []))
    macro_label = macro.get("macro_label", "") if macro else ""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"SwingAI Daily Brief -- {date} | {macro_label} | {n} Setups"
    msg["From"]    = f"SwingAI <{GMAIL_USER}>"
    msg["To"]      = ", ".join(to_list)
    msg.attach(MIMEText(format_telegram(data, macro=macro, sectors=sectors, allocation=allocation), "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to_list, msg.as_string())
        print(f"  Email sent -> {', '.join(to_list)}"); return True
    except Exception as e:
        print(f"  Email error: {e}"); return False

def run_notifications(data=None, macro=None, sectors=None, allocation=None):
    if data is None:
        data = load_scan()
    print(f"  Sending Telegram brief...")
    send_telegram(data, macro=macro, sectors=sectors, allocation=allocation)
    print(f"  Sending email...")
    send_email(data, macro=macro, sectors=sectors, allocation=allocation)

if __name__ == "__main__":
    run_notifications()
