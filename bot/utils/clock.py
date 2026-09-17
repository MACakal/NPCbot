import time
from datetime import datetime, timezone


def now_ts() -> int:
    """Current Unix time in seconds (true UTC epoch)."""
    return int(time.time())


def utc_day(ts: int) -> str:
    """Calendar day (UTC) a timestamp falls on, e.g. '2026-09-17'."""
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')


def format_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def format_duration(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m {secs}s"
