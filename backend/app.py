from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Iterable, Tuple

from flask import Flask, jsonify, request


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent


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

from data_service import get_weather_data, get_runtime_config_snapshot  # noqa: E402


def create_app() -> Flask:
    app = Flask(__name__)

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = os.getenv("CORS_ALLOW_ORIGIN", "*")
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, timestamp"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    def _health_payload():
        return {
            "code": 0,
            "message": "ok",
            "service": "atmosphere-borad-backend",
            "time_ms": int(time.time() * 1000),
            "config": get_runtime_config_snapshot(),
        }

    @app.route("/api/health", methods=["GET"])
    @app.route("/api/borad/health", methods=["GET"])
    @app.route("/api/board/health", methods=["GET"])
    def health():
        return jsonify(_health_payload())

    def _parse_pagination(page: int, page_size: int) -> Tuple[int, int]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        return page, page_size

    def _handle_weather(page: int, page_size: int):
        page, page_size = _parse_pagination(page, page_size)
        start_time = request.args.get("start_time") or request.args.get("startTime")
        end_time = request.args.get("end_time") or request.args.get("endTime")
        payload, status = get_weather_data(start_time, end_time, page, page_size)
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

    return app


def main() -> None:
    app = create_app()
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    port = int(os.getenv("BACKEND_PORT", "52000"))
    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
