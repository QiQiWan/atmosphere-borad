"""Weather data access layer with upstream fallback and stable response schema."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import requests


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


def fetch_upstream_data(start_time: str, end_time: str, page: int, page_size: int, config: WeatherApiConfig) -> Dict[str, Any]:
    if config.force_mock:
        raise UpstreamError("WEATHER_FORCE_MOCK is enabled.")

    url = f"{config.base_url.rstrip('/')}/getDeviceData/{page}/{page_size}"
    params = {
        "search[start_time]": start_time,
        "search[end_time]": end_time,
    }
    headers = build_headers(config)

    try:
        response = requests.get(url, headers=headers, params=params, timeout=config.timeout_seconds)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise UpstreamError(f"Upstream request timed out after {config.timeout_seconds}s.") from exc
    except requests.RequestException as exc:
        raise UpstreamError(f"Upstream request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        body = response.text[:300]
        raise UpstreamError(f"Upstream returned non-JSON response: {body}") from exc

    return normalise_payload(payload, page, page_size)


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


def get_weather_data(start_time: str, end_time: str, page: int, page_size: int) -> Tuple[Dict[str, Any], int]:
    config = WeatherApiConfig()
    try:
        return fetch_upstream_data(start_time, end_time, page, page_size, config), 200
    except UpstreamError as exc:
        return {
            "code": 502,
            "message": str(exc),
            "source": "upstream",
            "mock": False,
            "config": get_runtime_config_snapshot(),
            "result": {"list": [], "total": 0, "page": page, "page_size": page_size},
        }, 502
