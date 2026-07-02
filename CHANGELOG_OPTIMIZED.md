# 优化记录

## v1.4.0

- 前端数据接口恢复使用原仓库路径拼写 `/api/borad/{page}/{page_size}`，对齐服务器现有 Nginx 配置。
- 新增后端健康检查兼容路径 `/api/borad/health`，无需新增 Nginx location 即可访问。
- 页面打开后立即加载云端数据。
- 取消本地 mock 数据降级展示；上游失败时直接返回错误。
- 云端数据加载失败时前端弹窗提示，并自动重试，最多 3 次。
- 默认分页大小恢复为 20 条，更接近原仓库请求方式，降低上游接口压力。
- `.env.example` 与 `backend/.env.example` 默认设置 `WEATHER_ALLOW_MOCK=false`。
- 新增 `deploy/nginx-jinxiang.conf`，对齐 `jinxiang.eatrice.cn` 的 HTTPS + Flask 52000 部署方案。
- 新增 `start-backend-linux.sh` 与 `build-frontend-linux.sh`，便于服务器分别构建前端和启动后端。

## v1.3.1

- 移动端图表左右空白专项优化。
- 缩小移动端 ECharts grid、图例、坐标轴标签占位。
- 监听横竖屏变化并重新计算图表布局。

## v1.3.0

- 启动后自动打开 `http://localhost:5173/`。
- 上游请求恢复为原版兼容签名与请求头格式。
- 前后端超时时间改为 30 秒。
- 所有趋势图默认展开。

## v1.2.0

- 修复 `.env` 加载顺序问题。
- 修复暗色主题白色条纹。
- 修复隐藏 tab 中 ECharts 宽度异常。

## v1.1.0

- 增加后端异常处理、健康检查和响应式界面。
