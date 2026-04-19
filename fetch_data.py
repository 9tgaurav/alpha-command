"""
Alpha Command — EOD Data Fetcher
=================================
Runs via GitHub Actions every weekday at 3:45 PM IST (10:15 UTC).
Pulls NSE closing data from yfinance, computes all indicators,
writes data.json that the HTML app reads.

Run locally:   python fetch_data.py
Run for test:  python fetch_data.py --tickers DIXON,INFY,HDFCBANK
"""

import yfinance as yf
import pandas as pd
import numpy as np
import json, os, sys, argparse, warnings
from datetime import datetime, timedelta
import urllib.request

warnings.filterwarnings("ignore")

# ── CONFIG ─────────────────────────────────────────────────────────────────────
OUTPUT_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
IST_OFFSET   = timedelta(hours=5, minutes=30)
TODAY_IST    = (datetime.utcnow() + IST_OFFSET).strftime("%Y-%m-%d")
NOW_IST      = (datetime.utcnow() + IST_OFFSET).strftime("%Y-%m-%d %H:%M IST")

# ── DEFAULT WATCHLIST ──────────────────────────────────────────────────────────
DEFAULT_WATCHLIST = [
    "DIXON", "PERSISTENT", "INFY", "PGEL", "HDFCBANK",
    "LLENTLTD", "KALYANKJIL", "MOTHERSON",
    # Broad market + sectors
    "TCS", "WIPRO", "HCLTECH", "LTIM", "COFORGE",
    "RELIANCE", "BAJFINANCE", "KOTAKBANK", "ICICIBANK", "AXISBANK",
    "HAL", "BEL", "MAZDOCK", "CDSL", "BSE",
]

# ── INDEX TICKERS ──────────────────────────────────────────────────────────────
INDEX_TICKERS = {
    "NIFTY 50":   "^NSEI",
    "SENSEX":     "^BSESN",
    "BANK NIFTY": "^NSEBANK",
    "NIFTY IT":   "^CNXIT",
    "INDIA VIX":  "^INDIAVIX",
    "NIFTY MID":  "NIFTYMIDCAP150.NS",
}

# ── SECTOR MAP ─────────────────────────────────────────────────────────────────
SECTOR_ETF_MAP = {
    "IT/Tech":    "NIFTYIT.NS",
    "Banking":    "BANKNIFTY.NS",
    "Pharma":     "NIFTYPHARMA.NS",
    "Auto":       "NIFTYAUTO.NS",
    "FMCG":       "NIFTYFMCG.NS",
    "Metals":     "NIFTYMETAL.NS",
    "Realty":     "NIFTYREALTY.NS",
    "Infra":      "NIFTYINFRA.NS",
    "Energy":     "NIFTYENERGY.NS",
    "Defence":    "MIDFSMALL400.NS",
    "Chemical":   "NIFTYCHEMICAL.NS",
    "Media":      "NIFTYMEDIA.NS",
}

# ── HELPERS ────────────────────────────────────────────────────────────────────

def ns(ticker: str) -> str:
    """Add .NS suffix for NSE if not present."""
    if ticker.endswith(".NS") or ticker.startswith("^"):
        return ticker
    return ticker + ".NS"


def safe_float(val, decimals=2):
    try:
        v = float(val)
        return round(v, decimals) if not (np.isnan(v) or np.isinf(v)) else None
    except Exception:
        return None


def pct_change(new, old):
    try:
        return round((new - old) / old * 100, 2)
    except Exception:
        return 0.0


def fetch_history(ticker_ns: str, period="1y"):
    """Download historical OHLCV. Returns DataFrame or None."""
    try:
        df = yf.download(ticker_ns, period=period, auto_adjust=True,
                         progress=False, threads=False)
        if df.empty:
            return None
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.dropna(subset=["Close"])
        return df
    except Exception as e:
        print(f"  ✗ {ticker_ns}: {e}")
        return None


def compute_indicators(df: pd.DataFrame) -> dict:
    """From a Close series, compute all indicators needed by the HTML app."""
    close = df["Close"]
    volume = df["Volume"] if "Volume" in df.columns else pd.Series(dtype=float)

    ltp        = safe_float(close.iloc[-1])
    prev_close = safe_float(close.iloc[-2]) if len(close) > 1 else ltp
    chg        = pct_change(ltp, prev_close) if prev_close else 0.0

    ma50  = safe_float(close.tail(50).mean())  if len(close) >= 50  else None
    ma150 = safe_float(close.tail(150).mean()) if len(close) >= 150 else None
    ma200 = safe_float(close.tail(200).mean()) if len(close) >= 200 else None

    # 200-DMA slope: compare current vs 20 sessions ago
    ma200_slope = None
    if len(close) >= 220:
        ma200_now  = close.tail(200).mean()
        ma200_prev = close.iloc[-220:-20].mean()
        ma200_slope = "up" if ma200_now > ma200_prev else "down"

    high52w = safe_float(close.tail(252).max()) if len(close) >= 30 else ltp
    low52w  = safe_float(close.tail(252).min()) if len(close) >= 30 else ltp

    # Relative Strength (price momentum vs Nifty, approximated as % above 52w low)
    pct_above_low  = pct_change(ltp, low52w)  if low52w  else 0
    pct_below_high = pct_change(high52w, ltp) / high52w * 100 if high52w else 100

    # Trend Template — 8 criteria
    tt_checks = {
        "price_above_200ma":  bool(ltp and ma200 and ltp > ma200),
        "ma200_slope_up":     ma200_slope == "up",
        "ma150_above_200":    bool(ma150 and ma200 and ma150 > ma200),
        "ma50_above_150_200": bool(ma50 and ma150 and ma200 and ma50 > ma150 and ma50 > ma200),
        "price_above_50ma":   bool(ltp and ma50 and ltp > ma50),
        "pct_25_above_low":   pct_above_low >= 25,
        "within_25_of_high":  bool(high52w and ltp >= high52w * 0.75),
        "rs_above_70":        None,   # filled after RS calculation
    }

    tt_score = sum(1 for k, v in tt_checks.items() if v is True and k != "rs_above_70")

    # Stage
    if tt_score >= 6 and tt_checks["price_above_200ma"]:
        stage = 2
    elif tt_checks["price_above_200ma"]:
        stage = 1
    else:
        stage = 3

    # Avg volume
    avg_vol_20 = safe_float(volume.tail(20).mean()) if len(volume) >= 20 else None
    vol_today  = safe_float(volume.iloc[-1])        if len(volume) >= 1  else None

    return {
        "ltp":         ltp,
        "prev_close":  prev_close,
        "chg":         chg,
        "ma50":        ma50,
        "ma150":       ma150,
        "ma200":       ma200,
        "ma200_slope": ma200_slope,
        "high52w":     high52w,
        "low52w":      low52w,
        "stage":       stage,
        "tt_score":    tt_score,
        "tt_checks":   {k: bool(v) if v is not None else False for k, v in tt_checks.items()},
        "avg_vol_20":  avg_vol_20,
        "vol_today":   vol_today,
        "pct_above_low":  round(pct_above_low, 1),
        "pct_below_high": round(pct_below_high, 1),
    }


def compute_rs_rank(stock_data: dict, all_changes: list) -> int:
    """Rank stock's 1-year return vs all stocks. Returns 0-99."""
    try:
        ticker_chg = stock_data.get("chg_1y", 0)
        rank = sum(1 for c in all_changes if ticker_chg > c)
        return int(rank / max(len(all_changes), 1) * 99)
    except Exception:
        return 50


def grade_setup(ind: dict, rs: int) -> str:
    tt = ind.get("tt_score", 0)
    if not ind["tt_checks"]["price_above_200ma"]:
        return "REJECT"
    if tt == 8 and rs >= 85:
        return "A+"
    if tt >= 7 and rs >= 75:
        return "A"
    if tt >= 6 and rs >= 65:
        return "B+"
    if tt >= 5:
        return "B"
    return "C"


def suggest_levels(ltp, ma50, stage, grade):
    """Simple pivot-based entry/stop/target for display."""
    if grade in ("REJECT", "C", "B") or not ltp:
        return None, None, None, None

    # Entry: slightly above current price (assumes at/near pivot)
    entry = round(ltp * 1.015, 1)
    # Stop: below 50-DMA or 8% below entry
    stop_ma  = round(ma50 * 0.99, 1) if ma50 else None
    stop_pct = round(entry * 0.92, 1)
    stop = stop_ma if (stop_ma and stop_ma > stop_pct) else stop_pct
    risk = entry - stop
    t1   = round(entry + 2 * risk, 1)   # 2R
    t2   = round(entry + 3 * risk, 1)   # 3R
    rr   = round(risk / entry * 100, 1) if entry else None
    return entry, stop, t1, rr


# ── FETCH INDICES ──────────────────────────────────────────────────────────────

def fetch_indices():
    print("\n📡 Fetching index data...")
    results = []
    for name, ticker in INDEX_TICKERS.items():
        df = fetch_history(ticker, period="5d")
        if df is None or len(df) < 2:
            results.append({"name": name, "value": None, "chg": None})
            continue
        close = df["Close"]
        val   = safe_float(close.iloc[-1])
        chg   = pct_change(close.iloc[-1], close.iloc[-2])
        color = "green" if chg and chg >= 0 else "red"
        if name == "INDIA VIX":
            color = "gold"
            chg   = -chg if chg else chg   # VIX down = good for market
        results.append({"name": name, "value": val, "chg": chg, "color": color})
        print(f"  ✓ {name}: {val}  ({'+' if chg and chg>=0 else ''}{chg}%)")
    return results


# ── FETCH SECTORS ──────────────────────────────────────────────────────────────

def fetch_sectors():
    print("\n🗺 Fetching sector data...")
    results = []
    for sec, etf in SECTOR_ETF_MAP.items():
        df = fetch_history(etf, period="5d")
        if df is None or len(df) < 2:
            # fallback: neutral
            results.append({"name": sec, "pct": "N/A", "type": "neutral", "chg": 0})
            continue
        close = df["Close"]
        chg   = pct_change(close.iloc[-1], close.iloc[-2])
        pct_str = f"{'+' if chg >= 0 else ''}{chg}%"
        stype = "hot" if chg >= 1.5 else "warm" if chg >= 0.2 else "neutral" if chg >= -0.3 else "cold"
        results.append({"name": sec, "pct": pct_str, "type": stype, "chg": chg})
        print(f"  ✓ {sec}: {pct_str}")
    return results


# ── FETCH WATCHLIST ────────────────────────────────────────────────────────────

def fetch_watchlist(tickers: list):
    print(f"\n📋 Fetching {len(tickers)} watchlist stocks...")
    raw = {}

    # Download all at once (faster)
    ticker_ns_list = [ns(t) for t in tickers]
    try:
        bulk = yf.download(
            " ".join(ticker_ns_list),
            period="1y",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as e:
        print(f"  Bulk download failed ({e}), falling back to individual...")
        bulk = None

    # Compute 1-year returns for RS ranking
    chg_1y_list = []

    for t in tickers:
        t_ns = ns(t)
        df   = None

        # Try extracting from bulk download
        if bulk is not None and not bulk.empty:
            try:
                if isinstance(bulk.columns, pd.MultiIndex):
                    if t_ns in bulk.columns.get_level_values(1):
                        df = bulk.xs(t_ns, axis=1, level=1).copy()
                    elif t in bulk.columns.get_level_values(1):
                        df = bulk.xs(t, axis=1, level=1).copy()
                else:
                    df = bulk.copy()
                if df is not None:
                    df = df.dropna(subset=["Close"]) if "Close" in df.columns else None
            except Exception:
                df = None

        # Fallback: individual download
        if df is None or (hasattr(df, "empty") and df.empty):
            df = fetch_history(t_ns, period="1y")

        if df is None or len(df) < 10:
            print(f"  ✗ {t}: insufficient data")
            continue

        ind = compute_indicators(df)
        # 1-year return
        chg_1y = pct_change(df["Close"].iloc[-1], df["Close"].iloc[0])
        ind["chg_1y"] = chg_1y
        raw[t] = {"ind": ind, "ticker": t}
        chg_1y_list.append(chg_1y)
        print(f"  ✓ {t}: ₹{ind['ltp']}  {'+' if ind['chg']>=0 else ''}{ind['chg']}%  Stage {ind['stage']}  TT {ind['tt_score']}/8")

    # Compute RS ranks now that we have all 1Y returns
    results = []
    for t, data in raw.items():
        ind = data["ind"]
        rs  = compute_rs_rank(ind, chg_1y_list)
        ind["rs"] = rs
        ind["tt_checks"]["rs_above_70"] = rs >= 70
        ind["tt_score"] = sum(1 for v in ind["tt_checks"].values() if v is True)
        grade = grade_setup(ind, rs)
        entry, stop, target, rr = suggest_levels(ind["ltp"], ind["ma50"], ind["stage"], grade)
        results.append({
            "ticker":    t,
            "name":      t,                # fallback; could enrich from NSE CSV
            "ltp":       ind["ltp"],
            "chg":       ind["chg"],
            "ma50":      ind["ma50"],
            "ma150":     ind["ma150"],
            "ma200":     ind["ma200"],
            "ma200_slope": ind["ma200_slope"],
            "high52w":   ind["high52w"],
            "low52w":    ind["low52w"],
            "rs":        rs,
            "stage":     ind["stage"],
            "tt":        ind["tt_score"],
            "tt_checks": ind["tt_checks"],
            "grade":     grade,
            "entry":     entry,
            "stop":      stop,
            "target":    target,
            "rr":        rr,
            "vol_today": ind["vol_today"],
            "avg_vol_20":ind["avg_vol_20"],
        })

    # Sort: A+ first, then by RS rank
    grade_order = {"A+": 0, "A": 1, "B+": 2, "B": 3, "C": 4, "REJECT": 5}
    results.sort(key=lambda x: (grade_order.get(x["grade"], 9), -(x["rs"] or 0)))
    return results


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated NSE tickers (no .NS). Default: full watchlist.")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE,
                        help="Output JSON file path.")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",")] \
              if args.tickers else DEFAULT_WATCHLIST

    print(f"\n{'='*60}")
    print(f"  Alpha Command — EOD Data Fetch")
    print(f"  Date  : {NOW_IST}")
    print(f"  Stocks: {len(tickers)}")
    print(f"  Output: {args.output}")
    print(f"{'='*60}")

    indices  = fetch_indices()
    sectors  = fetch_sectors()
    watchlist = fetch_watchlist(tickers)

    # Summary stats
    go_trades = [s for s in watchlist if s["grade"] in ("A+", "A")]
    watch_trades = [s for s in watchlist if s["grade"] == "B+"]
    reject_trades = [s for s in watchlist if s["grade"] in ("C", "REJECT")]

    # Top consensus picks (A+ or A grade, highest RS)
    top_picks = [s["ticker"] for s in go_trades[:5]]

    # Market regime from Nifty 200-DMA
    nifty_chg  = next((i["chg"] for i in indices if i["name"]=="NIFTY 50"), 0)
    vix_val    = next((i["value"] for i in indices if i["name"]=="INDIA VIX"), 15)
    regime = "BULLISH" if (nifty_chg and nifty_chg > 0 and (vix_val or 20) < 20) \
             else "CAUTION" if (vix_val or 20) > 20 \
             else "SIDEWAYS"

    payload = {
        "meta": {
            "fetch_date":   TODAY_IST,
            "fetch_time":   NOW_IST,
            "data_source":  "Yahoo Finance (yfinance)",
            "is_live":      False,
            "market_close": "15:30 IST",
            "note":         "EOD data — closing prices after 3:30 PM IST",
            "regime":       regime,
            "top_picks":    top_picks,
            "go_count":     len(go_trades),
            "watch_count":  len(watch_trades),
            "reject_count": len(reject_trades),
        },
        "indices":    indices,
        "sectors":    sectors,
        "watchlist":  watchlist,
    }

    with open(args.output, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"  ✅ data.json written — {len(watchlist)} stocks")
    print(f"  GO trades   : {len(go_trades)}")
    print(f"  WATCH trades: {len(watch_trades)}")
    print(f"  Rejected    : {len(reject_trades)}")
    print(f"  Market regime: {regime}")
    print(f"  Top picks   : {', '.join(top_picks)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
