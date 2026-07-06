# v1.8.0

## 主看板性能优化

1. 主看板数据加载拆分为“请求服务器数据库 / 处理监测记录 / 生成小时聚合数据 / 分批渲染图表”四个阶段，并在页面显示进度条，避免用户误以为页面卡死。
2. 表格改为前端分页渲染，默认每页只渲染 100 条记录；总记录仍保留，避免 Element Plus 一次性渲染 5000 条以上导致页面冻结。
3. 图表小时聚合从每个图表单独计算，改为主看板统一计算一次；8 个图表共享同一份小时聚合数据，显著减少重复遍历。
4. 图表改为分批延迟渲染，每张图错开约 90ms；ECharts 禁用动画并使用 lazyUpdate，降低首屏渲染阻塞。
5. 图表和表格增加局部 loading，不再使用大面积阻塞式加载，主页面在数据请求和渲染期间仍可滚动和响应。

## 部署建议

无需修改 Nginx。部署后重新构建前端并重启后端：

```bash
cd /opt/atmosphere-borad/atmosphere-borad-optimized
unzip -o /path/to/atmosphere-borad-optimized-v1.8.0.zip -d /opt/atmosphere-borad
./build-frontend-linux.sh
sudo systemctl daemon-reload
sudo systemctl restart atmosphere-borad
sudo systemctl reload nginx
```


---

# v1.8.0

1. 启动前缓存检查器增加“缓存巡检与修复”阶段：先扫描 SQLite 中已有的逐日覆盖结果，再强制刷新缺失覆盖天、已覆盖但 0 记录天，以及最近若干天，避免旧缓存把实际有数据的日期错误标记为 `covered_no_records`。
2. 后端请求第三方接口的超时时间设置为最低 60 秒；即使 `.env` 中遗留 `WEATHER_TIMEOUT_SECONDS=10`，运行时也会提升到 60 秒。
3. 新增运行期后台缓存巡检线程：服务运行后定期扫描最近若干天并修复缓存，配合实时刷新线程，避免页面长期停留在部署时刻的数据。
4. `/api/borad/cache/progress` 增加 `cache_audit` 状态；新增 `/api/borad/cache/audit` 手动触发巡检接口。
5. 版本号更新为 `1.8.0`。

建议 `.env` 增加：

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

# v1.8.0

## 关键修复

1. 修复第三方接口在系统后端中拉不到数据的问题。
   - 后端请求第三方接口时默认禁用系统代理环境变量，避免 Windows/Clash 等环境把请求转到 127.0.0.1:7897 后超时。
   - 新增 `WEATHER_UPSTREAM_USE_SYSTEM_PROXY=false`，确实需要系统代理时可改为 `true`。
   - 默认上游请求超时调整为 60 秒，适配单日多页接口 10–25 秒/页的实际响应速度。

2. 保持和独立 notebook 验证一致的第三方接口调用方式。
   - URL 仍为 `/api/getDeviceData/{page}/{page_size}`。
   - Header 仍为 `Authorization`、`timestamp`。
   - Query 仍为 `search[start_time]`、`search[end_time]`。
   - 默认 `WEATHER_UPSTREAM_TIME_FORMAT=auto`，优先毫秒时间戳。

3. 修复服务长时间运行后数据停留在部署时刻的问题。
   - 新增后端实时增量刷新线程。
   - 默认每 600 秒强制刷新最近 1 天数据并写入 SQLite。
   - 查询时间范围触及最近实时窗口时，会启动/保持实时刷新线程。
   - 启动前缓存检查时，最近实时窗口不再直接复用旧缓存，而会重新请求第三方接口更新缓存。

4. 健康检查和配置快照增强。
   - `/api/borad/health` 返回版本 `1.8.0`。
   - 配置快照中增加上游代理、实时刷新状态、刷新间隔等字段。
   - 缓存检查器控制台打印 timeout 和 proxy_env，便于排查请求是否仍走代理。

## 新增配置

```env
WEATHER_TIMEOUT_SECONDS=60
WEATHER_UPSTREAM_USE_SYSTEM_PROXY=false

WEATHER_LIVE_REFRESH_ENABLED=true
WEATHER_LIVE_REFRESH_INTERVAL_SECONDS=600
WEATHER_LIVE_REFRESH_DAYS=1
WEATHER_LIVE_REFRESH_FORCE_CURRENT_DAYS=true
WEATHER_LIVE_REFRESH_RUN_ON_STARTUP=true
```

## 验证

- `python3 -m py_compile backend/data_service.py backend/app.py backend/cache_checker.py` 通过。
- `node --check vite.config.js` 与 `node --check src/api/data.js` 通过。
- 已确认后端上游请求 session 默认 `trust_env=False`。
