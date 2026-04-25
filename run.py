"""
SwingAI — Master Pipeline v2
Full daily brief: Macro + Sectors + Capital Allocation + Stock Setups

Usage:
  python run.py                        # full scan + notify
  python run.py --dry-run              # scan only, no notifications
  python run.py --notify-only          # send last results without re-scanning
  python run.py --portfolio 5000000    # ₹50L portfolio sizing
  python run.py --workers 25           # more parallel threads
  python run.py --tickers R.NS,TCS.NS  # custom ticker list

Schedule (crontab -e):
  # Weekdays 9:05 AM IST = 3:35 AM UTC
  35 3 * * 1-5 cd /path/to/SwingAI && python run.py >> logs/run.log 2>&1
"""

import argparse, json, os, sys, time
from datetime import datetime

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
SCAN_JSON = os.path.join(BASE_DIR, "scan_results.json")
LOG_DIR   = os.path.join(BASE_DIR, "logs")

# ── Auto-load .env ────────────────────────────────────────────────────────────
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


def _banner(text, width=65):
    print(f"\n{'─'*width}")
    print(f"  {text}")
    print(f"{'─'*width}")


def main():
    parser = argparse.ArgumentParser(description="SwingAI Master Pipeline v2")
    parser.add_argument("--portfolio",   type=int,   default=1_000_000)
    parser.add_argument("--workers",     type=int,   default=20)
    parser.add_argument("--dry-run",     action="store_true")
    parser.add_argument("--notify-only", action="store_true")
    parser.add_argument("--tickers",     type=str,   default=None)
    args = parser.parse_args()

    t0    = time.time()
    now   = datetime.now().strftime("%Y-%m-%d %H:%M")
    mode  = ("Dry Run" if args.dry_run else
             "Notify Only" if args.notify_only else "Full Pipeline")

    print(f"""
╔═══════════════════════════════════════════════════════════╗
║        SwingAI v2 — Complete Trading Advisory System          ║
║        Macro · Sectors · Allocation · SEPA Setups             ║
║        {now}                                        ║
╠═══════════════════════════════════════════════════════════════╣
║  Portfolio : ₹{args.portfolio:>12,.0f}                                 ║
║  Mode      : {mode:<50}║
╚═══════════════════════════════════════════════════════════════╝
""")

    sys.path.insert(0, BASE_DIR)

    # ── STEP 1: MACRO VIEW ───────────────────────────────────────────────────
    _banner("Step 1/4 — Macro Market View")
    macro = {}
    try:
        from macro_view import get_macro_view
        macro = get_macro_view()
        print(f"  ✓ Macro score: {macro.get('macro_score', '—')}/100 — {macro.get('macro_label', '—')}")
    except Exception as e:
        print(f"  ✗ Macro view failed: {e}")
        macro = {"macro_score": 50, "macro_label": "Neutral", "vix": {}, "breadth": {}, "nifty500": {}, "nifty50": {}}

    # ── STEP 2: SECTOR ROTATION ──────────────────────────────────────────────
    _banner("Step 2/4 — Sector Rotation")
    sectors = {}
    try:
        from sector_rotation import get_sector_rotation
        sectors = get_sector_rotation()
        print(f"  ✓ Rotation: {sectors.get('rotation_type', '—')} | Leaders: {[s['sector'] for s in sectors.get('leaders', [])]}")
    except Exception as e:
        print(f"  ✗ Sector rotation failed: {e}")
        sectors = {"rotation_type": "Mixed", "rotation_signal": "—", "leaders": [], "laggards": [], "sectors": []}

    # ── STEP 3: STOCK SCAN ───────────────────────────────────────────────────
    _banner("Step 3/4 — Stock Screener (Nifty 500)")
    if not args.notify_only:
        from screener import run_screener
        tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
        scan_data = run_screener(tickers=tickers, portfolio_inr=args.portfolio, workers=args.workers)
    else:
        print("  Loading last scan (--notify-only)...")
        if not os.path.exists(SCAN_JSON):
            print("  ✗ scan_results.json not found. Run without --notify-only first.")
            sys.exit(1)
        with open(SCAN_JSON) as f:
            scan_data = json.load(f)
        print(f"  ✓ Loaded {len(scan_data.get('results', []))} setups from {scan_data.get('scan_date', '?')}")

    results = scan_data.get("results", [])
    aplus   = [r for r in results if r["grade"] == "A+"]
    a_grade = [r for r in results if r["grade"] == "A"]
    bplus   = [r for r in results if r["grade"] == "B+"]
    vcps    = [r for r in results if r["is_vcp"]]

    print(f"  ✓ Setups: {len(results)} total | A+:{len(aplus)} A:{len(a_grade)} B+:{len(bplus)} VCP:{len(vcps)}")

    # ── STEP 4: CAPITAL ALLOCATION ───────────────────────────────────────────
    _banner("Step 4/4 — Capital Allocation")
    allocation = {}
    try:
        from capital_allocation import get_capital_allocation
        allocation = get_capital_allocation(macro, sectors, scan_data, portfolio_inr=args.portfolio)
        print(f"  ✓ Deploy: {allocation.get('deploy_pct', '—')}% (₹{allocation.get('deploy_inr', 0):,.0f}) | Cash: {allocation.get('cash_pct', '—')}%")
        print(f"  ✓ Max positions: {allocation.get('max_positions', '—')} | Risk/trade: ₹{allocation.get('risk_per_trade_inr', 0):,.0f}")
    except Exception as e:
        print(f"  ✗ Capital allocation failed: {e}")
        allocation = {}

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    _banner("📊 DAILY BRIEF SUMMARY")
    print(f"""
  Market   : {macro.get('macro_label', '—')} (Score: {macro.get('macro_score', '—')}/100)
  Sectors  : {sectors.get('rotation_type', '—')} rotation
  Setups   : {len(results)} total | {len(aplus)} A+ | {len(a_grade)} A | {len(vcps)} VCP
  Deploy   : {allocation.get('deploy_pct', '—')}% | Cash: {allocation.get('cash_pct', '—')}%
  Max Pos  : {allocation.get('max_positions', '—')} | ₹{allocation.get('max_position_size_inr', 0):,.0f} each
""")

    # ── SAVE LOG ──────────────────────────────────────────────────────────────
    os.makedirs(LOG_DIR, exist_ok=True)
    scan_date = scan_data.get("scan_date", "today")
    log_path  = os.path.join(LOG_DIR, f"run_{scan_date}.json")
    with open(log_path, "w") as f:
        json.dump({
            "run_at":       now,
            "mode":         mode,
            "portfolio_inr":args.portfolio,
            "macro_score":  macro.get("macro_score"),
            "macro_label":  macro.get("macro_label"),
            "rotation":     sectors.get("rotation_type"),
            "scan_date":    scan_date,
            "universe":     scan_data.get("universe_size"),
            "total_setups": len(results),
            "aplus":        len(aplus),
            "a_grade":      len(a_grade),
            "bplus":        len(bplus),
            "vcps":         len(vcps),
            "deploy_pct":   allocation.get("deploy_pct"),
            "top_10":       [f"{r['ticker']} [{r['grade']}]" for r in results[:10]],
        }, f, indent=2)
    print(f"  ✓ Log saved: logs/run_{scan_date}.json")

    # ── NOTIFY ───────────────────────────────────────────────────────────────
    if not args.dry_run:
        print(f"\n{'─'*65}")
        print("  Sending notifications...")
        from notify import run_notifications
        run_notifications(data=scan_data, macro=macro, sectors=sectors, allocation=allocation)
    else:
        print("\n  Notifications skipped (--dry-run). Open dashboard.html to view results.")

    elapsed = round(time.time() - t0, 1)
    _banner(f"✅  Complete in {elapsed}s")


if __name__ == "__main__":
    main()
