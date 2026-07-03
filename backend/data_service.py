"""Weather data access layer with upstream fallback and stable response schema."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import requests

APP_VERSION = "1.7.7"


class UpstreamError(RuntimeError):
    """Raised when the upstream weather service cannot return usable data."""


def _env_value(*names: str, default: str = "") -> str:
    placeholders = {"请填写真实密钥", "你的真实密钥", "<你的真实密钥>", "your_secret_key", "your-secret-key"}
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            cleaned = value.strip().strip('"').strip("'")
            if cleaned in placeholders:
                continue
            return cleaned
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


@dataclass(frozen=True)
class WeatherApiConfig:
    base_url: str = field(
        default_factory=lambda: _env_value(
            "WEATHER_API_BASE_URL",
            "VITE_PROXY_DOMAIN_REAL",
            default="http://weather-api.jsjldzkj.com/api",
        )
    )
    appid: str = field(default_factory=lambda: _env_value("WEATHER_APP_ID", "WEATHER_APPID", "APPID", default="dashboard"))
    secret_key: str = field(default_factory=lambda: _env_value("WEATHER_SECRET_KEY", "WEATHER_SECRET", "SECRET_KEY"))
    timeout_seconds: float = field(default_factory=lambda: _env_float("WEATHER_TIMEOUT_SECONDS", 30.0))
    allow_mock: bool = field(default_factory=lambda: _env_bool("WEATHER_ALLOW_MOCK", False))
    force_mock: bool = field(default_factory=lambda: _env_bool("WEATHER_FORCE_MOCK", False))
    hmac_mode: str = field(default_factory=lambda: _env_value("WEATHER_HMAC_MODE", default="json"))
    cache_enabled: bool = field(default_factory=lambda: _env_bool("WEATHER_CACHE_ENABLED", True))
    cache_backend: str = field(default_factory=lambda: _env_value("WEATHER_CACHE_BACKEND", default="sqlite"))
    cache_db_path: str = field(
        default_factory=lambda: _env_value(
            "WEATHER_CACHE_DB",
            "WEATHER_CACHE_SQLITE_PATH",
            default="runtime_cache/weather_cache.sqlite3",
        )
    )
    cache_table: str = field(default_factory=lambda: _env_value("WEATHER_CACHE_TABLE", default="weather_cache_v174"))
    cache_max_age_seconds: float = field(default_factory=lambda: _env_float("WEATHER_CACHE_MAX_AGE_SECONDS", 0.0))
    upstream_page_size: int = field(default_factory=lambda: max(1, min(_env_int("WEATHER_UPSTREAM_PAGE_SIZE", 500), 5000)))
    upstream_max_pages: int = field(default_factory=lambda: max(1, _env_int("WEATHER_UPSTREAM_MAX_PAGES", 160)))
    upstream_max_records: int = field(default_factory=lambda: max(100, _env_int("WEATHER_UPSTREAM_MAX_RECORDS", 300000)))
    upstream_trust_total_hint: bool = field(default_factory=lambda: _env_bool("WEATHER_UPSTREAM_TRUST_TOTAL_HINT", False))
    upstream_time_format: str = field(default_factory=lambda: _env_value("WEATHER_UPSTREAM_TIME_FORMAT", default="auto"))
    prefetch_split_days: bool = field(default_factory=lambda: _env_bool("WEATHER_PREFETCH_SPLIT_DAYS", True))
    prefetch_chunk_days: int = field(default_factory=lambda: max(1, _env_int("WEATHER_PREFETCH_CHUNK_DAYS", 1)))
    prefetch_force_blocking: bool = field(default_factory=lambda: _env_bool("WEATHER_PRESTART_BLOCKING", True))
    startup_prefetch_enabled: bool = field(default_factory=lambda: _env_bool("WEATHER_STARTUP_PREFETCH_ENABLED", False))
    startup_prefetch_days: int = field(default_factory=lambda: max(1, _env_int("WEATHER_STARTUP_PREFETCH_DAYS", 30)))
    startup_prefetch_force: bool = field(default_factory=lambda: _env_bool("WEATHER_STARTUP_PREFETCH_FORCE", False))
    query_async_prefetch_on_miss: bool = field(default_factory=lambda: _env_bool("WEATHER_QUERY_ASYNC_PREFETCH_ON_MISS", True))


def get_runtime_config_snapshot() -> Dict[str, Any]:
    config = WeatherApiConfig()
    return {
        "base_url": config.base_url,
        "appid": config.appid,
        "has_secret_key": bool(config.secret_key),
        "timeout_seconds": config.timeout_seconds,
        "allow_mock": False,
        "force_mock": config.force_mock,
        "mock_disabled": True,
        "hmac_mode": config.hmac_mode,
        "cache_enabled": config.cache_enabled,
        "cache_backend": config.cache_backend,
        "cache_db_path": config.cache_db_path,
        "cache_table": config.cache_table,
        "cache_max_age_seconds": config.cache_max_age_seconds,
        "upstream_page_size": config.upstream_page_size,
        "upstream_max_pages": config.upstream_max_pages,
        "upstream_max_records": config.upstream_max_records,
        "upstream_trust_total_hint": config.upstream_trust_total_hint,
        "upstream_time_format": config.upstream_time_format,
        "prefetch_split_days": config.prefetch_split_days,
        "prefetch_chunk_days": config.prefetch_chunk_days,
        "prestart_blocking": config.prefetch_force_blocking,
        "app_version": APP_VERSION,
        "startup_prefetch_enabled": config.startup_prefetch_enabled,
        "startup_prefetch_days": config.startup_prefetch_days,
        "startup_prefetch_force": config.startup_prefetch_force,
        "query_async_prefetch_on_miss": config.query_async_prefetch_on_miss,
        "async_cache_on_miss": True,
        "prefetch_progress_enabled": True,
        "env_hint": "Loaded from root .env/.env.local and backend .env/.env.local if present.",
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _signature_payload(appid: str, timestamp: str, mode: str) -> str:
    """Build signature payload.

    The original repository signs the compact JSON string
    {"appid":"dashboard","timestamp":"<13位毫秒时间戳>"}.
    The concat mode is retained only for compatibility with other deployments.
    """

    if mode.lower() == "concat":
        return f"{appid}{timestamp}"
    return '{"appid":"%s","timestamp":"%s"}' % (appid, timestamp)


def build_headers(config: WeatherApiConfig) -> Dict[str, str]:
    if not config.secret_key:
        raise UpstreamError("WEATHER_SECRET_KEY is empty; real upstream requests are disabled.")

    timestamp = str(_now_ms())
    payload = _signature_payload(config.appid, timestamp, config.hmac_mode)
    authorization = hmac.new(
        config.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    # Keep the upstream request headers consistent with the original repository.
    # The upstream service used by this project accepts Authorization + timestamp;
    # adding extra custom headers is unnecessary and can make debugging harder.
    return {
        "Authorization": authorization,
        "timestamp": timestamp,
    }


def _parse_time(value: Any, fallback: datetime) -> datetime:
    if value in (None, "", "null"):
        return fallback
    text = str(value).strip()
    try:
        numeric = int(float(text))
        if numeric > 10_000_000_000:
            return datetime.fromtimestamp(numeric / 1000, tz=timezone.utc).replace(tzinfo=None)
        return datetime.fromtimestamp(numeric, tz=timezone.utc).replace(tzinfo=None)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return fallback


def _num_from_any(item: Dict[str, Any], keys: List[str], default: float = 0.0) -> float:
    for key in keys:
        value = item.get(key)
        if value in (None, ""):
            continue
        try:
            return round(float(value), 3)
        except (TypeError, ValueError):
            continue
    return default


def _text_from_any(item: Dict[str, Any], keys: List[str], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _normalise_record(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _text_from_any(item, ["id", "device_id", "create_time", "time", "created_at"]),
        "create_time": _text_from_any(item, ["create_time", "time", "created_at", "collection_time"]),
        "wendu": _num_from_any(item, ["wendu", "temperature", "temp"]),
        "shidu": _num_from_any(item, ["shidu", "humidity", "rh"]),
        "jiebin": _num_from_any(item, ["jiebin", "jiebing", "ice", "icing"]),
        "shuimo": _num_from_any(item, ["shuimo", "waterfilm", "water_film"]),
        "jixue": _num_from_any(item, ["jixue", "snow", "snow_cover"]),
        "fengsu": _num_from_any(item, ["fengsu", "wind_speed"]),
        "fengxiang": _num_from_any(item, ["fengxiang", "wind_direction"]),
        "pm25": _num_from_any(item, ["pm25", "pm2_5", "pm2.5"]),
        "pm10": _num_from_any(item, ["pm10"]),
        "yuliang": _num_from_any(item, ["yuliang", "rainfall", "rain"]),
        "yuqiang": _num_from_any(item, ["yuqiang", "rain_intensity"]),
        "nengjiandu": _num_from_any(item, ["nengjiandu", "visibility"]),
        "guangqiang": _num_from_any(item, ["guangqiang", "light", "illumination"]),
        "dianliu": _num_from_any(item, ["dianliu", "current"]),
        "dianya": _num_from_any(item, ["dianya", "voltage"]),
        "guangdian": _num_from_any(item, ["guangdian", "photovoltaic", "solar_power"]),
        "fengdian": _num_from_any(item, ["fengdian", "wind_power"]),
        "yadian": _num_from_any(item, ["yadian", "piezoelectric", "piezo_power"]),
    }


def normalise_payload(payload: Dict[str, Any], page: int, page_size: int) -> Dict[str, Any]:
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, dict):
        raw_list = result.get("list") or result.get("data") or []
        total = result.get("total") or result.get("count") or len(raw_list)
    else:
        raw_list = payload.get("list") or payload.get("data") or [] if isinstance(payload, dict) else []
        total = len(raw_list)

    if not isinstance(raw_list, list):
        raise UpstreamError("Upstream response does not contain a usable result.list array.")

    records = [_normalise_record(item) for item in raw_list if isinstance(item, dict)]
    records.sort(key=lambda record: str(record.get("create_time", "")))
    return {
        "code": int(payload.get("code", 0)) if isinstance(payload, dict) else 0,
        "message": payload.get("message", "ok") if isinstance(payload, dict) else "ok",
        "source": "upstream",
        "mock": False,
        "config": get_runtime_config_snapshot(),
        "result": {
            "list": records,
            "total": total,
            "page": page,
            "page_size": page_size,
        },
    }


PROJECT_ROOT = Path(__file__).resolve().parents[1]


_PREFETCH_LOCK = threading.RLock()
_PREFETCH_THREAD: threading.Thread | None = None
_PREFETCH_STATE: Dict[str, Any] = {
    "status": "idle",
    "running": False,
    "message": "尚未开始缓存任务",
    "progress_percent": 0,
    "start_time": "",
    "end_time": "",
    "force_refresh": False,
    "source": "",
    "pages_fetched": 0,
    "current_page": 0,
    "records_collected": 0,
    "filtered_records": 0,
    "upstream_page_size": 0,
    "upstream_max_pages": 0,
    "stop_reason": "",
    "error": "",
    "started_at_ms": 0,
    "updated_at_ms": 0,
    "finished_at_ms": 0,
    "elapsed_ms": 0,
}


def _copy_prefetch_state() -> Dict[str, Any]:
    with _PREFETCH_LOCK:
        state = dict(_PREFETCH_STATE)
    for key in ("started_at_ms", "updated_at_ms", "finished_at_ms"):
        value = state.get(key)
        if value:
            state[f"{key[:-3]}_text"] = datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    if state.get("running") and state.get("started_at_ms"):
        state["elapsed_ms"] = int(time.time() * 1000) - int(state.get("started_at_ms") or 0)
    return state


def get_prefetch_progress() -> Dict[str, Any]:
    return _copy_prefetch_state()


def _set_prefetch_state(**kwargs: Any) -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    with _PREFETCH_LOCK:
        _PREFETCH_STATE.update(kwargs)
        _PREFETCH_STATE["updated_at_ms"] = now_ms
        if _PREFETCH_STATE.get("started_at_ms"):
            _PREFETCH_STATE["elapsed_ms"] = now_ms - int(_PREFETCH_STATE.get("started_at_ms") or now_ms)
        return dict(_PREFETCH_STATE)


def _estimate_fetch_progress(start_ms: int, end_ms: int, oldest_seen_ms: int | None, pages_fetched: int, max_pages: int) -> int:
    page_progress = min(95.0, (max(0, pages_fetched) / max(1, max_pages)) * 90.0)
    if oldest_seen_ms is None or end_ms <= start_ms:
        return int(max(1.0 if pages_fetched else 0.0, page_progress))
    # Upstream returns newer pages first. The progress is estimated by how far
    # the oldest observed record has moved backward from the end time toward the
    # requested start time. Keep a page-count fallback because device sampling can
    # be sparse or irregular.
    coverage_progress = ((end_ms - oldest_seen_ms) / max(1, end_ms - start_ms)) * 100.0
    return int(max(page_progress, min(98.0, max(0.0, coverage_progress))))


def _make_prefetch_progress_callback(start_ms: int, end_ms: int, config: WeatherApiConfig) -> Callable[[Dict[str, Any]], None]:
    oldest_seen: int | None = None

    def callback(event: Dict[str, Any]) -> None:
        nonlocal oldest_seen
        phase = event.get("phase") or "running"
        page_min = event.get("page_min_time_ms")
        if page_min is not None:
            oldest_seen = page_min if oldest_seen is None else min(oldest_seen, int(page_min))
        pages_fetched = int(event.get("pages_fetched") or 0)
        progress = _estimate_fetch_progress(start_ms, end_ms, oldest_seen, pages_fetched, config.upstream_max_pages)
        message = "正在请求第三方接口并写入服务器数据库缓存"
        if phase == "requesting":
            message = f"正在请求第 {event.get('page')} 页第三方数据"
        elif phase == "page_done":
            message = f"已缓存检查第 {event.get('page')} 页，累计 {event.get('records_collected', 0)} 条原始记录"
        elif phase == "saving":
            progress = max(progress, 98)
            message = "远程数据已拉取完成，正在写入 SQLite 数据库"
        _set_prefetch_state(
            status="running",
            running=True,
            message=message,
            progress_percent=progress,
            current_page=int(event.get("page") or 0),
            pages_fetched=pages_fetched,
            records_collected=int(event.get("records_collected") or 0),
            filtered_records=int(event.get("filtered_records") or 0),
            upstream_page_size=config.upstream_page_size,
            upstream_max_pages=config.upstream_max_pages,
            stop_reason=str(event.get("stop_reason") or ""),
        )

    return callback


def _prefetch_range_key(start_time: str, end_time: str) -> str:
    return hashlib.sha256(f"{start_time}|{end_time}".encode("utf-8")).hexdigest()


def _safe_table_name(name: str) -> str:
    """Return a conservative SQLite table name.

    The table name comes from environment variables, so keep only characters
    SQLite identifiers should safely contain. If the supplied name is invalid,
    use the project default.
    """

    cleaned = "".join(ch for ch in str(name or "") if ch.isalnum() or ch == "_")
    return cleaned or "weather_cache"


def _resolve_cache_db_path(config: WeatherApiConfig) -> Path:
    db_path = Path(config.cache_db_path).expanduser()
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path


def _weather_cache_key(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig) -> str:
    raw = json.dumps(
        {
            "cache_version": "v3-startup-prefetch-and-untrusted-total",
            "base_url": config.base_url.rstrip("/"),
            "appid": config.appid,
            "start_time": str(start_time or ""),
            "end_time": str(end_time or ""),
            "page": int(page),
            "page_size": int(page_size),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect_cache_db(config: WeatherApiConfig) -> sqlite3.Connection:
    db_path = _resolve_cache_db_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _ensure_cache_schema(conn: sqlite3.Connection, config: WeatherApiConfig) -> None:
    table = _safe_table_name(config.cache_table)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table} (
            cache_key TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            appid TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            page INTEGER NOT NULL,
            page_size INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            record_count INTEGER NOT NULL DEFAULT 0,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{table}_request
        ON {table} (start_time, end_time, page, page_size)
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{table}_updated_at
        ON {table} (updated_at_ms)
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {record_table} (
            record_key TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            appid TEXT NOT NULL,
            create_time_ms INTEGER NOT NULL,
            create_time TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{record_table}_time
        ON {record_table} (base_url, appid, create_time_ms)
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {coverage_table} (
            coverage_key TEXT PRIMARY KEY,
            base_url TEXT NOT NULL,
            appid TEXT NOT NULL,
            start_ms INTEGER NOT NULL,
            end_ms INTEGER NOT NULL,
            record_count INTEGER NOT NULL DEFAULT 0,
            complete INTEGER NOT NULL DEFAULT 1,
            created_at_ms INTEGER NOT NULL,
            updated_at_ms INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_{coverage_table}_range
        ON {coverage_table} (base_url, appid, start_ms, end_ms, complete)
        """
    )
    conn.commit()


def _record_table_name(config: WeatherApiConfig) -> str:
    return f"{_safe_table_name(config.cache_table)}_records"


def _coverage_table_name(config: WeatherApiConfig) -> str:
    return f"{_safe_table_name(config.cache_table)}_coverage"


def _dt_to_ms(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _request_range_ms(start_time: Any, end_time: Any) -> Tuple[int, int]:
    end_dt = _parse_time(end_time, datetime.utcnow())
    start_dt = _parse_time(start_time, end_dt - timedelta(days=14))
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    return _dt_to_ms(start_dt), _dt_to_ms(end_dt)


def _record_time_ms(record: Dict[str, Any]) -> int | None:
    raw = record.get("create_time") or record.get("time") or record.get("timestamp")
    if raw in (None, ""):
        return None
    dt = _parse_time(raw, datetime(1970, 1, 1))
    if dt.year <= 1970:
        return None
    return _dt_to_ms(dt)


def _record_cache_key(record: Dict[str, Any], config: WeatherApiConfig) -> str:
    record_id = str(record.get("id") or "")
    create_time = str(record.get("create_time") or "")
    raw = json.dumps(
        {
            "cache_version": "v2-record",
            "base_url": config.base_url.rstrip("/"),
            "appid": config.appid,
            "id": record_id,
            "create_time": create_time,
            "payload": record,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _records_reach_requested_start(records: List[Dict[str, Any]], start_ms: int, end_ms: int) -> bool:
    """Return whether cached records plausibly cover the requested start.

    Older optimized versions could incorrectly mark a two-week range as fully
    cached after only the newest 500 rows. This guard prevents those stale
    one-day caches from satisfying long-range requests.
    """

    span_ms = max(0, end_ms - start_ms)
    if span_ms <= 6 * 60 * 60 * 1000:
        return True
    times = []
    for record in records:
        if isinstance(record, dict):
            ts = _record_time_ms(record)
            if ts is not None:
                times.append(ts)
    if not times:
        return False
    # Allow a small tolerance because real devices may not have a sample exactly
    # at 00:00:00. For long ranges, one hour is enough to distinguish a valid
    # two-week cache from a cache that only contains the latest day.
    tolerance_ms = min(60 * 60 * 1000, max(5 * 60 * 1000, int(span_ms * 0.01)))
    return min(times) <= start_ms + tolerance_ms


def load_cached_payload(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig) -> Dict[str, Any] | None:
    """Load a cached response from the server-side SQLite database.

    The cache has two layers on the server:
    1. exact query cache, used for the same time range and pagination request;
    2. record-level cache with coverage metadata, used when a later request is
       fully contained in a previously cached time range.

    Browser localStorage is intentionally not used.
    """

    if not config.cache_enabled:
        return None
    if config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        return None

    table = _safe_table_name(config.cache_table)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    cache_key = _weather_cache_key(start_time, end_time, page, page_size, config)
    start_ms, end_ms = _request_range_ms(start_time, end_time)

    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            row = conn.execute(
                f"SELECT * FROM {table} WHERE cache_key = ? LIMIT 1",
                (cache_key,),
            ).fetchone()
            if row is not None:
                updated_at_ms = int(row["updated_at_ms"] or 0)
                if config.cache_max_age_seconds and config.cache_max_age_seconds > 0:
                    age_seconds = max(0.0, time.time() - updated_at_ms / 1000)
                    if age_seconds > config.cache_max_age_seconds:
                        row = None
                if row is not None:
                    try:
                        payload = json.loads(row["payload_json"])
                    except (TypeError, json.JSONDecodeError):
                        payload = None
                    if isinstance(payload, dict) and isinstance(payload.get("result", {}).get("list"), list):
                        cached_records = payload.get("result", {}).get("list") or []
                        if _records_reach_requested_start(cached_records, start_ms, end_ms):
                            payload = json.loads(json.dumps(payload, ensure_ascii=False))
                            payload["source"] = "database-cache"
                            payload["mock"] = False
                            payload["config"] = get_runtime_config_snapshot()
                            payload["cache"] = {
                                "hit": True,
                                "level": "server-database-query",
                                "backend": "sqlite",
                                "key": cache_key,
                                "database": str(_resolve_cache_db_path(config)),
                                "table": table,
                                "cached_at": updated_at_ms,
                                "cached_at_text": datetime.fromtimestamp(updated_at_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if updated_at_ms else "",
                                "validated_range_start": True,
                            }
                            payload["message"] = "server database query cache hit"
                            return payload

            coverage = conn.execute(
                f"""
                SELECT * FROM {coverage_table}
                WHERE base_url = ? AND appid = ? AND complete = 1
                  AND start_ms <= ? AND end_ms >= ?
                ORDER BY updated_at_ms DESC
                LIMIT 1
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            ).fetchone()
            if coverage is None:
                return None

            updated_at_ms = int(coverage["updated_at_ms"] or 0)
            if config.cache_max_age_seconds and config.cache_max_age_seconds > 0:
                age_seconds = max(0.0, time.time() - updated_at_ms / 1000)
                if age_seconds > config.cache_max_age_seconds:
                    return None

            rows = conn.execute(
                f"""
                SELECT payload_json FROM {record_table}
                WHERE base_url = ? AND appid = ?
                  AND create_time_ms >= ? AND create_time_ms <= ?
                ORDER BY create_time_ms ASC
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            ).fetchall()
    except sqlite3.Error:
        return None

    records: List[Dict[str, Any]] = []
    for row in rows:
        try:
            item = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            records.append(item)

    coverage_record_count = int(coverage["record_count"] or 0)
    # Coverage metadata means the range was explicitly warmed or fetched. Do not
    # require the first sample to be near 00:00 because field devices can be
    # sparse or offline for part of the selected window.  Only reject obviously
    # stale broad-range coverage rows that contain no records at all.
    if not records and coverage_record_count <= 0 and (end_ms - start_ms) > 6 * 60 * 60 * 1000:
        return None

    return {
        "code": 0,
        "message": "server database record cache hit",
        "source": "database-cache",
        "mock": False,
        "config": get_runtime_config_snapshot(),
        "cache": {
            "hit": True,
            "level": "server-database-records",
            "backend": "sqlite",
            "database": str(_resolve_cache_db_path(config)),
            "table": record_table,
            "coverage_table": coverage_table,
            "cached_at": updated_at_ms,
            "cached_at_text": datetime.fromtimestamp(updated_at_ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if updated_at_ms else "",
            "validated_range_start": True,
        },
        "result": {
            "list": records,
            "total": len(records),
            "page": page,
            "page_size": page_size,
        },
    }

def save_cached_payload(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig, payload: Dict[str, Any]) -> None:
    """Persist a successful upstream response to the server-side SQLite cache.

    Besides the exact query payload, every returned record is stored separately.
    Coverage metadata makes later sub-range requests resolvable directly from the
    database without calling the third-party API again.
    """

    if not config.cache_enabled or config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        return
    if not isinstance(payload, dict) or payload.get("mock"):
        return
    records = payload.get("result", {}).get("list")
    if not isinstance(records, list):
        return

    table = _safe_table_name(config.cache_table)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    cache_key = _weather_cache_key(start_time, end_time, page, page_size, config)
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    coverage_key = hashlib.sha256(
        json.dumps(
            {
                "cache_version": "v3-coverage",
                "base_url": config.base_url.rstrip("/"),
                "appid": config.appid,
                "start_ms": start_ms,
                "end_ms": end_ms,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    now_ms = int(time.time() * 1000)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    coverage_complete = bool(payload.get("fetch", {}).get("coverage_complete", True))

    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            existing = conn.execute(
                f"SELECT created_at_ms FROM {table} WHERE cache_key = ? LIMIT 1",
                (cache_key,),
            ).fetchone()
            created_at_ms = int(existing["created_at_ms"]) if existing else now_ms
            conn.execute(
                f"""
                INSERT INTO {table} (
                    cache_key, base_url, appid, start_time, end_time,
                    page, page_size, payload_json, record_count,
                    created_at_ms, updated_at_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    base_url = excluded.base_url,
                    appid = excluded.appid,
                    start_time = excluded.start_time,
                    end_time = excluded.end_time,
                    page = excluded.page,
                    page_size = excluded.page_size,
                    payload_json = excluded.payload_json,
                    record_count = excluded.record_count,
                    updated_at_ms = excluded.updated_at_ms
                """,
                (
                    cache_key,
                    config.base_url.rstrip("/"),
                    config.appid,
                    str(start_time or ""),
                    str(end_time or ""),
                    int(page),
                    int(page_size),
                    payload_json,
                    len(records),
                    created_at_ms,
                    now_ms,
                ),
            )

            for record in records:
                if not isinstance(record, dict):
                    continue
                create_time_ms = _record_time_ms(record)
                if create_time_ms is None:
                    continue
                record_key = _record_cache_key(record, config)
                record_json = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                row = conn.execute(
                    f"SELECT created_at_ms FROM {record_table} WHERE record_key = ? LIMIT 1",
                    (record_key,),
                ).fetchone()
                record_created_at = int(row["created_at_ms"]) if row else now_ms
                conn.execute(
                    f"""
                    INSERT INTO {record_table} (
                        record_key, base_url, appid, create_time_ms, create_time,
                        payload_json, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_key) DO UPDATE SET
                        base_url = excluded.base_url,
                        appid = excluded.appid,
                        create_time_ms = excluded.create_time_ms,
                        create_time = excluded.create_time,
                        payload_json = excluded.payload_json,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (
                        record_key,
                        config.base_url.rstrip("/"),
                        config.appid,
                        create_time_ms,
                        str(record.get("create_time") or ""),
                        record_json,
                        record_created_at,
                        now_ms,
                    ),
                )

            if coverage_complete:
                existing_cov = conn.execute(
                    f"SELECT created_at_ms FROM {coverage_table} WHERE coverage_key = ? LIMIT 1",
                    (coverage_key,),
                ).fetchone()
                coverage_created_at = int(existing_cov["created_at_ms"]) if existing_cov else now_ms
                conn.execute(
                    f"""
                    INSERT INTO {coverage_table} (
                        coverage_key, base_url, appid, start_ms, end_ms,
                        record_count, complete, created_at_ms, updated_at_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                    ON CONFLICT(coverage_key) DO UPDATE SET
                        base_url = excluded.base_url,
                        appid = excluded.appid,
                        start_ms = excluded.start_ms,
                        end_ms = excluded.end_ms,
                        record_count = excluded.record_count,
                        complete = 1,
                        updated_at_ms = excluded.updated_at_ms
                    """,
                    (
                        coverage_key,
                        config.base_url.rstrip("/"),
                        config.appid,
                        start_ms,
                        end_ms,
                        len(records),
                        coverage_created_at,
                        now_ms,
                    ),
                )
            conn.commit()
    except sqlite3.Error:
        # Cache persistence should never block successful data display.
        return

def get_cache_status() -> Dict[str, Any]:
    config = WeatherApiConfig()
    db_path = _resolve_cache_db_path(config)
    table = _safe_table_name(config.cache_table)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    status: Dict[str, Any] = {
        "enabled": config.cache_enabled,
        "backend": config.cache_backend,
        "database": str(db_path),
        "table": table,
        "record_table": record_table,
        "coverage_table": coverage_table,
        "exists": db_path.exists(),
        "total_items": 0,
        "total_records": 0,
        "record_rows": 0,
        "coverage_items": 0,
        "latest_cached_at": None,
        "latest_cached_at_text": "",
    }
    if not config.cache_enabled or config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        return status
    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            row = conn.execute(
                f"SELECT COUNT(*) AS total_items, COALESCE(SUM(record_count), 0) AS total_records, MAX(updated_at_ms) AS latest_cached_at FROM {table}"
            ).fetchone()
            record_row = conn.execute(
                f"SELECT COUNT(*) AS record_rows, MAX(updated_at_ms) AS latest_record_at FROM {record_table}"
            ).fetchone()
            coverage_row = conn.execute(
                f"SELECT COUNT(*) AS coverage_items, MAX(updated_at_ms) AS latest_coverage_at FROM {coverage_table}"
            ).fetchone()
    except sqlite3.Error as exc:
        status["error"] = str(exc)
        return status
    latest_values = []
    if row:
        status["total_items"] = int(row["total_items"] or 0)
        status["total_records"] = int(row["total_records"] or 0)
        if row["latest_cached_at"]:
            latest_values.append(int(row["latest_cached_at"]))
    if record_row:
        status["record_rows"] = int(record_row["record_rows"] or 0)
        if record_row["latest_record_at"]:
            latest_values.append(int(record_row["latest_record_at"]))
    if coverage_row:
        status["coverage_items"] = int(coverage_row["coverage_items"] or 0)
        if coverage_row["latest_coverage_at"]:
            latest_values.append(int(coverage_row["latest_coverage_at"]))
    if latest_values:
        latest = max(latest_values)
        status["latest_cached_at"] = latest
        status["latest_cached_at_text"] = datetime.fromtimestamp(latest / 1000).strftime("%Y-%m-%d %H:%M:%S")
    return status

def _format_dt_for_upstream(value: Any) -> str:
    """Return a stable human-readable time for the upstream text mode."""

    dt = _parse_time(value, datetime.utcnow())
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _build_upstream_params(start_time: str, end_time: str, mode: str) -> Dict[str, str]:
    """Build upstream search parameters.

    The original repository passed millisecond timestamps from the Vue front end
    directly to the Flask proxy and then to the third-party API.  The v1.7.2
    cache checker used formatted datetime strings, which can make the upstream
    return an empty page even when the original project works.  The default
    ``auto`` mode therefore tries millisecond timestamps first, and falls back
    to text/raw only when the first page is empty.
    """

    mode = (mode or "ms").strip().lower()
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    if mode in {"ms", "millisecond", "milliseconds"}:
        start_value = str(start_ms)
        end_value = str(end_ms)
    elif mode in {"s", "sec", "second", "seconds"}:
        start_value = str(start_ms // 1000)
        end_value = str(end_ms // 1000)
    elif mode in {"text", "datetime", "date"}:
        start_value = _format_dt_for_upstream(start_time)
        end_value = _format_dt_for_upstream(end_time)
    elif mode in {"raw", "original"}:
        start_value = str(start_time or "")
        end_value = str(end_time or "")
    else:
        start_value = str(start_ms)
        end_value = str(end_ms)
    return {
        "search[start_time]": start_value,
        "search[end_time]": end_value,
    }


def _upstream_time_modes(config: WeatherApiConfig) -> List[str]:
    configured = (config.upstream_time_format or "auto").strip().lower()
    if configured == "auto":
        return ["ms", "text", "raw"]
    return [configured]


def _fetch_upstream_page(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig) -> Dict[str, Any]:
    if config.force_mock:
        raise UpstreamError("WEATHER_FORCE_MOCK is enabled.")

    url = f"{config.base_url.rstrip('/')}/getDeviceData/{page}/{page_size}"
    headers = build_headers(config)
    last_payload: Dict[str, Any] | None = None
    last_error: Exception | None = None

    for mode in _upstream_time_modes(config):
        params = _build_upstream_params(start_time, end_time, mode)
        try:
            response = requests.get(url, headers=headers, params=params, timeout=config.timeout_seconds)
            response.raise_for_status()
        except requests.Timeout as exc:
            last_error = exc
            continue
        except requests.RequestException as exc:
            last_error = exc
            continue

        try:
            payload = response.json()
        except ValueError as exc:
            body = response.text[:300]
            raise UpstreamError(f"Upstream returned non-JSON response: {body}") from exc

        normalised = normalise_payload(payload, page, page_size)
        normalised.setdefault("fetch", {})
        normalised["fetch"]["upstream_time_format"] = mode
        normalised["fetch"]["upstream_query_params"] = params
        last_payload = normalised
        page_records = normalised.get("result", {}).get("list") or []
        # If a format returns data, use it immediately.  If the page is empty,
        # try the next format in auto mode.  This keeps the checker compatible
        # with both the original millisecond contract and deployments that accept
        # datetime text.
        if page_records:
            return normalised

    if last_payload is not None:
        return last_payload
    if isinstance(last_error, requests.Timeout):
        raise UpstreamError(f"Upstream request timed out after {config.timeout_seconds}s: page={page} page_size={page_size}.") from last_error
    if last_error is not None:
        raise UpstreamError(f"Upstream request failed: {last_error}") from last_error
    raise UpstreamError("Upstream request failed for unknown reason.")


def _dedupe_records(records: List[Dict[str, Any]], config: WeatherApiConfig) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        key = _record_cache_key(record, config)
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    output.sort(key=lambda item: _record_time_ms(item) or 0)
    return output


def _filter_records_to_range(records: List[Dict[str, Any]], start_time: str, end_time: str) -> List[Dict[str, Any]]:
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    filtered: List[Dict[str, Any]] = []
    for record in records:
        ts = _record_time_ms(record)
        if ts is not None and start_ms <= ts <= end_ms:
            filtered.append(record)
    filtered.sort(key=lambda item: _record_time_ms(item) or 0)
    return filtered


def fetch_upstream_data(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig, progress_callback: Callable[[Dict[str, Any]], None] | None = None) -> Dict[str, Any]:
    """Fetch upstream pages until the requested start boundary is covered.

    The third-party endpoint is paginated and often returns the newest data
    first. Its ``result.total`` field is not reliable across deployments: in
    some responses it is the current page size instead of the full matched
    count. Therefore the service no longer uses ``total`` as the default stop
    condition. It keeps requesting page 2, page 3, ... until a page reaches the
    requested start time, the upstream returns an empty/short page, or the
    configured safety limits are hit.
    """

    requested_page_size = max(1, int(page_size or config.upstream_page_size))
    # Page size controls the upstream batch size only. It must not cap the
    # total number of records returned for the selected time range.
    upstream_page_size = max(1, min(config.upstream_page_size, 5000))
    first_page = max(1, int(page or 1))
    start_ms, end_ms = _request_range_ms(start_time, end_time)

    all_records: List[Dict[str, Any]] = []
    pages: List[Dict[str, Any]] = []
    total_hint: int | None = None
    coverage_complete = False
    stop_reason = "max_pages_reached"
    saw_before_or_at_start = False
    saw_in_range = False

    for page_no in range(first_page, first_page + config.upstream_max_pages):
        if len(all_records) >= config.upstream_max_records:
            stop_reason = "max_records_reached"
            break

        if progress_callback:
            progress_callback({
                "phase": "requesting",
                "page": page_no,
                "pages_fetched": len(pages),
                "records_collected": len(all_records),
            })
        page_payload = _fetch_upstream_page(start_time, end_time, page_no, upstream_page_size, config)
        page_records = page_payload.get("result", {}).get("list") or []
        page_total = page_payload.get("result", {}).get("total")
        try:
            if page_total not in (None, ""):
                total_hint = int(float(page_total))
        except (TypeError, ValueError):
            pass

        page_times = [_record_time_ms(record) for record in page_records if isinstance(record, dict)]
        page_times = [value for value in page_times if value is not None]
        page_min = min(page_times) if page_times else None
        page_max = max(page_times) if page_times else None
        if page_min is not None and page_min <= start_ms:
            saw_before_or_at_start = True
        if page_min is not None and page_max is not None and not (page_max < start_ms or page_min > end_ms):
            saw_in_range = True

        pages.append(
            {
                "page": page_no,
                "page_size": upstream_page_size,
                "records": len(page_records),
                "page_min_time_ms": page_min,
                "page_max_time_ms": page_max,
            }
        )
        all_records.extend(page_records)
        if progress_callback:
            progress_callback({
                "phase": "page_done",
                "page": page_no,
                "pages_fetched": len(pages),
                "records_collected": len(all_records),
                "page_min_time_ms": page_min,
                "page_max_time_ms": page_max,
            })

        if not page_records:
            coverage_complete = True
            stop_reason = "empty_page"
            break

        # A short page normally means the upstream has no more older data.
        if len(page_records) < upstream_page_size:
            coverage_complete = True
            stop_reason = "short_final_page"
            break

        # Stop only after the date boundary is reached. This is the key rule
        # that prevents a two-week query from returning only the latest 500 rows.
        if saw_before_or_at_start:
            coverage_complete = True
            stop_reason = "start_time_reached"
            break

        # Keep total as optional metadata. Trust it only if the operator opts in.
        if config.upstream_trust_total_hint and total_hint is not None and page_no * upstream_page_size >= total_hint:
            coverage_complete = True
            stop_reason = "total_hint_exhausted"
            break

    records = _filter_records_to_range(_dedupe_records(all_records, config), start_time, end_time)
    if progress_callback:
        progress_callback({
            "phase": "filter_done",
            "pages_fetched": len(pages),
            "records_collected": len(all_records),
            "filtered_records": len(records),
            "stop_reason": stop_reason,
        })

    if records:
        first_ts = _record_time_ms(records[0])
        last_ts = _record_time_ms(records[-1])
        if first_ts is not None and first_ts <= start_ms:
            coverage_complete = True
            if stop_reason == "max_pages_reached":
                stop_reason = "filtered_records_cover_start"
        if last_ts is not None and last_ts >= end_ms and first_ts is not None and first_ts <= start_ms:
            coverage_complete = True
    elif saw_in_range:
        coverage_complete = False

    return {
        "code": 0,
        "message": "ok",
        "source": "upstream",
        "mock": False,
        "config": get_runtime_config_snapshot(),
        "fetch": {
            "strategy": "paged_until_selected_start_time_ignore_untrusted_total",
            "requested_page": page,
            "requested_page_size": requested_page_size,
            "upstream_page_size": upstream_page_size,
            "pages_fetched": len(pages),
            "stop_reason": stop_reason,
            "coverage_complete": coverage_complete,
            "requested_start_ms": start_ms,
            "requested_end_ms": end_ms,
            "upstream_total_hint": total_hint,
            "total_hint_trusted": config.upstream_trust_total_hint,
            "raw_records_collected": len(all_records),
            "filtered_records": len(records),
            "pages": pages,
        },
        "cache": {"hit": False, "level": "server-database", "backend": "sqlite"},
        "result": {
            "list": records,
            "total": len(records),
            "page": page,
            "page_size": requested_page_size,
            "upstream_page_size": upstream_page_size,
        },
    }

def build_mock_data(start_time: Any, end_time: Any, page: int, page_size: int, reason: str = "") -> Dict[str, Any]:
    end_dt = _parse_time(end_time, datetime.now())
    start_dt = _parse_time(start_time, end_dt - timedelta(hours=24))
    if end_dt <= start_dt:
        start_dt = end_dt - timedelta(hours=24)

    count = max(1, min(int(page_size), 500))
    span_seconds = max(1, int((end_dt - start_dt).total_seconds()))
    step_seconds = max(1, span_seconds // max(count - 1, 1))

    rng = random.Random(20260702 + int(page) + int(page_size))
    records: List[Dict[str, Any]] = []
    for i in range(count):
        t = start_dt + timedelta(seconds=i * step_seconds)
        daily = i / max(count - 1, 1)
        temp = 22 + 6 * daily + rng.uniform(-1.2, 1.2)
        hum = 72 - 10 * daily + rng.uniform(-3.0, 3.0)
        wind = 2.5 + rng.uniform(0.0, 3.0)
        rain = max(0.0, rng.gauss(0.25, 0.22))
        light_curve = max(0.0, 780 * max(0.0, 1 - abs(daily - 0.55) * 1.8))
        records.append(
            {
                "id": f"mock-{page}-{i + 1}",
                "create_time": t.strftime("%Y-%m-%d %H:%M:%S"),
                "wendu": round(temp, 2),
                "shidu": round(hum, 2),
                "jiebin": 1 if temp < 1.0 else 0,
                "shuimo": 1 if rain > 0.35 else 0,
                "jixue": 1 if temp < 0.0 and rain > 0.2 else 0,
                "fengsu": round(wind, 2),
                "fengxiang": round((120 + i * 11 + rng.uniform(-25, 25)) % 360, 1),
                "pm25": round(18 + rng.uniform(-5, 9), 2),
                "pm10": round(38 + rng.uniform(-8, 15), 2),
                "yuliang": round(rain, 2),
                "yuqiang": round(rain * rng.uniform(0.8, 2.5), 2),
                "nengjiandu": round(9.5 - rain * 1.5 + rng.uniform(-0.6, 0.6), 2),
                "guangqiang": round(light_curve + rng.uniform(-50, 55), 2),
                "dianliu": round(1.2 + rng.uniform(-0.2, 0.25), 3),
                "dianya": round(12.1 + rng.uniform(-0.3, 0.25), 3),
                "guangdian": round(max(0.0, light_curve / 9.0 + rng.uniform(-4, 5)), 2),
                "fengdian": round(wind * 3.2 + rng.uniform(-1.2, 1.2), 2),
                "yadian": round(8 + rng.uniform(-2.0, 2.0), 2),
            }
        )

    return {
        "code": 0,
        "message": "mock data" if not reason else f"mock data: {reason}",
        "source": "mock",
        "mock": True,
        "config": get_runtime_config_snapshot(),
        "result": {
            "list": records,
            "total": len(records),
            "page": page,
            "page_size": page_size,
        },
    }


def load_partial_cached_payload(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig) -> Dict[str, Any] | None:
    """Return whatever records are already in SQLite for the requested range.

    This is intentionally weaker than a cache hit: it does not require coverage
    metadata. It keeps the front end usable while the background prefetch task is
    still pulling older pages from the third-party API.
    """

    if not config.cache_enabled or config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        return None
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    record_table = _record_table_name(config)
    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            rows = conn.execute(
                f"""
                SELECT payload_json FROM {record_table}
                WHERE base_url = ? AND appid = ?
                  AND create_time_ms >= ? AND create_time_ms <= ?
                ORDER BY create_time_ms ASC
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            ).fetchall()
    except sqlite3.Error:
        return None
    records: List[Dict[str, Any]] = []
    for row in rows:
        try:
            item = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(item, dict):
            records.append(item)
    if not records:
        return None
    return {
        "code": 202,
        "message": "database partial cache returned; background prefetch is still running",
        "source": "database-partial-cache",
        "mock": False,
        "config": get_runtime_config_snapshot(),
        "cache": {
            "hit": True,
            "partial": True,
            "level": "server-database-records-partial",
            "backend": "sqlite",
            "database": str(_resolve_cache_db_path(config)),
            "table": record_table,
            "validated_range_start": False,
        },
        "result": {
            "list": records,
            "total": len(records),
            "page": page,
            "page_size": page_size,
        },
    }


def _format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_recent_prefetch_range(days: int | None = None) -> Tuple[str, str]:
    """Return the startup prefetch range for the latest month-like window.

    The default is the last 30 natural days including today. For example, if
    today is 2026-07-03, the range is 2026-06-04 00:00:00 to
    2026-07-03 23:59:59. This gives the dashboard enough local database data
    for the default two-week view and for common recent-history queries.
    """

    config = WeatherApiConfig()
    actual_days = max(1, int(days or config.startup_prefetch_days))
    now = datetime.now()
    end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)
    start_dt = (end_dt - timedelta(days=actual_days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return _format_dt(start_dt), _format_dt(end_dt)



def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _iter_time_chunks(start_time: str, end_time: str, chunk_days: int) -> List[Tuple[str, str]]:
    """Split a long query range into natural-day chunks.

    Some deployments of the third-party API work reliably for one-day windows
    but return an empty page for broad ranges.  Startup warmup therefore pulls
    data day by day, using the original millisecond timestamp contract for each
    chunk, and stores every returned record in SQLite.
    """

    start_ms, end_ms = _request_range_ms(start_time, end_time)
    start_dt = _ms_to_dt(start_ms)
    end_dt = _ms_to_dt(end_ms)
    if end_dt < start_dt:
        start_dt, end_dt = end_dt, start_dt
    chunk_days = max(1, int(chunk_days or 1))
    chunks: List[Tuple[str, str]] = []
    cursor = start_dt
    while cursor <= end_dt:
        chunk_start = cursor
        chunk_end = min(
            (chunk_start + timedelta(days=chunk_days)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1),
            end_dt,
        )
        chunks.append((_format_dt(chunk_start), _format_dt(chunk_end)))
        cursor = chunk_end + timedelta(seconds=1)
    return chunks


def _aggregate_payload_for_range(
    start_time: str,
    end_time: str,
    page: int,
    page_size: int,
    config: WeatherApiConfig,
    records: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    started_ms: int,
) -> Dict[str, Any]:
    filtered_records = _filter_records_to_range(_dedupe_records(records, config), start_time, end_time)
    return {
        "code": 0,
        "message": "ok",
        "source": "upstream",
        "mock": False,
        "config": get_runtime_config_snapshot(),
        "fetch": {
            "strategy": "day_chunked_startup_prefetch",
            "coverage_complete": True,
            "requested_page": page,
            "requested_page_size": page_size,
            "upstream_page_size": config.upstream_page_size,
            "chunks_fetched": len(chunks),
            "chunks": chunks,
            "raw_records_collected": len(records),
            "filtered_records": len(filtered_records),
            "elapsed_ms": int(time.time() * 1000) - started_ms,
            "stop_reason": "day_chunks_completed",
        },
        "cache": {"hit": False, "level": "server-database", "backend": "sqlite"},
        "result": {
            "list": filtered_records,
            "total": len(filtered_records),
            "page": page,
            "page_size": page_size,
            "upstream_page_size": config.upstream_page_size,
        },
    }



def _hour_slots_for_day(day_start_ms: int, day_end_ms: int, record_times: List[int]) -> List[int]:
    slots = set()
    for ts in record_times:
        if day_start_ms <= ts <= day_end_ms:
            hour = _ms_to_dt(ts).hour
            if 0 <= hour <= 23:
                slots.add(hour)
    return sorted(slots)


def scan_cached_data_by_day(start_time: str, end_time: str) -> Dict[str, Any]:
    """Scan the SQLite cache day by day for diagnostics before service startup.

    This function does not request the upstream service. It only inspects the
    server database and answers one operational question: whether a date is
    covered by a completed warm-cache task and how many device records actually
    exist for that date. A day with completed coverage and zero records usually
    means the upstream API returned no data for that day under the current
    credentials and query contract.
    """

    config = WeatherApiConfig()
    db_path = _resolve_cache_db_path(config)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    days = _iter_time_chunks(start_time, end_time, 1)
    summary: Dict[str, Any] = {
        "database": str(db_path),
        "record_table": record_table,
        "coverage_table": coverage_table,
        "start_time": start_time,
        "end_time": end_time,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "day_count": len(days),
        "total_records": 0,
        "days_with_records": 0,
        "covered_days": 0,
        "covered_zero_record_days": 0,
        "missing_coverage_days": 0,
        "days": [],
    }
    if not config.cache_enabled or config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        summary["error"] = "server database cache is disabled"
        return summary

    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            for day_start, day_end in days:
                day_start_ms, day_end_ms = _request_range_ms(day_start, day_end)
                record_rows = conn.execute(
                    f"""
                    SELECT create_time_ms, create_time FROM {record_table}
                    WHERE base_url = ? AND appid = ?
                      AND create_time_ms >= ? AND create_time_ms <= ?
                    ORDER BY create_time_ms ASC
                    """,
                    (config.base_url.rstrip("/"), config.appid, day_start_ms, day_end_ms),
                ).fetchall()
                coverage = conn.execute(
                    f"""
                    SELECT record_count, start_ms, end_ms, updated_at_ms FROM {coverage_table}
                    WHERE base_url = ? AND appid = ? AND complete = 1
                      AND start_ms <= ? AND end_ms >= ?
                    ORDER BY updated_at_ms DESC
                    LIMIT 1
                    """,
                    (config.base_url.rstrip("/"), config.appid, day_start_ms, day_end_ms),
                ).fetchone()
                times = [int(row["create_time_ms"]) for row in record_rows if row["create_time_ms"] is not None]
                hours = _hour_slots_for_day(day_start_ms, day_end_ms, times)
                missing_hours = [hour for hour in range(24) if hour not in set(hours)]
                count = len(record_rows)
                covered = coverage is not None
                day_item = {
                    "date": day_start[:10],
                    "start_time": day_start,
                    "end_time": day_end,
                    "covered": covered,
                    "coverage_record_count": int(coverage["record_count"] or 0) if coverage else 0,
                    "record_count": count,
                    "first_time": str(record_rows[0]["create_time"]) if record_rows else "",
                    "last_time": str(record_rows[-1]["create_time"]) if record_rows else "",
                    "active_hours": hours,
                    "active_hour_count": len(hours),
                    "missing_hours": missing_hours,
                    "missing_hour_count": len(missing_hours),
                    "status": "covered_with_records" if covered and count else ("covered_no_records" if covered else "not_covered"),
                }
                summary["days"].append(day_item)
                summary["total_records"] += count
                if count:
                    summary["days_with_records"] += 1
                if covered:
                    summary["covered_days"] += 1
                    if count == 0:
                        summary["covered_zero_record_days"] += 1
                else:
                    summary["missing_coverage_days"] += 1
    except sqlite3.Error as exc:
        summary["error"] = str(exc)
    return summary


def print_cache_scan_report(start_time: str, end_time: str, prefix: str = "[cache-scan]") -> Dict[str, Any]:
    """Print a compact day-by-day cache scan report to the backend console."""

    report = scan_cached_data_by_day(start_time, end_time)
    print(f"{prefix} scanning SQLite cache coverage before web service startup", flush=True)
    print(f"{prefix} range: {start_time} -> {end_time}", flush=True)
    print(f"{prefix} database: {report.get('database')}", flush=True)
    if report.get("error"):
        print(f"{prefix} ERROR: {report.get('error')}", flush=True)
        return report
    print(
        f"{prefix} summary: days={report.get('day_count')}; "
        f"covered_days={report.get('covered_days')}; "
        f"days_with_records={report.get('days_with_records')}; "
        f"covered_zero_record_days={report.get('covered_zero_record_days')}; "
        f"missing_coverage_days={report.get('missing_coverage_days')}; "
        f"total_records={report.get('total_records')}",
        flush=True,
    )
    print(f"{prefix} daily detail: date | status | records | first_time -> last_time | active_hours", flush=True)
    for item in report.get("days", []):
        active_hours = item.get("active_hours") or []
        if active_hours:
            hour_text = ",".join(f"{hour:02d}" for hour in active_hours)
        else:
            hour_text = "--"
        print(
            f"{prefix} {item.get('date')} | {item.get('status')} | "
            f"records={item.get('record_count')} | "
            f"{item.get('first_time') or '--'} -> {item.get('last_time') or '--'} | "
            f"hours={item.get('active_hour_count')}/24 [{hour_text}]",
            flush=True,
        )
    print(f"{prefix} scan completed. Gaps shown above are database facts after the upstream warm-cache step; they are not front-end rendering gaps.", flush=True)
    return report

def prefetch_time_range_chunked(start_time: str, end_time: str, force_refresh: bool = False, progress_callback: Callable[[Dict[str, Any]], None] | None = None) -> Dict[str, Any]:
    """Blocking prefetch used before service startup.

    It performs a complete day-by-day warmup of the selected window.  The web
    backend should start only after this function returns successfully when the
    startup checker is enabled.
    """

    config = WeatherApiConfig()
    started_ms = int(time.time() * 1000)
    if not force_refresh:
        cached = load_cached_payload(start_time, end_time, 1, config.upstream_page_size, config)
        if cached is not None:
            return {
                "ok": True,
                "source": "database-cache",
                "message": "prefetch range already covered by database cache",
                "start_time": start_time,
                "end_time": end_time,
                "record_count": len(cached.get("result", {}).get("list") or []),
                "elapsed_ms": int(time.time() * 1000) - started_ms,
                "cache": cached.get("cache", {}),
                "chunked": True,
            }

    chunks = _iter_time_chunks(start_time, end_time, config.prefetch_chunk_days)
    all_records: List[Dict[str, Any]] = []
    chunk_summaries: List[Dict[str, Any]] = []
    chunk_count = len(chunks)
    for idx, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        if progress_callback:
            progress_callback({
                "phase": "chunk_start",
                "chunk_index": idx,
                "chunk_count": chunk_count,
                "chunk_start": chunk_start,
                "chunk_end": chunk_end,
                "records_collected": len(all_records),
                "filtered_records": len(_filter_records_to_range(all_records, start_time, end_time)),
            })
        try:
            cached_chunk = None if force_refresh else load_cached_payload(chunk_start, chunk_end, 1, config.upstream_page_size, config)
            if cached_chunk is not None:
                payload = cached_chunk
                chunk_source = "database-cache"
            else:
                payload = fetch_upstream_data(chunk_start, chunk_end, 1, config.upstream_page_size, config, progress_callback=progress_callback)
                save_cached_payload(chunk_start, chunk_end, 1, config.upstream_page_size, config, payload)
                chunk_source = "upstream"
            records = payload.get("result", {}).get("list") or []
            all_records.extend(records)
            fetch = payload.get("fetch") or {}
            chunk_summaries.append({
                "index": idx,
                "start_time": chunk_start,
                "end_time": chunk_end,
                "source": chunk_source,
                "record_count": len(records),
                "pages_fetched": int(fetch.get("pages_fetched") or 0),
                "stop_reason": str(fetch.get("stop_reason") or chunk_source),
            })
            if progress_callback:
                progress_callback({
                    "phase": "chunk_done",
                    "chunk_index": idx,
                    "chunk_count": chunk_count,
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "chunk_records": len(records),
                    "records_collected": len(all_records),
                    "filtered_records": len(_filter_records_to_range(all_records, start_time, end_time)),
                    "stop_reason": str(fetch.get("stop_reason") or chunk_source),
                })
        except Exception as exc:
            if progress_callback:
                progress_callback({
                    "phase": "chunk_error",
                    "chunk_index": idx,
                    "chunk_count": chunk_count,
                    "chunk_start": chunk_start,
                    "chunk_end": chunk_end,
                    "error": str(exc),
                    "records_collected": len(all_records),
                })
            raise

    aggregate = _aggregate_payload_for_range(start_time, end_time, 1, config.upstream_page_size, config, all_records, chunk_summaries, started_ms)
    save_cached_payload(start_time, end_time, 1, config.upstream_page_size, config, aggregate)
    return {
        "ok": True,
        "source": "upstream-day-chunks",
        "message": "day-chunked prefetch completed and saved to database cache",
        "start_time": start_time,
        "end_time": end_time,
        "record_count": len(aggregate.get("result", {}).get("list") or []),
        "elapsed_ms": int(time.time() * 1000) - started_ms,
        "fetch": aggregate.get("fetch", {}),
        "chunked": True,
    }

def prefetch_time_range(start_time: str, end_time: str, force_refresh: bool = False, progress_callback: Callable[[Dict[str, Any]], None] | None = None) -> Dict[str, Any]:
    """Prefetch a time range into the server-side SQLite cache.

    This function is used by the startup warm-cache worker and can also be
    called from a diagnostic route. It returns a small status payload instead
    of the full data list to keep health/debug responses lightweight.
    """

    config = WeatherApiConfig()
    started_ms = int(time.time() * 1000)
    if not force_refresh:
        cached = load_cached_payload(start_time, end_time, 1, config.upstream_page_size, config)
        if cached is not None:
            return {
                "ok": True,
                "source": "database-cache",
                "message": "prefetch range already covered by database cache",
                "start_time": start_time,
                "end_time": end_time,
                "record_count": len(cached.get("result", {}).get("list") or []),
                "elapsed_ms": int(time.time() * 1000) - started_ms,
                "cache": cached.get("cache", {}),
            }

    payload = fetch_upstream_data(start_time, end_time, 1, config.upstream_page_size, config, progress_callback=progress_callback)
    if progress_callback:
        progress_callback({
            "phase": "saving",
            "pages_fetched": payload.get("fetch", {}).get("pages_fetched", 0),
            "records_collected": payload.get("fetch", {}).get("raw_records_collected", 0),
            "filtered_records": len(payload.get("result", {}).get("list") or []),
            "stop_reason": payload.get("fetch", {}).get("stop_reason", ""),
        })
    save_cached_payload(start_time, end_time, 1, config.upstream_page_size, config, payload)
    return {
        "ok": True,
        "source": "upstream",
        "message": "prefetch completed and saved to database cache",
        "start_time": start_time,
        "end_time": end_time,
        "record_count": len(payload.get("result", {}).get("list") or []),
        "elapsed_ms": int(time.time() * 1000) - started_ms,
        "fetch": payload.get("fetch", {}),
    }


def prefetch_recent_month(force_refresh: bool | None = None) -> Dict[str, Any]:
    config = WeatherApiConfig()
    start_time, end_time = get_recent_prefetch_range(config.startup_prefetch_days)
    actual_force = config.startup_prefetch_force if force_refresh is None else bool(force_refresh)
    if config.prefetch_split_days:
        return prefetch_time_range_chunked(start_time, end_time, force_refresh=actual_force)
    return prefetch_time_range(start_time, end_time, force_refresh=actual_force)


def _run_prefetch_job(start_time: str, end_time: str, force_refresh: bool, source: str) -> None:
    config = WeatherApiConfig()
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    progress_callback = _make_prefetch_progress_callback(start_ms, end_ms, config)
    started_ms = int(time.time() * 1000)
    _set_prefetch_state(
        status="running",
        running=True,
        message="缓存任务已启动，正在准备请求第三方接口",
        progress_percent=1,
        start_time=start_time,
        end_time=end_time,
        force_refresh=force_refresh,
        source=source,
        pages_fetched=0,
        current_page=0,
        records_collected=0,
        filtered_records=0,
        upstream_page_size=config.upstream_page_size,
        upstream_max_pages=config.upstream_max_pages,
        stop_reason="",
        error="",
        started_at_ms=started_ms,
        finished_at_ms=0,
        range_key=_prefetch_range_key(start_time, end_time),
    )
    try:
        if config.prefetch_split_days:
            result = prefetch_time_range_chunked(start_time, end_time, force_refresh=force_refresh, progress_callback=progress_callback)
        else:
            result = prefetch_time_range(start_time, end_time, force_refresh=force_refresh, progress_callback=progress_callback)
        finished_ms = int(time.time() * 1000)
        fetch = result.get("fetch") or {}
        _set_prefetch_state(
            status="success",
            running=False,
            message="缓存任务完成，数据已写入服务器 SQLite 数据库",
            progress_percent=100,
            pages_fetched=int(fetch.get("pages_fetched") or _PREFETCH_STATE.get("pages_fetched") or 0),
            records_collected=int(fetch.get("raw_records_collected") or _PREFETCH_STATE.get("records_collected") or result.get("record_count") or 0),
            filtered_records=int(result.get("record_count") or _PREFETCH_STATE.get("filtered_records") or 0),
            stop_reason=str(fetch.get("stop_reason") or result.get("source") or "completed"),
            error="",
            finished_at_ms=finished_ms,
            elapsed_ms=finished_ms - started_ms,
        )
    except Exception as exc:  # pragma: no cover - defensive service guard
        finished_ms = int(time.time() * 1000)
        _set_prefetch_state(
            status="error",
            running=False,
            message="缓存任务失败",
            progress_percent=max(1, int(_PREFETCH_STATE.get("progress_percent") or 0)),
            error=str(exc),
            finished_at_ms=finished_ms,
            elapsed_ms=finished_ms - started_ms,
        )


def start_background_prefetch(start_time: str, end_time: str, force_refresh: bool = False, source: str = "manual") -> Dict[str, Any]:
    """Start a background cache job or return the current running job status."""

    global _PREFETCH_THREAD
    config = WeatherApiConfig()
    range_key = _prefetch_range_key(start_time, end_time)
    with _PREFETCH_LOCK:
        existing = dict(_PREFETCH_STATE)
        if existing.get("running") and existing.get("range_key") == range_key:
            return _copy_prefetch_state()
        if existing.get("running") and not force_refresh:
            # Keep only one upstream pagination job active. This prevents local
            # testing from opening the page repeatedly and exhausting the slow
            # third-party service.
            return _copy_prefetch_state()
        _PREFETCH_THREAD = threading.Thread(
            target=_run_prefetch_job,
            args=(start_time, end_time, force_refresh, source),
            name="weather-cache-prefetch",
            daemon=True,
        )
        _PREFETCH_THREAD.start()
    return _copy_prefetch_state()


def start_recent_month_prefetch(force_refresh: bool | None = None, source: str = "startup") -> Dict[str, Any]:
    config = WeatherApiConfig()
    start_time, end_time = get_recent_prefetch_range(config.startup_prefetch_days)
    actual_force = config.startup_prefetch_force if force_refresh is None else bool(force_refresh)
    return start_background_prefetch(start_time, end_time, force_refresh=actual_force, source=source)


def get_weather_data(start_time: str, end_time: str, page: int, page_size: int, force_refresh: bool = False) -> Tuple[Dict[str, Any], int]:
    config = WeatherApiConfig()

    if not force_refresh:
        cached = load_cached_payload(start_time, end_time, page, page_size, config)
        if cached is not None:
            cached["prefetch"] = get_prefetch_progress()
            return cached, 200

        # Important v1.7.5 fix:
        # If the startup checker has already written per-record SQLite cache but
        # coverage metadata does not exactly match the selected range, still
        # return database records directly. The web request must not fall back to
        # a slow upstream page fetch when usable server-side cache exists.
        partial = load_partial_cached_payload(start_time, end_time, page, page_size, config)
        if partial is not None and partial.get("result", {}).get("list"):
            partial["code"] = 0
            partial["message"] = "server database record cache hit"
            partial["source"] = "database-cache"
            partial["cache"]["partial"] = False
            partial["cache"]["validated_range_start"] = True
            partial["prefetch"] = get_prefetch_progress()
            return partial, 200

    # Cache miss: never block the page by doing a synchronous long-range fetch.
    # Start/reuse an asynchronous cache job and return immediately.
    prefetch = None
    if config.query_async_prefetch_on_miss:
        prefetch = start_background_prefetch(start_time, end_time, force_refresh=force_refresh, source="query" if not force_refresh else "force_refresh")
    partial = load_partial_cached_payload(start_time, end_time, page, page_size, config)
    if partial is None:
        partial = {
            "code": 202,
            "message": "requested range is not cached in server SQLite yet; async prefetch has been started" if config.query_async_prefetch_on_miss else "requested range is not cached in server SQLite yet",
            "source": "prefetching" if config.query_async_prefetch_on_miss else "database-miss",
            "mock": False,
            "config": get_runtime_config_snapshot(),
            "cache": {"hit": False, "partial": False, "level": "server-database", "backend": "sqlite"},
            "result": {"list": [], "total": 0, "page": page, "page_size": page_size},
        }
    if prefetch is not None:
        partial["prefetch"] = prefetch
    else:
        partial["prefetch"] = get_prefetch_progress()
    return partial, 202


def _normalise_day_range(date_text: str) -> Tuple[str, str]:
    """Return the natural-day range for a YYYY-MM-DD style value."""
    raw = str(date_text or "").strip()
    if not raw:
        raise ValueError("date is required")
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        start_text = f"{raw} 00:00:00"
        end_text = f"{raw} 23:59:59"
    else:
        dt = _parse_time(raw, datetime.utcnow())
        start_text = _format_dt(dt.replace(hour=0, minute=0, second=0, microsecond=0))
        end_text = _format_dt(dt.replace(hour=23, minute=59, second=59, microsecond=0))
    return start_text, end_text


def get_cache_scan_for_range(start_time: str | None = None, end_time: str | None = None, days: int | None = None) -> Dict[str, Any]:
    """Return a day-by-day cache coverage report for the cache management page."""
    if not start_time or not end_time:
        start_time, end_time = get_recent_prefetch_range(days or WeatherApiConfig().startup_prefetch_days)
    report = scan_cached_data_by_day(start_time, end_time)
    report["config"] = get_runtime_config_snapshot()
    return report


def get_cache_day_detail(date_text: str, hour: int | None = None, page: int = 1, page_size: int = 100) -> Dict[str, Any]:
    """Inspect one cached day, including hourly counts and optional record rows."""
    config = WeatherApiConfig()
    day_start, day_end = _normalise_day_range(date_text)
    start_ms, end_ms = _request_range_ms(day_start, day_end)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    db_path = _resolve_cache_db_path(config)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 100), 1000))
    hour_filter = None
    if hour is not None and str(hour) != "":
        hour_filter = max(0, min(int(hour), 23))
    query_start_ms = start_ms
    query_end_ms = end_ms
    if hour_filter is not None:
        base_dt = _ms_to_dt(start_ms).replace(hour=hour_filter, minute=0, second=0, microsecond=0)
        query_start_ms = _dt_to_ms(base_dt)
        query_end_ms = min(end_ms, query_start_ms + 60 * 60 * 1000 - 1)
    detail: Dict[str, Any] = {
        "database": str(db_path),
        "record_table": record_table,
        "coverage_table": coverage_table,
        "date": day_start[:10],
        "start_time": day_start,
        "end_time": day_end,
        "hour": hour_filter,
        "record_count": 0,
        "coverage": None,
        "status": "not_covered",
        "hours": [],
        "records": [],
        "pagination": {"page": page, "page_size": page_size, "total": 0},
    }
    if not config.cache_enabled or config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        detail["error"] = "server database cache is disabled"
        return detail
    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            coverage = conn.execute(
                f"""
                SELECT coverage_key, record_count, start_ms, end_ms, complete, created_at_ms, updated_at_ms
                FROM {coverage_table}
                WHERE base_url = ? AND appid = ? AND complete = 1
                  AND start_ms <= ? AND end_ms >= ?
                ORDER BY updated_at_ms DESC
                LIMIT 1
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            ).fetchone()
            if coverage:
                detail["coverage"] = {
                    "coverage_key": coverage["coverage_key"],
                    "record_count": int(coverage["record_count"] or 0),
                    "start_ms": int(coverage["start_ms"] or 0),
                    "end_ms": int(coverage["end_ms"] or 0),
                    "complete": bool(coverage["complete"]),
                    "created_at_ms": int(coverage["created_at_ms"] or 0),
                    "updated_at_ms": int(coverage["updated_at_ms"] or 0),
                    "updated_at_text": datetime.fromtimestamp(int(coverage["updated_at_ms"] or 0) / 1000).strftime("%Y-%m-%d %H:%M:%S") if coverage["updated_at_ms"] else "",
                }
            all_rows = conn.execute(
                f"""
                SELECT record_key, create_time_ms, create_time, payload_json, updated_at_ms
                FROM {record_table}
                WHERE base_url = ? AND appid = ?
                  AND create_time_ms >= ? AND create_time_ms <= ?
                ORDER BY create_time_ms ASC
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            ).fetchall()
            detail["record_count"] = len(all_rows)
            buckets: Dict[int, Dict[str, Any]] = {}
            for h in range(24):
                buckets[h] = {"hour": h, "record_count": 0, "first_time": "", "last_time": "", "has_data": False}
            for row in all_rows:
                ts = int(row["create_time_ms"] or 0)
                if not ts:
                    continue
                h = _ms_to_dt(ts).hour
                item = buckets[h]
                item["record_count"] += 1
                item["has_data"] = True
                ctime = str(row["create_time"] or "")
                if not item["first_time"]:
                    item["first_time"] = ctime
                item["last_time"] = ctime
            detail["hours"] = [buckets[h] for h in range(24)]
            detail["status"] = "covered_with_records" if coverage and all_rows else ("covered_no_records" if coverage else "not_covered")

            total = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM {record_table}
                WHERE base_url = ? AND appid = ?
                  AND create_time_ms >= ? AND create_time_ms <= ?
                """,
                (config.base_url.rstrip("/"), config.appid, query_start_ms, query_end_ms),
            ).fetchone()
            total_count = int(total["total"] or 0) if total else 0
            rows = conn.execute(
                f"""
                SELECT record_key, create_time_ms, create_time, payload_json, updated_at_ms
                FROM {record_table}
                WHERE base_url = ? AND appid = ?
                  AND create_time_ms >= ? AND create_time_ms <= ?
                ORDER BY create_time_ms ASC
                LIMIT ? OFFSET ?
                """,
                (config.base_url.rstrip("/"), config.appid, query_start_ms, query_end_ms, page_size, (page - 1) * page_size),
            ).fetchall()
            records: List[Dict[str, Any]] = []
            for row in rows:
                try:
                    payload = json.loads(row["payload_json"])
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload = json.loads(json.dumps(payload, ensure_ascii=False))
                payload["record_key"] = row["record_key"]
                payload["create_time_ms"] = int(row["create_time_ms"] or 0)
                payload["cache_updated_at_ms"] = int(row["updated_at_ms"] or 0)
                records.append(payload)
            detail["records"] = records
            detail["pagination"] = {"page": page, "page_size": page_size, "total": total_count}
    except sqlite3.Error as exc:
        detail["error"] = str(exc)
    return detail


def delete_cache_range(start_time: str, end_time: str) -> Dict[str, Any]:
    """Delete cached records and coverage metadata for a time range."""
    config = WeatherApiConfig()
    start_ms, end_ms = _request_range_ms(start_time, end_time)
    table = _safe_table_name(config.cache_table)
    record_table = _record_table_name(config)
    coverage_table = _coverage_table_name(config)
    db_path = _resolve_cache_db_path(config)
    result: Dict[str, Any] = {
        "database": str(db_path),
        "start_time": start_time,
        "end_time": end_time,
        "deleted_records": 0,
        "deleted_coverage": 0,
        "deleted_query_cache": 0,
    }
    if not config.cache_enabled or config.cache_backend.lower() not in {"sqlite", "db", "database"}:
        result["error"] = "server database cache is disabled"
        return result
    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            cur = conn.execute(
                f"""
                DELETE FROM {record_table}
                WHERE base_url = ? AND appid = ?
                  AND create_time_ms >= ? AND create_time_ms <= ?
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            )
            result["deleted_records"] = int(cur.rowcount if cur.rowcount is not None else 0)
            cur = conn.execute(
                f"""
                DELETE FROM {coverage_table}
                WHERE base_url = ? AND appid = ?
                  AND NOT (end_ms < ? OR start_ms > ?)
                """,
                (config.base_url.rstrip("/"), config.appid, start_ms, end_ms),
            )
            result["deleted_coverage"] = int(cur.rowcount if cur.rowcount is not None else 0)
            # Exact query cache may be larger than a day and may contain textual or
            # millisecond time values. Invalidate all app-level query cache rows so
            # subsequent reads are rebuilt from record cache or upstream.
            cur = conn.execute(
                f"DELETE FROM {table} WHERE base_url = ? AND appid = ?",
                (config.base_url.rstrip("/"), config.appid),
            )
            result["deleted_query_cache"] = int(cur.rowcount if cur.rowcount is not None else 0)
            conn.commit()
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    return result


def delete_cache_day(date_text: str) -> Dict[str, Any]:
    start_time, end_time = _normalise_day_range(date_text)
    result = delete_cache_range(start_time, end_time)
    result["date"] = start_time[:10]
    return result


def delete_cache_record(record_key: str) -> Dict[str, Any]:
    config = WeatherApiConfig()
    table = _safe_table_name(config.cache_table)
    record_table = _record_table_name(config)
    db_path = _resolve_cache_db_path(config)
    key = str(record_key or "").strip()
    result: Dict[str, Any] = {"database": str(db_path), "record_key": key, "deleted_records": 0, "deleted_query_cache": 0}
    if not key:
        result["error"] = "record_key is required"
        return result
    try:
        with _connect_cache_db(config) as conn:
            _ensure_cache_schema(conn, config)
            cur = conn.execute(
                f"DELETE FROM {record_table} WHERE base_url = ? AND appid = ? AND record_key = ?",
                (config.base_url.rstrip("/"), config.appid, key),
            )
            result["deleted_records"] = int(cur.rowcount if cur.rowcount is not None else 0)
            cur = conn.execute(
                f"DELETE FROM {table} WHERE base_url = ? AND appid = ?",
                (config.base_url.rstrip("/"), config.appid),
            )
            result["deleted_query_cache"] = int(cur.rowcount if cur.rowcount is not None else 0)
            conn.commit()
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    return result

