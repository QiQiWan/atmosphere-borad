from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Iterable, Tuple

from flask import Flask, jsonify, request


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
APP_VERSION = "1.8.0"


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def load_dotenv_files(paths: Iterable[Path] | None = None) -> None:
    """Load project .env files before the data service reads configuration.

    The first optimized package only loaded backend/.env after importing the data
    module. Because the dataclass defaults were evaluated at import time, a valid
    .env file could still lead to an empty WEATHER_SECRET_KEY. This loader runs
    before importing the data service and accepts both root-level and backend-level
    .env files.
    """

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
                # Keep explicit process-level variables, but fix empty placeholders.
                if key not in os.environ or os.environ.get(key, "") == "":
                    os.environ[key] = value


load_dotenv_files()

from data_service import (  # noqa: E402
    get_weather_data,
    get_runtime_config_snapshot,
    get_cache_status,
    get_prefetch_progress,
    prefetch_recent_month,
    start_background_prefetch,
    start_recent_month_prefetch,
    get_cache_scan_for_range,
    get_cache_day_detail,
    delete_cache_day,
    delete_cache_record,
    start_live_refresh_loop_once,
    get_live_refresh_state,
    start_background_cache_audit_loop_once,
    get_cache_audit_state,
    audit_and_refresh_cache_range,
)


_PREFETCH_STARTED = False


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return str(value).lower() in {"1", "true", "yes", "on"}


def _startup_prefetch_worker() -> None:
    try:
        result = start_recent_month_prefetch(source="startup")
        print(f"[startup-prefetch] {result}", flush=True)
    except Exception as exc:  # pragma: no cover - defensive service guard
        print(f"[startup-prefetch] failed: {exc}", flush=True)


def start_startup_prefetch_once() -> None:
    global _PREFETCH_STARTED
    if _PREFETCH_STARTED:
        return
    if not _env_bool("WEATHER_STARTUP_PREFETCH_ENABLED", True):
        return
    # Avoid double prefetch when Flask debug reloader starts a parent process.
    debug_enabled = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    if debug_enabled and os.getenv("WERKZEUG_RUN_MAIN") != "true":
        return
    _PREFETCH_STARTED = True
    thread = threading.Thread(target=_startup_prefetch_worker, name="weather-startup-prefetch", daemon=True)
    thread.start()


def create_app() -> Flask:
    app = Flask(__name__)

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ALLOW_ORIGIN", "*")
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, timestamp"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        return response

    def _health_payload():
        return {
            "code": 0,
            "message": "ok",
            "service": "atmosphere-borad-backend",
            "version": APP_VERSION,
            "time_ms": int(time.time() * 1000),
            "config": get_runtime_config_snapshot(),
        }

    @app.route("/api/health", methods=["GET"])
    @app.route("/api/borad/health", methods=["GET"])
    @app.route("/api/board/health", methods=["GET"])
    def health():
        return jsonify(_health_payload())

    @app.route("/api/borad/cache/status", methods=["GET"])
    @app.route("/api/borad/cache/status/", methods=["GET"])
    @app.route("/api/board/cache/status", methods=["GET"])
    @app.route("/api/board/cache/status/", methods=["GET"])
    @app.route("/api/cache/status", methods=["GET"])
    @app.route("/api/cache/status/", methods=["GET"])
    def cache_status():
        return jsonify({
            "code": 0,
            "message": "ok",
            "cache": get_cache_status(),
            "config": get_runtime_config_snapshot(),
        })

    @app.route("/api/borad/cache/prefetch", methods=["POST", "GET"])
    @app.route("/api/borad/cache/prefetch/", methods=["POST", "GET"])
    @app.route("/api/board/cache/prefetch", methods=["POST", "GET"])
    @app.route("/api/board/cache/prefetch/", methods=["POST", "GET"])
    @app.route("/api/cache/prefetch", methods=["POST", "GET"])
    @app.route("/api/cache/prefetch/", methods=["POST", "GET"])
    def cache_prefetch():
        force = _request_bool("force_refresh", False)
        start_time = request.args.get("start_time") or request.args.get("startTime")
        end_time = request.args.get("end_time") or request.args.get("endTime")
        try:
            if start_time and end_time:
                result = start_background_prefetch(start_time, end_time, force_refresh=force, source="manual-range")
            else:
                result = start_recent_month_prefetch(force_refresh=force, source="manual-month")
            return jsonify({"code": 202 if result.get("running") else 0, "message": "prefetch task accepted", "prefetch": result, "config": get_runtime_config_snapshot()}), 202
        except Exception as exc:
            return jsonify({"code": 502, "message": str(exc), "config": get_runtime_config_snapshot()}), 502

    @app.route("/api/borad/cache/progress", methods=["GET"])
    @app.route("/api/borad/cache/progress/", methods=["GET"])
    @app.route("/api/board/cache/progress", methods=["GET"])
    @app.route("/api/board/cache/progress/", methods=["GET"])
    @app.route("/api/cache/progress", methods=["GET"])
    @app.route("/api/cache/progress/", methods=["GET"])
    def cache_progress():
        return jsonify({
            "code": 0,
            "message": "ok",
            "prefetch": get_prefetch_progress(),
            "live_refresh": get_live_refresh_state(),
            "cache_audit": get_cache_audit_state(),
            "cache": get_cache_status(),
            "config": get_runtime_config_snapshot(),
        })

    @app.route("/api/borad/cache/live-refresh", methods=["POST", "GET"])
    @app.route("/api/borad/cache/live-refresh/", methods=["POST", "GET"])
    @app.route("/api/board/cache/live-refresh", methods=["POST", "GET"])
    @app.route("/api/cache/live-refresh", methods=["POST", "GET"])
    def cache_live_refresh():
        state = start_live_refresh_loop_once()
        return jsonify({
            "code": 0,
            "message": "live refresh loop started",
            "live_refresh": state,
            "cache": get_cache_status(),
            "config": get_runtime_config_snapshot(),
        })

    @app.route("/api/borad/cache/audit", methods=["GET", "POST"])
    @app.route("/api/borad/cache/audit/", methods=["GET", "POST"])
    @app.route("/api/board/cache/audit", methods=["GET", "POST"])
    @app.route("/api/cache/audit", methods=["GET", "POST"])
    def cache_audit():
        start_time = request.args.get("start_time") or request.args.get("startTime")
        end_time = request.args.get("end_time") or request.args.get("endTime")
        days_raw = request.args.get("days")
        try:
            if not (start_time and end_time):
                from data_service import get_recent_prefetch_range
                days = int(days_raw) if days_raw not in (None, "") else None
                start_time, end_time = get_recent_prefetch_range(days)
            result = audit_and_refresh_cache_range(start_time, end_time, source="manual-api")
            return jsonify({
                "code": 0 if result.get("ok") else 207,
                "message": result.get("message", "cache audit completed"),
                "audit": result,
                "cache_audit": get_cache_audit_state(),
                "cache": get_cache_status(),
                "config": get_runtime_config_snapshot(),
            }), 200 if result.get("ok") else 207
        except Exception as exc:
            return jsonify({"code": 500, "message": str(exc), "config": get_runtime_config_snapshot()}), 500


    @app.route("/api/borad/cache/scan", methods=["GET"])
    @app.route("/api/borad/cache/scan/", methods=["GET"])
    @app.route("/api/board/cache/scan", methods=["GET"])
    @app.route("/api/board/cache/scan/", methods=["GET"])
    @app.route("/api/cache/scan", methods=["GET"])
    @app.route("/api/cache/scan/", methods=["GET"])
    def cache_scan():
        start_time = request.args.get("start_time") or request.args.get("startTime")
        end_time = request.args.get("end_time") or request.args.get("endTime")
        days_raw = request.args.get("days")
        try:
            days = int(days_raw) if days_raw not in (None, "") else None
            report = get_cache_scan_for_range(start_time, end_time, days)
            status = 500 if report.get("error") else 200
            return jsonify({"code": 0 if status == 200 else 500, "message": report.get("error") or "ok", "scan": report, "config": get_runtime_config_snapshot()}), status
        except Exception as exc:
            return jsonify({"code": 500, "message": str(exc), "config": get_runtime_config_snapshot()}), 500

    @app.route("/api/borad/cache/day/<date_text>", methods=["GET"])
    @app.route("/api/board/cache/day/<date_text>", methods=["GET"])
    @app.route("/api/cache/day/<date_text>", methods=["GET"])
    def cache_day_detail(date_text: str):
        try:
            hour_raw = request.args.get("hour")
            hour = int(hour_raw) if hour_raw not in (None, "", "all") else None
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", request.args.get("pageSize", "100")))
            detail = get_cache_day_detail(date_text, hour=hour, page=page, page_size=page_size)
            status = 500 if detail.get("error") else 200
            return jsonify({"code": 0 if status == 200 else 500, "message": detail.get("error") or "ok", "detail": detail, "config": get_runtime_config_snapshot()}), status
        except Exception as exc:
            return jsonify({"code": 500, "message": str(exc), "config": get_runtime_config_snapshot()}), 500

    @app.route("/api/borad/cache/day/<date_text>/refresh", methods=["GET", "POST"])
    @app.route("/api/board/cache/day/<date_text>/refresh", methods=["GET", "POST"])
    @app.route("/api/cache/day/<date_text>/refresh", methods=["GET", "POST"])
    def cache_day_refresh(date_text: str):
        try:
            start_time = f"{date_text} 00:00:00" if len(date_text) == 10 else date_text
            end_time = f"{date_text} 23:59:59" if len(date_text) == 10 else date_text
            force = _request_bool("force_refresh", True)
            result = start_background_prefetch(start_time, end_time, force_refresh=force, source="cache-admin-day")
            return jsonify({"code": 202 if result.get("running") else 0, "message": "cache refresh task accepted", "prefetch": result, "config": get_runtime_config_snapshot()}), 202
        except Exception as exc:
            return jsonify({"code": 502, "message": str(exc), "config": get_runtime_config_snapshot()}), 502

    @app.route("/api/borad/cache/day/<date_text>/delete", methods=["DELETE", "POST"])
    @app.route("/api/board/cache/day/<date_text>/delete", methods=["DELETE", "POST"])
    @app.route("/api/cache/day/<date_text>/delete", methods=["DELETE", "POST"])
    def cache_day_delete(date_text: str):
        try:
            result = delete_cache_day(date_text)
            status = 500 if result.get("error") else 200
            return jsonify({"code": 0 if status == 200 else 500, "message": result.get("error") or "deleted", "result": result, "config": get_runtime_config_snapshot()}), status
        except Exception as exc:
            return jsonify({"code": 500, "message": str(exc), "config": get_runtime_config_snapshot()}), 500

    @app.route("/api/borad/cache/record/<record_key>/delete", methods=["DELETE", "POST"])
    @app.route("/api/board/cache/record/<record_key>/delete", methods=["DELETE", "POST"])
    @app.route("/api/cache/record/<record_key>/delete", methods=["DELETE", "POST"])
    def cache_record_delete(record_key: str):
        try:
            result = delete_cache_record(record_key)
            status = 500 if result.get("error") else 200
            return jsonify({"code": 0 if status == 200 else 500, "message": result.get("error") or "deleted", "result": result, "config": get_runtime_config_snapshot()}), status
        except Exception as exc:
            return jsonify({"code": 500, "message": str(exc), "config": get_runtime_config_snapshot()}), 500

    def _parse_pagination(page: int, page_size: int) -> Tuple[int, int]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 5000))
        return page, page_size

    def _request_bool(name: str, default: bool = False) -> bool:
        value = request.args.get(name)
        if value in (None, ""):
            return default
        return str(value).lower() in {"1", "true", "yes", "on"}

    def _handle_weather(page: int, page_size: int):
        page, page_size = _parse_pagination(page, page_size)
        start_time = request.args.get("start_time") or request.args.get("startTime")
        end_time = request.args.get("end_time") or request.args.get("endTime")
        force_refresh = _request_bool("force_refresh", False)
        payload, status = get_weather_data(start_time, end_time, page, page_size, force_refresh=force_refresh)
        return jsonify(payload), status

    @app.route("/api/borad/<int:page>/<int:page_size>", methods=["GET", "OPTIONS"])
    def get_borad_data(page: int, page_size: int):
        if request.method == "OPTIONS":
            return "", 204
        return _handle_weather(page, page_size)

    @app.route("/api/board/<int:page>/<int:page_size>", methods=["GET", "OPTIONS"])
    def get_board_data(page: int, page_size: int):
        if request.method == "OPTIONS":
            return "", 204
        return _handle_weather(page, page_size)

    start_live_refresh_loop_once()
    start_background_cache_audit_loop_once()
    start_startup_prefetch_once()
    return app


def main() -> None:
    app = create_app()
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "52000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
