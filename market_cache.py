"""
SwingAI - Market Data Cache
Solves Telegram speed: /macro /sectors /allocate /brief now < 2 sec (was 30-120 sec).
Cache TTL: 4 hours. Auto-refreshes in background thread.
"""
import os, json, time
from datetime import datetime, timedelta

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(BASE_DIR, "market_cache.json")
CACHE_TTL_HOURS = int(os.environ.get("CACHE_TTL_HOURS", "4"))

def _load_cache():
    if not os.path.exists(CACHE_FILE): return {}
    try:
        with open(CACHE_FILE) as f: return json.load(f)
    except: return {}

def _save_cache(data):
    data["_cached_at"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f: json.dump(data, f, indent=2, default=str)

def _is_stale():
    cached_at = _load_cache().get("_cached_at")
    if not cached_at: return True
    try: return datetime.now() - datetime.fromisoformat(cached_at) > timedelta(hours=CACHE_TTL_HOURS)
    except: return True

def cache_age_str():
    cached_at = _load_cache().get("_cached_at")
    if not cached_at: return "never"
    try:
        mins = int((datetime.now() - datetime.fromisoformat(cached_at)).total_seconds() / 60)
        return f"{mins}m ago" if mins < 60 else f"{mins//60}h {mins%60}m ago"
    except: return "unknown"

_refreshing = False

def refresh_cache(force=False):
    global _refreshing
    if _refreshing: return False
    if not force and not _is_stale(): return True
    _refreshing = True
    try:
        import sys; sys.path.insert(0, BASE_DIR)
        from macro_view import get_macro_view
        from sector_rotation import get_sector_rotation
        _save_cache({"macro": get_macro_view(), "sectors": get_sector_rotation()})
        print(f"  [Cache] Updated at {datetime.now().strftime('%H:%M:%S')}")
        return True
    except Exception as e:
        print(f"  [Cache] Refresh failed: {e}"); return False
    finally: _refreshing = False

def get_macro():
    if _is_stale(): refresh_cache()
    return _load_cache().get("macro", {})

def get_sectors():
    if _is_stale(): refresh_cache()
    return _load_cache().get("sectors", {})

def start_background_refresh():
    import threading
    def _loop():
        if _is_stale(): refresh_cache()
        while True:
            time.sleep(CACHE_TTL_HOURS * 3600)
            refresh_cache(force=True)
    threading.Thread(target=_loop, daemon=True, name="CacheRefresh").start()
    print(f"  [Cache] Background refresh started (every {CACHE_TTL_HOURS}h)")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    if args.status: print(f"Age: {cache_age_str()} | {'STALE' if _is_stale() else 'FRESH'}")
    elif args.refresh: refresh_cache(force=True); print("Done.")
