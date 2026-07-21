# 🌐 公网访问指南

通过 Cloudflare Tunnel 将本地项目暴露到公网，无需购买服务器或域名。

---

## 第一步：安装 cloudflared

### macOS

```bash
brew install cloudflared
```

### Windows

1. 打开 [Cloudflare Tunnel 下载页](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
2. 下载 Windows 版本
3. 双击安装

### Linux

```bash
curl -L https://github.com/cloudflare/cloudflare-go/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

---

## 第二步：启动本地项目

```bash
# 进入项目目录
cd staff-ai-agent-review-1-2

# 一键启动（首次启动需等候 1-2 分钟安装依赖）
./start_demo.sh

```

> ⚠️ 确保终端不要关闭，服务需一直运行。

启动成功后应看到：
```
✅ 后端就绪
Frontend: http://localhost:3000
Backend:  http://localhost:8000
```

---

## 第三步：创建 Tunnel

打开一个新终端窗口，执行：

```bash
cloudflared tunnel --url http://localhost:3000
```

稍等片刻，终端会显示类似：

```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://example-pineapple-tackle.trycloudflare.com                                        |
+--------------------------------------------------------------------------------------------+
```

**那个 `https://xxx.trycloudflare.com` 就是你的公网地址。**

---

## 第四步：分享给别人

把上一步得到的 URL 发给任何人，对方在浏览器打开即可访问。

> 💡 URL 格式：`https://<随机名>.trycloudflare.com`

---

## 关闭公网访问

在运行 `cloudflared` 的终端按 `Ctrl + C` 即可关闭 Tunnel。之后那个公网地址立即失效。

关闭本地项目：
```bash
docker compose down
```

---

## ⚠️ 注意事项

| 事项 | 说明 |
|------|------|
| **不要暴露 API Key** | 启动脚本默认使用 Demo 模式，不会调用真实 AI API |
| **链接一次性** | 每次启动 Tunnel 会生成新的随机 URL |
| **服务依赖性** | 本地电脑和 Docker 必须保持运行 |
| **有效期** | Tunnel 在关闭前一直有效 |

---