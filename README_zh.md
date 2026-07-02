# 荆襄气象监测看板优化版

当前版本：v1.4.0。

## 本版关键调整

1. 页面打开后立即请求云端上游数据，不再返回或展示本地模拟数据。
2. 云端数据加载失败时，前端弹窗提示失败原因，并自动重试，最多 3 次。
3. 前端接口路径恢复为原仓库拼写：`/api/borad/{page}/{page_size}`，用于对齐现有 Nginx 配置。
4. 健康检查接口新增兼容路径：`/api/borad/health`，可以被你当前的 `location /api/borad/` 直接转发。
5. 服务端部署口径统一：公网只开放 HTTPS 443；Flask 后端只监听服务器内网端口 52000；5173 只用于本地开发调试。
6. 上游请求超时时间默认 30 秒。
7. 移动端图表继续保留 v1.3.1 的紧凑布局优化。

## 端口使用原则

生产环境不需要把 Nginx 转发到 5173。5173 是 Vite 本地开发服务器端口，只适用于本地调试。

服务器部署时推荐如下结构：

```text
用户浏览器 https://jinxiang.eatrice.cn:443
        ↓
Nginx 静态文件 root /opt/borad-vue3/dist
        ↓
/api/borad/ 反向代理到 http://127.0.0.1:52000/api/borad/
        ↓
Flask 后端 52000
        ↓
weather-api.jsjldzkj.com 云端接口
```

## 与你当前 Nginx 配置的对齐方式

你当前的配置可以继续使用。新版前端只调用：

```text
/api/borad/1/20
/api/borad/health
```

这两个路径都会命中：

```nginx
location /api/borad/ {
    proxy_pass http://127.0.0.1:52000/api/borad/;
}
```

包内也提供了参考配置：

```text
deploy/nginx-jinxiang.conf
```

其中加入了 30 秒代理超时：

```nginx
proxy_connect_timeout 30s;
proxy_send_timeout 30s;
proxy_read_timeout 30s;
```

## 本地开发启动

Linux：

```bash
chmod +x start-linux.sh
./start-linux.sh
```

Windows：

```bat
start-windows.bat
```

本地开发时浏览器会打开：

```text
http://localhost:5173/
```

Vite 会把 `/api` 代理到本机 Flask 后端 `http://127.0.0.1:52000`。

## 服务器部署步骤

1. 配置环境变量。推荐复制 `.env.example` 为 `.env`，并填写真实密钥。

```env
VITE_API_BASE_URL=/api
VITE_API_TIMEOUT=30000

BACKEND_HOST=0.0.0.0
BACKEND_PORT=52000
FLASK_DEBUG=false
CORS_ALLOW_ORIGIN=*

WEATHER_API_BASE_URL=http://weather-api.jsjldzkj.com/api
WEATHER_APP_ID=dashboard
WEATHER_SECRET_KEY=<你的真实密钥>
WEATHER_TIMEOUT_SECONDS=30
WEATHER_ALLOW_MOCK=false
WEATHER_FORCE_MOCK=false
WEATHER_HMAC_MODE=json
```

2. 构建前端。

```bash
chmod +x build-frontend-linux.sh
./build-frontend-linux.sh
```

3. 把 `dist` 部署到 Nginx root。

```bash
sudo mkdir -p /opt/borad-vue3
sudo rm -rf /opt/borad-vue3/dist
sudo cp -r dist /opt/borad-vue3/dist
```

4. 启动后端。

```bash
chmod +x start-backend-linux.sh
./start-backend-linux.sh
```

生产环境建议用 systemd 或 supervisor 托管后端进程。

5. 验证健康检查。

```bash
curl https://jinxiang.eatrice.cn/api/borad/health
```

需要看到：

```json
"has_secret_key": true
```

6. 验证数据接口。

```bash
curl "https://jinxiang.eatrice.cn/api/borad/1/20?start_time=1717200000000&end_time=1717286400000"
```

## 重要说明

当前版本默认不启用模拟数据。云端接口失败、密钥为空、签名错误、DNS 不通、Nginx 代理错误或上游超时，前端会直接弹窗提示并重试，不会再用本地假数据填充页面。
