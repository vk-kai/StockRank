#!/bin/bash
# ================================================================
# TrendZen 树莓派边缘节点一键部署脚本
# 用法: curl/scp 此脚本到 Pi，然后 bash deploy_edge_node.sh
# ================================================================
set -e

# ---------- 可配置变量 ----------
EDGE_PORT=${EDGE_NODE_PORT:-8766}
EDGE_WORKERS=${EDGE_NODE_WORKERS:-3}
EDGE_TOKEN=${PI_NODE_TOKEN:-}
SERVER_IP=${SERVER_IP:-}           # 服务器公网 IP（隧道用，可后配）
TUNNEL_USER=${TUNNEL_USER:-tunnel}
PI_USER=$(whoami)
PI_HOME=$(eval echo "~$PI_USER")
INSTALL_DIR="$PI_HOME/TrendZen"
VENV_DIR="$INSTALL_DIR/.venv"
LOG_DIR="$INSTALL_DIR/logs"

# 颜色
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

# ---------- 0. 检查是否在 Pi (aarch64) 上 ----------
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" ]]; then
    warn "当前架构 $ARCH，不是 aarch64。继续部署但可能需要调整依赖。"
fi

# ---------- 1. apt 换清华源 ----------
info "1/8 配置 apt 清华源..."
if ! grep -q "mirrors.tuna.tsinghua.edu.cn" /etc/apt/sources.list 2>/dev/null; then
    CODENAME=$(lsb_release -cs 2>/dev/null || cat /etc/os-release | grep VERSION_CODENAME | cut -d= -f2)
    sudo cp /etc/apt/sources.list /etc/apt/sources.list.bak 2>/dev/null || true
    sudo tee /etc/apt/sources.list > /dev/null << EOF
deb https://mirrors.tuna.tsinghua.edu.cn/debian/ ${CODENAME} main contrib non-free non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian/ ${CODENAME}-updates main contrib non-free non-free-firmware
deb https://mirrors.tuna.tsinghua.edu.cn/debian-security ${CODENAME}-security main contrib non-free non-free-firmware
EOF
    info "apt 源已换为清华镜像 ($CODENAME)"
else
    info "apt 清华源已配置，跳过"
fi

# ---------- 2. 安装系统依赖 ----------
info "2/8 安装系统依赖..."
sudo apt update -qq
sudo apt install -y python3-venv python3-dev git autossh curl

# ---------- 3. 部署代码 ----------
info "3/8 部署代码..."
if [[ ! -d "$INSTALL_DIR/backend" ]]; then
    err "代码目录 $INSTALL_DIR 不存在。请先将 TrendZen 项目复制到 Pi:
     方式1: scp -r /path/to/TrendZen ${PI_USER}@$(hostname):$INSTALL_DIR
     方式2: git clone <仓库> $INSTALL_DIR"
fi

# ---------- 4. 创建 venv + pip 换清华源 + 安装依赖 ----------
info "4/8 创建 venv 并安装 Python 依赖..."
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# pip 换清华源
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装依赖（只装 worker 需要的，不装 akshare/pytdx 等）
pip install --quiet \
    'fastapi>=0.104' \
    'uvicorn[standard]>=0.24' \
    'pydantic>=2.0' \
    'pandas>=2.0' \
    'numpy>=1.24' \
    'backtrader>=1.9.78' \
    'psutil>=5.9' \
    'pyarrow>=14.0'

# ---------- 5. 验证依赖 ----------
info "5/8 验证 Python 依赖..."
python -c "import fastapi,uvicorn,pydantic,pandas,numpy,backtrader,psutil,pyarrow; print('ALL OK')" || err "依赖验证失败"

# ---------- 6. 创建 watchdog 脚本 ----------
info "6/8 创建 watchdog 监控脚本..."
mkdir -p "$LOG_DIR"

cat > "$INSTALL_DIR/edge_watchdog.sh" << 'WATCHDOG'
#!/bin/bash
FAIL_COUNT=0
MAX_FAIL=3
CHECK_INTERVAL=30
LOG=__LOG_DIR__/watchdog.log
EDGE_SERVICE=trendzen-edge

mkdir -p "$(dirname "$LOG")"

while true; do
    RESP=$(curl -s -m 5 http://127.0.0.1:__EDGE_PORT__/health 2>/dev/null)
    if echo "$RESP" | grep -q '"status":"ok"' || echo "$RESP" | grep -q '"status": "ok"'; then
        if [ "$FAIL_COUNT" -gt 0 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] worker 恢复正常" >> "$LOG"
        fi
        FAIL_COUNT=0
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
        echo "$(date '+%Y-%m-%d %H:%M:%S') [WARN] /health 失败 ($FAIL_COUNT/$MAX_FAIL): $RESP" >> "$LOG"
        if [ "$FAIL_COUNT" -ge "$MAX_FAIL" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') [ACTION] 重启 $EDGE_SERVICE 服务" >> "$LOG"
            sudo systemctl restart "$EDGE_SERVICE"
            FAIL_COUNT=0
            sleep 10
            continue
        fi
    fi
    sleep "$CHECK_INTERVAL"
done
WATCHDOG

# 替换模板变量
sed -i "s|__LOG_DIR__|$LOG_DIR|g" "$INSTALL_DIR/edge_watchdog.sh"
sed -i "s|__EDGE_PORT__|$EDGE_PORT|g" "$INSTALL_DIR/edge_watchdog.sh"
chmod +x "$INSTALL_DIR/edge_watchdog.sh"

# ---------- 7. 创建 systemd 服务 ----------
info "7/8 配置 systemd 服务..."

# Worker 服务
sudo tee /etc/systemd/system/trendzen-edge.service > /dev/null << EOF
[Unit]
Description=TrendZen Edge Node (FastAPI worker)
After=network-online.target

[Service]
Type=simple
User=$PI_USER
WorkingDirectory=$INSTALL_DIR
Environment="EDGE_NODE_WORKERS=$EDGE_WORKERS"
Environment="EDGE_NODE_PORT=$EDGE_PORT"
EOF

if [[ -n "$EDGE_TOKEN" ]]; then
    echo "Environment=\"PI_NODE_TOKEN=$EDGE_TOKEN\"" | sudo tee -a /etc/systemd/system/trendzen-edge.service > /dev/null
fi

sudo tee -a /etc/systemd/system/trendzen-edge.service > /dev/null << EOF
ExecStart=$VENV_DIR/bin/python -m edge_node
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Watchdog 服务
sudo tee /etc/systemd/system/trendzen-watchdog.service > /dev/null << EOF
[Unit]
Description=TrendZen Edge Node Watchdog
After=trendzen-edge.service

[Service]
Type=simple
User=$PI_USER
ExecStart=$INSTALL_DIR/edge_watchdog.sh
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 隧道服务（仅当 SERVER_IP 已配置时）
if [[ -n "$SERVER_IP" ]]; then
    info "   配置 autossh 隧道 -> $SERVER_IP ..."
    # 生成密钥（如不存在）
    if [[ ! -f "$PI_HOME/.ssh/tunnel_ed25519" ]]; then
        ssh-keygen -t ed25519 -f "$PI_HOME/.ssh/tunnel_ed25519" -N "" -q
        info "   SSH 密钥已生成"
    fi

    sudo tee /etc/systemd/system/trendzen-tunnel.service > /dev/null << EOF
[Unit]
Description=autossh reverse tunnel to TrendZen server
After=network-online.target

[Service]
Type=simple
User=$PI_USER
Environment=AUTOSSH_GATETIME=0
ExecStart=/usr/bin/autossh -M 0 -N -R 127.0.0.1:8765:127.0.0.1:$EDGE_PORT -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -i $PI_HOME/.ssh/tunnel_ed25519 ${TUNNEL_USER}@${SERVER_IP}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
fi

# ---------- 8. 启动服务 ----------
info "8/8 启动服务..."
sudo systemctl daemon-reload
sudo systemctl enable --now trendzen-edge
sudo systemctl enable --now trendzen-watchdog

if [[ -n "$SERVER_IP" ]]; then
    # 先不自动启动隧道，等服务器端配好再开
    sudo systemctl enable trendzen-tunnel
    warn "隧道服务已 enable 但未 start。请先在服务器完成 tunnel 用户配置后手动启动:
    sudo systemctl start trendzen-tunnel"
fi

# 等 worker 启动
sleep 3

# ---------- 验证 ----------
echo ""
echo "========================================="
info "部署完成！状态检查:"
sudo systemctl status trendzen-edge --no-pager -l | head -15
echo ""

HEALTH=$(curl -s -m 3 http://127.0.0.1:$EDGE_PORT/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q '"ok"'; then
    info "/health 响应正常: $HEALTH"
else
    warn "/health 无响应，worker 可能还在启动，稍后检查: curl http://127.0.0.1:$EDGE_PORT/health"
fi

if [[ -n "$SERVER_IP" ]]; then
    echo ""
    info "===== Pi 公钥（需添加到服务器 ${TUNNEL_USER} 用户 authorized_keys）====="
    cat "$PI_HOME/.ssh/tunnel_ed25519.pub"
    echo "================================================================"
fi

echo ""
info "常用命令:"
echo "  查看状态:  sudo systemctl status trendzen-edge trendzen-watchdog"
echo "  查看日志:  sudo journalctl -u trendzen-edge -f"
echo "  手动重启:  sudo systemctl restart trendzen-edge"
echo "  健康检查:  curl http://127.0.0.1:$EDGE_PORT/health"
echo "  watchdog日志: cat $LOG_DIR/watchdog.log"
