#!/bin/bash

echo "======================================="
echo "  A股资金流入看板 - 环境安装脚本"
echo "======================================="
echo

# 检查前端dist目录
echo "[1/5] 检查前端dist目录..."
if [ ! -d "../frontend/dist" ]; then
    echo "错误: 前端dist目录不存在，请先在本地构建前端"
    echo "构建命令: cd ../frontend && npm install && npm run build"
    exit 1
fi
echo "前端dist目录已存在"

# 检查 Docker
echo
echo "[2/5] 检查 Docker..."
if ! command -v docker &> /dev/null; then
    echo "错误: 未检测到 Docker，请先安装 Docker"
    echo "安装命令: sudo apt-get install docker.io"
    exit 1
fi
echo "Docker 已安装"

echo

echo "[3/5] 检查 Docker Compose..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "错误: 未检测到 Docker Compose"
    exit 1
fi
echo "Docker Compose 已安装"

echo

echo "[4/5] 构建和启动 Docker 容器..."
cd "$(dirname "$0")"

if command -v docker-compose &> /dev/null; then
    docker-compose up -d --build
else
    docker compose up -d --build
fi

if [ $? -ne 0 ]; then
    echo "错误: Docker 容器启动失败"
    exit 1
fi

echo

echo "[5/5] 检查服务状态..."
sleep 5

echo

echo "======================================="
echo "  安装完成！"
echo "======================================="
echo
echo "服务地址: http://服务器IP:80"
echo
echo "使用以下命令管理服务:"
echo "  启动: docker compose down"
echo "  停止: docker compose up -d"
echo "  重启: docker-compose restart"
echo "  查看日志: docker-compose logs -f"
echo
echo "注意: 如需更新前端，只需在本地重新构建并复制dist目录到服务器即可"
echo
