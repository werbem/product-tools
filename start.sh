#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════╗"
echo "║   AI 竞品分析助手 — 启动脚本              ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ── Check Python ──
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ python3 not found${NC}"
    echo "Please install Python 3.12+ from https://www.python.org/downloads/"
    exit 1
fi
echo -e "${GREEN}✅ Python $(python3 --version | cut -d' ' -f2)${NC}"

# ── Check Node.js ──
if ! command -v node &> /dev/null; then
    echo -e "${RED}❌ node not found${NC}"
    echo "Please install Node.js 22+ from https://nodejs.org/"
    exit 1
fi
echo -e "${GREEN}✅ Node.js $(node --version | cut -d'v' -f2)${NC}"

# ── Check pnpm ──
if ! command -v pnpm &> /dev/null; then
    echo -e "${YELLOW}⚠ pnpm not found, installing...${NC}"
    npm install -g pnpm
fi
echo -e "${GREEN}✅ pnpm $(pnpm --version)${NC}"

echo ""

# ── Install dependencies ──
echo "📦 Installing backend dependencies..."
cd "$ROOT_DIR/backend"
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install -q -r requirements.txt
echo -e "${GREEN}✅ Backend dependencies installed${NC}"

echo ""
echo "📦 Installing frontend dependencies..."
cd "$ROOT_DIR/frontend"
pnpm install --frozen-lockfile 2>/dev/null || pnpm install
echo -e "${GREEN}✅ Frontend dependencies installed${NC}"

echo ""

# ── Build frontend if not built ──
if [ ! -d "$ROOT_DIR/frontend/.next" ]; then
    echo "🏗️  Building frontend..."
    cd "$ROOT_DIR/frontend"
    pnpm build
    echo -e "${GREEN}✅ Frontend built${NC}"
    echo ""
fi

# ── Kill any existing processes on target ports ──
echo "🧹 Cleaning ports 8000 and 3000..."
lsof -ti:8000 -ti:3000 | xargs kill -9 2>/dev/null || true
sleep 1

# ── Start services ──
echo "🚀 Starting services... (Ctrl+C to stop)"
echo ""

# 本地运行时后端在 localhost:8000；Docker Compose 会覆盖为 http://backend:8000
export API_URL="${API_URL:-http://localhost:8000}"

cleanup() {
    echo ""
    echo "🛑 Shutting down..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "👋 Goodbye!"
    exit 0
}
trap cleanup SIGINT SIGTERM

# Start backend
cd "$ROOT_DIR/backend"
source venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo -e "  Backend:  ${GREEN}http://localhost:8000${NC} (PID: $BACKEND_PID)"

# Start frontend
cd "$ROOT_DIR/frontend"
pnpm dev &
FRONTEND_PID=$!
echo -e "  Frontend: ${GREEN}http://localhost:3000${NC} (PID: $FRONTEND_PID)"

echo ""
echo "Press Ctrl+C to stop all services."

wait
