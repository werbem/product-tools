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
echo -e "${CYAN}║       AI 竞品分析助手 — Demo 启动脚本          ║${NC}"
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

# ── 2. Check .env ──
if [ ! -f ".env" ]; then
    echo ""
    echo -e "${YELLOW}⚠ .env 文件不存在，从 .env.example 创建...${NC}"
    cp .env.example .env
    echo -e "${GREEN}✅ .env 已创建（Demo 模式，无需 API Key）${NC}"
    echo ""
    echo -e "${YELLOW}💡 如需启用真实 AI 分析，编辑 .env 填入 OPENAI_API_KEY${NC}"
else
    echo -e "${GREEN}✅ .env 已存在${NC}"
fi

# ── 3. Configure for Demo mode ──
export DEMO_MODE=true

# ── 4. Stop existing containers ──
echo ""
echo "🧹 清理旧容器..."
docker compose down 2>/dev/null || true

# ── 5. Start services ──
echo ""
echo "🚀 启动服务..."
DEMO_MODE=true docker compose up -d --build 2>&1 | grep -v "^$"

# ── 6. Wait for healthy ──
echo ""
echo -n "⏳ 等待服务就绪"
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}✅ 后端就绪${NC}"
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
echo -e "${CYAN}║                                                ║${NC}"
echo -e "${CYAN}║  模式:     ${GREEN}📋 Demo 模式（固定案例「抖音 vs 快手」）${CYAN}║${NC}"
echo -e "${CYAN}║  📋 体验 Demo：点击首页「体验 Demo」按钮       ║${NC}"
echo -e "${CYAN}║  🔧 查看日志：docker compose logs -f           ║${NC}"
echo -e "${CYAN}║  🛑 停止服务：docker compose down              ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════╝${NC}"
echo ""
