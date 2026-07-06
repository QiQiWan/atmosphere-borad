from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any, Dict

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def load_dotenv_files(paths: Iterable[Path] | None = None) -> None:
    candidates = list(paths or [
        ROOT_DIR / ".env",
        ROOT_DIR / ".env.local",
        BACKEND_DIR / ".env",
        BACKEND_DIR / ".env.local",
    ])
    for env_path in candidates:
        if not env_path.exists():
            continue
        with env_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = _strip_env_value(value)
                if key not in os.environ or os.environ.get(key, "") == "":
                    os.environ[key] = value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return default


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check and warm the server-side weather database cache before starting the web service."
    )
    parser.add_argument("--days", type=int, default=None, help="Recent natural days to cache before startup.")
    parser.add_argument("--start-time", default="", help="Explicit start time, e.g. 2026-06-20 00:00:00.")
    parser.add_argument("--end-time", default="", help="Explicit end time, e.g. 2026-07-03 23:59:59.")
    parser.add_argument("--force", action="store_true", help="Ignore existing coverage and rebuild the cache.")
    parser.add_argument("--skip", action="store_true", help="Skip the cache check and exit successfully.")
    parser.add_argument("--min-records", type=int, default=None, help="Minimum records required after cache check. Default comes from WEATHER_PRESTART_CACHE_MIN_RECORDS.")
    parser.add_argument("--strict", action="store_true", help="Exit with failure when the minimum record count is not met.")
    parser.add_argument("--no-scan", action="store_true", help="Do not print the day-by-day SQLite cache scan after warmup.")
    return parser


def _print_progress(event: Dict[str, Any]) -> None:
    phase = event.get("phase") or "running"
    page = event.get("page") or 0
    pages_fetched = event.get("pages_fetched") or 0
    records_collected = event.get("records_collected") or 0
    filtered_records = event.get("filtered_records") or 0
    stop_reason = event.get("stop_reason") or ""
    prefix = "[cache-checker]"
    if phase == "chunk_start":
        print(
            f"{prefix} chunk {event.get('chunk_index')}/{event.get('chunk_count')} "
            f"{event.get('chunk_start')} -> {event.get('chunk_end')} started; "
            f"total_raw={records_collected}",
            flush=True,
        )
    elif phase == "chunk_done":
        print(
            f"{prefix} chunk {event.get('chunk_index')}/{event.get('chunk_count')} done; "
            f"chunk_records={event.get('chunk_records', 0)}; total_raw={records_collected}; "
            f"range_records={filtered_records}; stop={stop_reason}",
            flush=True,
        )
    elif phase == "chunk_error":
        print(
            f"{prefix} chunk {event.get('chunk_index')}/{event.get('chunk_count')} failed: {event.get('error')}",
            file=sys.stderr,
            flush=True,
        )
    elif phase == "requesting":
        print(f"{prefix} requesting upstream page {page}...", flush=True)
    elif phase == "page_done":
        print(f"{prefix} page {page} done; pages={pages_fetched}; raw_records={records_collected}", flush=True)
    elif phase == "filter_done":
        print(f"{prefix} filtering done; pages={pages_fetched}; raw_records={records_collected}; range_records={filtered_records}; stop={stop_reason}", flush=True)
    elif phase == "saving":
        print(f"{prefix} saving to SQLite; pages={pages_fetched}; raw_records={records_collected}; range_records={filtered_records}; stop={stop_reason}", flush=True)


def main() -> int:
    load_dotenv_files()

    # Import only after .env files have been loaded.
    from data_service import (  # noqa: WPS433
        WeatherApiConfig,
        get_recent_prefetch_range,
        get_runtime_config_snapshot,
        prefetch_time_range,
        prefetch_time_range_chunked,
        print_cache_scan_report,
    )

    parser = _build_parser()
    args = parser.parse_args()

    enabled = _env_bool("WEATHER_PRESTART_CACHE_CHECK_ENABLED", True)
    if args.skip or not enabled:
        print("[cache-checker] skipped by configuration.", flush=True)
        return 0

    config = WeatherApiConfig()
    if not config.cache_enabled:
        print("[cache-checker] WEATHER_CACHE_ENABLED is false; cache check skipped.", flush=True)
        return 0
    if config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        print(f"[cache-checker] unsupported cache backend: {config.cache_backend}; cache check skipped.", flush=True)
        return 0
    if not config.secret_key:
        print("[cache-checker] ERROR: WEATHER_SECRET_KEY is empty. Cannot prefetch required data.", file=sys.stderr, flush=True)
        return 2

    if args.start_time and args.end_time:
        start_time, end_time = args.start_time, args.end_time
    else:
        days = args.days or _env_int("WEATHER_PRESTART_CACHE_CHECK_DAYS", config.startup_prefetch_days)
        start_time, end_time = get_recent_prefetch_range(days)

    force = bool(args.force or _env_bool("WEATHER_PRESTART_CACHE_CHECK_FORCE", config.startup_prefetch_force))
    min_records = args.min_records
    if min_records is None:
        min_records = _env_int("WEATHER_PRESTART_CACHE_MIN_RECORDS", 1)
    strict = bool(args.strict or _env_bool("WEATHER_PRESTART_CACHE_STRICT", True))

    print("[cache-checker] required cache range:", flush=True)
    print(f"[cache-checker]   start_time = {start_time}", flush=True)
    print(f"[cache-checker]   end_time   = {end_time}", flush=True)
    print(f"[cache-checker]   force      = {str(force).lower()}", flush=True)
    print(f"[cache-checker]   min_records= {min_records}", flush=True)
    print(f"[cache-checker]   strict     = {str(strict).lower()}", flush=True)
    snapshot = get_runtime_config_snapshot()
    print(f"[cache-checker]   db         = {snapshot.get('cache_db_path')}", flush=True)
    print(f"[cache-checker]   page_size  = {snapshot.get('upstream_page_size')}", flush=True)
    print(f"[cache-checker]   max_pages  = {snapshot.get('upstream_max_pages')}", flush=True)
    print(f"[cache-checker]   timeout    = {snapshot.get('timeout_seconds')}s", flush=True)
    print(f"[cache-checker]   proxy_env  = {snapshot.get('upstream_use_system_proxy')}", flush=True)
    print(f"[cache-checker]   split_days = {snapshot.get('prefetch_split_days')}", flush=True)
    print(f"[cache-checker]   chunk_days = {snapshot.get('prefetch_chunk_days')}", flush=True)

    started = time.time()
    try:
        if getattr(config, "prefetch_split_days", True):
            result = prefetch_time_range_chunked(start_time, end_time, force_refresh=force, progress_callback=_print_progress)
        else:
            result = prefetch_time_range(start_time, end_time, force_refresh=force, progress_callback=_print_progress)
    except Exception as exc:
        print(f"[cache-checker] ERROR: cache warmup failed: {exc}", file=sys.stderr, flush=True)
        return 3

    record_count = int(result.get("record_count") or 0)
    elapsed = time.time() - started
    source = result.get("source") or "unknown"
    message = result.get("message") or ""
    print(f"[cache-checker] completed; source={source}; records={record_count}; elapsed={elapsed:.1f}s", flush=True)
    if message:
        print(f"[cache-checker] message: {message}", flush=True)

    scan_enabled = _env_bool("WEATHER_PRESTART_CACHE_SCAN_ENABLED", True)
    if scan_enabled and not args.no_scan:
        try:
            print_cache_scan_report(start_time, end_time)
        except Exception as exc:
            print(f"[cache-checker] WARNING: cache scan failed: {exc}", file=sys.stderr, flush=True)

    if record_count < max(0, min_records):
        level = "ERROR" if strict else "WARNING"
        print(
            f"[cache-checker] {level}: cached record count {record_count} is lower than required minimum {min_records}.",
            file=sys.stderr,
            flush=True,
        )
        if strict:
            return 4
        print("[cache-checker] non-strict mode is enabled; web service will still start and the page will show the cache/upstream status.", flush=True)

    print(f"[cache-checker] ready at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}; web service can start.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
