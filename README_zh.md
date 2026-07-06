# atmosphere-borad-optimized

当前版本：v1.7.9。

## v1.7.9 缓存巡检与运行期刷新

本版用于修复“独立 notebook 单日分页接口可正常返回，但系统缓存仍显示日期缺失”的问题。根因通常是旧缓存已经把某些日期写成 `covered_no_records`，后续普通查询会误信旧覆盖记录，不再强制请求第三方接口。

启动流程现在为：

```text
启动脚本 / systemd ExecStartPre
  ↓
cache_checker.py 按最近 30 天预缓存
  ↓
扫描 SQLite 逐日缓存状态
  ↓
强制刷新：缺失覆盖日期、0记录日期、最近若干日期
  ↓
打印最终 scan 结果
  ↓
启动 Flask 后端
  ↓
运行期后台 cache audit + live refresh 定时刷新
```

关键配置：

```env
WEATHER_TIMEOUT_SECONDS=60
WEATHER_UPSTREAM_USE_SYSTEM_PROXY=false
WEATHER_STARTUP_CACHE_AUDIT_ENABLED=true
WEATHER_STARTUP_CACHE_AUDIT_REFRESH_ZERO_DAYS=true
WEATHER_STARTUP_CACHE_AUDIT_REFRESH_MISSING_DAYS=true
WEATHER_STARTUP_CACHE_AUDIT_FORCE_RECENT_DAYS=7
WEATHER_BACKGROUND_CACHE_AUDIT_ENABLED=true
WEATHER_BACKGROUND_CACHE_AUDIT_INTERVAL_SECONDS=3600
WEATHER_BACKGROUND_CACHE_AUDIT_DAYS=7
```

部署后检查：

```bash
curl http://127.0.0.1:52000/api/borad/health
curl http://127.0.0.1:52000/api/borad/cache/progress
curl http://127.0.0.1:52000/api/borad/cache/audit
```

`/api/borad/cache/progress` 中应能看到 `cache_audit`、`live_refresh` 和 `cache` 三类状态。

---

# 荆襄气象监测看板优化版

当前版本：v1.7.9。

## v1.7.9 数据拉取与实时更新修复

本版修复的核心问题是：独立 notebook 可以按页成功拉取 2026-07-03 全天 1408 条数据，但系统后端拉取失败。原因通常是后端 `requests` 自动读取系统代理环境变量，导致请求走到本地代理 `127.0.0.1:7897`，而不是直接访问 `weather-api.jsjldzkj.com`。v1.7.9 后端默认禁用系统代理。

推荐 `.env`：

```env
WEATHER_TIMEOUT_SECONDS=60
WEATHER_UPSTREAM_USE_SYSTEM_PROXY=false
WEATHER_UPSTREAM_TIME_FORMAT=auto
WEATHER_HMAC_MODE=json

WEATHER_LIVE_REFRESH_ENABLED=true
WEATHER_LIVE_REFRESH_INTERVAL_SECONDS=600
WEATHER_LIVE_REFRESH_DAYS=1
WEATHER_LIVE_REFRESH_FORCE_CURRENT_DAYS=true
WEATHER_LIVE_REFRESH_RUN_ON_STARTUP=true
```

如服务器必须通过代理访问第三方接口，再把 `WEATHER_UPSTREAM_USE_SYSTEM_PROXY` 改成 `true`。

为了避免服务运行几天后仍显示部署时刻的数据，系统现在会在后端启动后开启实时刷新线程，默认每 10 分钟强制刷新最近 1 天数据并写入 SQLite。页面打开时优先读取 SQLite，因此只要后端持续运行，页面会读取后台持续更新后的缓存数据。


## v1.7.9 缓存管理页面

缓存控制已从主看板拆分到独立页面，主看板不会显示缓存重建、云端刷新、缓存进度等控制项。需要管理服务器 SQLite 缓存时，直接访问：

```text
http://localhost:5173/cache-admin
```

服务器部署后访问：

```text
https://jinxiang.eatrice.cn/cache-admin
```

该页面可以查看最近区间的逐日缓存状态、记录数、首末记录时间、活跃小时分布，并支持按日重新拉取、按日删除、查看具体小时记录和删除单条缓存记录。该页面没有从主看板入口，避免现场展示时误操作。


## 本版关键调整

1. 启动脚本在启动 Flask 和前端前，会先运行 `backend/cache_checker.py`。
2. 缓存检查器会按自然日分块拉取最近 30 天数据，并写入服务器 SQLite 数据库。
3. 缓存未达到最低记录数时，默认直接阻止后端启动，避免页面打开后只有空表格。
4. 第三方接口仍按原仓库方式请求：`/getDeviceData/{page}/{page_size}`、`Authorization + timestamp`、`search[start_time]` 和 `search[end_time]`。
5. 长时间范围不再一次性请求第三方接口，而是拆成每天一个请求窗口；这可以规避第三方接口对两周、一个月等大范围查询返回空页的问题。
6. 前端趋势图继续按日期选择器区间显示，数据点按小时聚合均值。
7. 缓存统一放在服务器 SQLite 数据库，不使用浏览器 localStorage，不使用 mock 数据。

## 启动流程

```text
start-windows.bat / start-linux.sh
  ↓
安装依赖
  ↓
运行 backend/cache_checker.py
  ↓
按天拉取最近 30 天数据并写入 runtime_cache/weather_cache.sqlite3
  ↓
缓存记录数达到要求后启动 Flask 52000
  ↓
启动 Vite 5173 或由 Nginx 443 访问生产 dist
```

如果缓存检查失败，后端不会启动。此时应先检查 `.env` 中的密钥、第三方接口时间格式、网络连通性和控制台日志。

## 推荐 `.env`

```env
VITE_API_BASE_URL=/api
VITE_API_TIMEOUT=30000
VITE_OPEN_BROWSER=true

BACKEND_HOST=0.0.0.0
BACKEND_PORT=52000
FLASK_DEBUG=false
CORS_ALLOW_ORIGIN=*

WEATHER_API_BASE_URL=http://weather-api.jsjldzkj.com/api
WEATHER_APP_ID=dashboard
WEATHER_SECRET_KEY=你的真实密钥
WEATHER_TIMEOUT_SECONDS=30
WEATHER_HMAC_MODE=json
WEATHER_UPSTREAM_TIME_FORMAT=auto

WEATHER_ALLOW_MOCK=false
WEATHER_FORCE_MOCK=false

WEATHER_CACHE_ENABLED=true
WEATHER_CACHE_BACKEND=sqlite
WEATHER_CACHE_DB=runtime_cache/weather_cache.sqlite3
WEATHER_CACHE_TABLE=weather_cache_v174
WEATHER_CACHE_MAX_AGE_SECONDS=0

WEATHER_UPSTREAM_PAGE_SIZE=500
WEATHER_UPSTREAM_MAX_PAGES=160
WEATHER_UPSTREAM_MAX_RECORDS=300000
WEATHER_UPSTREAM_TRUST_TOTAL_HINT=false

WEATHER_PREFETCH_SPLIT_DAYS=true
WEATHER_PREFETCH_CHUNK_DAYS=1
WEATHER_PRESTART_CACHE_CHECK_ENABLED=true
WEATHER_PRESTART_CACHE_CHECK_DAYS=30
WEATHER_PRESTART_CACHE_CHECK_FORCE=false
WEATHER_PRESTART_CACHE_STRICT=true
WEATHER_PRESTART_CACHE_MIN_RECORDS=1

WEATHER_STARTUP_PREFETCH_ENABLED=false
WEATHER_STARTUP_PREFETCH_DAYS=30
WEATHER_STARTUP_PREFETCH_FORCE=false
```

其中 `WEATHER_CACHE_TABLE=weather_cache_v174` 会使用新的 SQLite 表，避免旧版本生成的错误覆盖缓存继续生效。

## 本地启动

Windows：

```bat
start-windows.bat
```

Linux：

```bash
chmod +x start-linux.sh
./start-linux.sh
```

## 单独检查缓存

```bash
cd /opt/atmosphere-borad/atmosphere-borad-optimized
source .venv/bin/activate
python backend/cache_checker.py --days 30 --force
```

如果希望只检查最近 14 天：

```bash
python backend/cache_checker.py --days 14 --force
```

## 服务器部署

生产环境仍建议：公网只开放 443，Nginx 服务前端 dist，并把 `/api/borad/` 反向代理到 Flask 52000。

```nginx
location /api/borad/ {
    proxy_pass http://127.0.0.1:52000/api/borad/;
    proxy_connect_timeout 30s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;
}
```

更新部署：

```bash
cd /opt/atmosphere-borad/atmosphere-borad-optimized
unzip -o /path/to/atmosphere-borad-optimized-v1.7.4.zip -d /opt/atmosphere-borad
./build-frontend-linux.sh
sudo systemctl daemon-reload
sudo systemctl restart atmosphere-borad
sudo systemctl reload nginx
```

systemd 推荐在 `ExecStartPre` 中加入缓存检查：

```ini
ExecStartPre=/opt/atmosphere-borad/atmosphere-borad-optimized/.venv/bin/python /opt/atmosphere-borad/atmosphere-borad-optimized/backend/cache_checker.py
ExecStart=/opt/atmosphere-borad/atmosphere-borad-optimized/.venv/bin/python app.py
```

## 常见问题

如果缓存检查器显示 `records=0`，重点排查：

```text
1. WEATHER_SECRET_KEY 是否填写真实值。
2. WEATHER_HMAC_MODE 是否应为 json。
3. WEATHER_UPSTREAM_TIME_FORMAT 是否应固定为 ms。
4. 第三方接口在最近 30 天内是否确实有设备数据。
5. 当前网络是否能访问 weather-api.jsjldzkj.com。
```

如果旧缓存影响结果，可以删除数据库或更换表名：

```bash
rm -f runtime_cache/weather_cache.sqlite3
```

或在 `.env` 中设置新表名：

```env
WEATHER_CACHE_TABLE=weather_cache_v174
```

## v1.7.9 本地调试注意事项

如果页面控制台出现 `/api/borad/cache/progress 404`，同时 `/api/borad/1/5000` 返回 `Upstream request timed out after 10.0s`，通常说明 52000 端口上仍然运行着旧版 Flask 后端。此时前端虽然是新版本，但 Vite 代理命中了旧后端，因此会出现“缓存已经完成但页面仍然去请求第三方接口”的现象。

v1.7.9 的启动脚本会自动清理 `BACKEND_PORT` 上的旧监听进程，再启动新后端，并通过 `/api/borad/health` 校验 `version=1.7.9`。如不希望脚本自动结束旧进程，可设置：

```bash
SKIP_KILL_BACKEND_PORT=true
```

Windows 本地测试建议直接关闭旧的 `atmosphere-backend` 命令行窗口后重新双击 `start-windows.bat`。启动后检查：

```text
http://127.0.0.1:52000/api/borad/health
```

返回中应包含：

```json
"version": "1.7.9"
```

## v1.7.9 启动前缓存扫描

系统启动前会先运行 `backend/cache_checker.py`。缓存完成后，检查器会继续扫描服务器 SQLite 数据库，并在后端控制台打印逐日结果：日期、覆盖状态、记录数、首末记录时间和活跃小时。该信息只打印到控制台，不在前端显示，用于判断图表中的空白日期是缓存缺失还是第三方接口当天确实没有数据。

推荐配置：

```env
WEATHER_PRESTART_CACHE_SCAN_ENABLED=true
```

前端已移除“缓存当前区间”“强制重建缓存”“云端刷新”和缓存进度面板，避免部署后的巡检页面误操作。
