#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     AI 竞品分析助手 — 真实 AI 模式启动脚本    ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Check Docker ──
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker 未安装${NC}"
    echo "请先安装 Docker Desktop: https://www.docker.com/products/docker-desktop"
    exit 1
fi
echo -e "${GREEN}✅ Docker $(docker --version | cut -d' ' -f3 | cut -d',' -f1)${NC}"

if ! docker compose version &> /dev/null; then
    echo -e "${RED}❌ Docker Compose 不可用${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker Compose${NC}"

# ── 2. Check .env and API Key ──
if [ ! -f ".env" ]; then
    echo ""
    echo -e "${YELLOW}⚠ .env 文件不存在，从 .env.example 创建...${NC}"
    cp .env.example .env
fi

# Load current API key from .env
source .env 2>/dev/null || true

if [ -z "$OPENAI_API_KEY" ] || [ "$OPENAI_API_KEY" = "sk-your-key-here" ]; then
    echo ""
    echo -e "${RED}❌ 未配置 OPENAI_API_KEY${NC}"
    echo ""
    echo "请在 .env 文件中设置你的 API Key："
    echo ""
    echo "  OpenAI:  OPENAI_API_KEY=sk-xxx"
    echo "           OPENAI_MODEL=gpt-4o-mini"
    echo ""
    echo "  DeepSeek: OPENAI_API_KEY=sk-xxx"
    echo "            OPENAI_BASE_URL=https://api.deepseek.com"
    echo "            OPENAI_MODEL=deepseek-chat"
    echo ""
    echo "✏️  编辑 .env 文件填入 Key 后重新运行: ./start_live.sh"
    exit 1
fi
echo -e "${GREEN}✅ OPENAI_API_KEY 已配置${NC}"

# ── 3. Configure for real AI mode ──
export DEMO_MODE=false

# ── 4. Stop existing containers ──
echo ""
echo "🧹 清理旧容器..."
docker compose down 2>/dev/null || true

# ── 5. Start services ──
echo ""
echo "🚀 启动服务（真实 AI 模式）..."
DEMO_MODE=false docker compose up -d --build 2>&1 | grep -v "^$"

# ── 6. Wait for healthy ──
echo ""
echo -n "⏳ 等待服务就绪"
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}✅ 后端就绪（LLM: 真实 AI）${NC}"
        break
    fi
    echo -n "."
    sleep 2
done

# ── 7. Show result ──
echo ""
echo -e "${CYAN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║              启动成功！                        ║${NC}"
echo -e "${CYAN}╠════════════════════════════════════════════════╣${NC}"
echo -e "${CYAN}║                                                ║${NC}"
echo -e "${CYAN}║  Frontend: ${GREEN}http://localhost:3000${CYAN}                 ║${NC}"
echo -e "${CYAN}║  Backend:  ${GREEN}http://localhost:8000${CYAN}                 ║${NC}"
echo -e "${CYAN}║  模式:     ${GREEN}🤖 真实 AI（DeepSeek/OpenAI）${CYAN}        ║${NC}"
echo -e "${CYAN}║                                                ║${NC}"
echo -e "${CYAN}║  📝 开始分析：点击首页「开始分析」输入公司名   ║${NC}"
echo -e "${CYAN}║  🔧 查看日志：docker compose logs -f           ║${NC}"
echo -e "${CYAN}║  🛑 停止服务：docker compose down              ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
echo ""
