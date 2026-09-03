# Phase 1 部署与运行指南

本文档说明本地或单机部署 **AI 竞品分析助手** 的最小运行要求（Copilot Workspace + Conversation SSE）。

## 环境变量

在 `backend/.env` 或项目根 `.env` 中配置（参考 `backend/.env.example`）：

```bash
# LLM（必填，真实模式）
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
# OPENAI_BASE_URL=https://api.deepseek.com   # 可选，兼容 API

# 搜索（推荐）
TAVILY_API_KEY=tvly-your-key-here

# 数据目录（可选，默认 ./data）
APP_DATA_DIR=./data

# 强制关闭 Demo（推荐生产/验收）
DEMO_MODE=false
```

其他常用变量：`APP_PORT`、`FRONTEND_URL`、`DATABASE_URL`、`LOG_LEVEL`。

## 启动方式

### Backend（必须单 worker）

Conversation SSE 与内存 EventBus 要求 **单进程**：

```bash
cd backend
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

### Frontend

开发模式（修改代码后）：

```bash
cd frontend
rm -rf .next && pnpm dev
```

生产模式：

```bash
cd frontend
pnpm build && pnpm start
```

> **注意：** 若先执行 `pnpm build` 再 `pnpm dev`，需删除 `.next`，否则 `/workspace` 可能出现 500（chunk 缺失）。

### 使用 start.sh

项目根目录：

```bash
./start.sh
```

脚本会：

1. 检查 Python / Node / pnpm
2. 安装 backend、frontend 依赖
3. **删除 `frontend/.next`**（避免 dev/build 缓存混用）
4. 清理 8000、3000 端口
5. 启动 backend（`127.0.0.1:8000`）与 frontend（`3000`）

访问：

- 主入口：<http://localhost:3000/workspace>
- 旧版表单：<http://localhost:3000/classic>
- 健康检查：<http://localhost:8000/api/health>（`mock: false` 表示真实 LLM）

## 分析模式

| 模式 | 预计耗时 | 能力 |
|------|----------|------|
| **快速** | 约 6 分钟 | 13 章报告；跳过 Compare / Insight / Strategy / Review |
| **完整** | 约 12 分钟 | 全链路：对比、洞察、战略、审阅 |

在 Workspace 新建对话时选择模式；旧版 `/classic` 表单默认为完整模式。

## 已知限制

1. **单 worker**：多 worker 会导致 Conversation SSE / EventBus 状态不一致。
2. **JSON File Store**：Copilot 数据（项目、对话、Artifact）存于 `APP_DATA_DIR`，非关系型数据库。
3. **SSE 无历史 replay**：刷新 Conversation 页后需依赖 REST API 拉取消息；进行中的任务可重新订阅 progress。
4. **真实 LLM**：验收与生产需配置 `OPENAI_API_KEY`；无 Key 时可能进入 Demo 模式。
5. **Report metadata**：新报告在 `GET /api/reports/{id}` 的 `metadata` 字段含 `generation_mode`、`analysis_mode`；旧报告无此字段。

## 快速验收

```bash
# Backend — Router 金标 + 路由单测
cd backend && PYTHONPATH=. python3 -m pytest \
  tests/unit/test_router_goldens_pr_v26.py \
  tests/unit/test_router_service_pr_v21.py \
  tests/unit/test_intent_mapper_routing.py \
  -q

# Backend — API 集成
cd backend && PYTHONPATH=. python3 -m pytest tests/integration/test_conversation_api.py tests/integration/test_api.py -q

# Frontend
cd frontend && pnpm exec tsc --noEmit && pnpm build
```

手动检查：

- `/` → 重定向到 `/workspace`
- `/classic` → 旧版表单可提交
- Conversation 路径可创建 Artifact
- `GET /api/reports/{task_id}` 含 `metadata.generation_mode`（新报告）
