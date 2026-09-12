#!/bin/bash
# TrendZen Pi 节点一键更新重启脚本
set -e
cd ~/TrendZen
echo ">>> 拉取最新代码..."
git fetch origin && git reset --hard origin/main
echo ">>> 重启服务..."
sudo systemctl restart trendzen-edge trendzen-watchdog trendzen-tunnel
sleep 3
echo ">>> 状态检查..."
sudo systemctl is-active trendzen-edge trendzen-watchdog trendzen-tunnel
echo ""
HEALTH=$(curl -s -m 3 http://127.0.0.1:8766/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q '"ok"'; then
    echo "✓ worker 健康: $HEALTH"
else
    echo "✗ worker 无响应，检查日志: sudo journalctl -u trendzen-edge --since '1 min ago'"
fi
