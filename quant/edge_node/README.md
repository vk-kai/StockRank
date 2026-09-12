# TrendZen 边缘节点（树莓派）部署

把回测计算卸载到家里的树莓派，服务器 CPU/内存吃紧时由 Pi 兜底；Pi 掉线自动回落服务器本机。

## 架构

```
[服务器 TrendZen]  ──HTTP──▶  127.0.0.1:8765  ═══SSH 反向隧道(autossh)═══▶  [树莓派]  127.0.0.1:8766  edge_node worker
   runtime.py                                                                                  runs run_backtest
```

- 树莓派**主动**连服务器（autossh `-R`），服务器**无需**给 Pi 做内网穿透。
- 服务器把 Pi 当 `http://127.0.0.1:8765` 的本机服务调用。隧道只绑服务器 loopback，不暴露公网。
- df 由服务器序列化（pickle+zlib+base64）随任务下发，**Pi 无状态、不取数、不碰 DB**。
- 失败/超时 → 服务器自动回落本机 `run_backtest` / `ProcessPoolExecutor`（复用同一份 df，结果一致）。

## 1. 树莓派环境

- **64 位 Pi OS**（Bookworm aarch64）。32 位系统装 pandas/pyarrow 很痛。
- Python 3.11+。
- 建议 Pi 4（4GB+）或 Pi 5。1GB/2GB 机型把 `EDGE_NODE_WORKERS` 调到 2。

```bash
sudo apt update && sudo apt install -y python3-venv python3-dev git
git clone <你的 TrendZen 仓库> ~/TrendZen && cd ~/TrendZen
python3 -m venv .venv && . .venv/bin/activate

# worker 只需要这几个依赖（不装 akshare/pytdx/sqlalchemy，保持轻量）
pip install --extra-index-url https://www.piwheels.org/simple \
    "fastapi>=0.104" "uvicorn[standard]>=0.24" "pydantic>=2.0" \
    "pandas>=2.0" "numpy>=1.24" "backtrader>=1.9.78" "psutil>=5.9"
```

> ⚠️ **backtrader 版本必须与服务器一致**（服务器默认 1.9.78.123）。worker 的 `/health` 会上报版本，服务器握手时校验，不一致会在导航栏徽章 tooltip 提示「版本不一致，结果可能漂移」。

## 2. 启动 worker

```bash
cd ~/TrendZen && . .venv/bin/activate
# 可选：设一个共享 token（与服务器 PI_NODE_TOKEN 一致；不设则不鉴权）
export PI_NODE_TOKEN=换成一段随机串
export EDGE_NODE_WORKERS=3           # Pi 核数 - 1
export EDGE_NODE_PORT=8766
python -m edge_node                  # 监听 127.0.0.1:8766
```

本机自测：`curl http://127.0.0.1:8766/health` 应返回 `{"status":"ok",...,"load":{cpu_percent,...}}`。

## 3. 反向隧道（autossh）

Pi 主动连服务器，把 Pi 的 8766 映射成服务器的 127.0.0.1:8765：

```bash
sudo apt install -y autossh
# 先把 Pi 的公钥加到服务器 tunnel 用户（见第 4 步）
autossh -M 0 -N \
  -R 127.0.0.1:8765:127.0.0.1:8766 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
  -i ~/.ssh/tunnel_ed25519 tunnel@<服务器IP>
```

做成 systemd（`/etc/systemd/system/trendzen-tunnel.service`）：

```ini
[Unit]
Description=autossh reverse tunnel to TrendZen server
After=network-online.target
[Service]
Type=simple
User=pi
Environment=AUTOSSH_GATETIME=0
ExecStart=/usr/bin/autossh -M 0 -N -R 127.0.0.1:8765:127.0.0.1:8766 \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes \
  -i /home/pi/.ssh/tunnel_ed25519 tunnel@<服务器IP>
Restart=always
[Install]
WantedBy=multi-user.target
```

worker 也做成 systemd（`/etc/systemd/system/trendzen-edge.service`）：

```ini
[Unit]
Description=TrendZen Edge Node (FastAPI worker)
After=network-online.target
[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/TrendZen
Environment="PI_NODE_TOKEN=换成一段随机串"
Environment="EDGE_NODE_WORKERS=3"
Environment="EDGE_NODE_PORT=8766"
ExecStart=/home/pi/TrendZen/.venv/bin/python -m edge_node
Restart=always
[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trendzen-edge trendzen-tunnel
```

## 4. 服务器侧 sshd（加固）

建专用 `tunnel` 用户（无 shell）、仅允许端口转发、强制只绑 loopback：

```bash
sudo useradd -m -s /usr/sbin/nologin tunnel
# 把 Pi 生成的密钥对公钥放到 /home/tunnel/.ssh/authorized_keys
```

`/etc/ssh/sshd_config.d/tunnel.conf`：

```
Match User tunnel
    AllowTcpForwarding yes
    GatewayPorts no              # 关键：-R 只绑服务器 loopback，不暴露公网
    PermitOpen 127.0.0.1:8765
    X11Forwarding no
    AllowAgentForwarding no
    PermitTTY no
```

```bash
sudo systemctl reload sshd
# 验证：在服务器上 curl http://127.0.0.1:8765/health 应能拿到 Pi 的响应
```

## 5. 服务器侧开启卸载

在 TrendZen `.env` 里：

```ini
PI_NODE_ENABLED=true
PI_NODE_URL=http://127.0.0.1:8765
PI_NODE_TOKEN=换成与 Pi 相同的那段随机串
PI_NODE_OFFLOAD_MODE=both        # both / single_only / full_only
PI_NODE_BATCH_CHUNK=50           # 全量扫描每批发送标的数；Pi 内存小可调到 25
PI_NODE_MAX_DF_KB=512            # 单标的 df 超此值跳过卸载（分钟级大 df 走本地）
```

重启 TrendZen 后端。导航栏 `ws-status` 旁会出现节点徽章：
- 🟢 `节点 23%·49% 42ms`（在线，Pi 的 CPU%·内存%·延迟）
- 🟠 `保底中 Ns` / `保底中(离线)`（Pi 不可用，已回落本机）
- ⚪ `本机`（未启用）

回测进度卡会显示「执行节点：树莓派节点 / 本机 / 节点 + 本机（混合）」。

## 6. 排错

| 现象 | 排查 |
|---|---|
| 徽章一直「保底中(离线)」 | Pi 上 `systemctl status trendzen-edge trendzen-tunnel`；服务器 `curl http://127.0.0.1:8765/health`；看 TrendZen 日志 `Pi 节点健康检测` |
| 单股正常、全量慢 | 调小 `PI_NODE_BATCH_CHUNK`；分钟级 df 大可设 `PI_NODE_OFFLOAD_MODE=single_only` 只卸载单股 |
| tooltip 提示版本不一致 | Pi 上 `pip install "backtrader==<服务器版本>"` 对齐 |
| Pi 内存吃紧 | 调小 `EDGE_NODE_WORKERS` 和 `PI_NODE_BATCH_CHUNK` |

## 关闭

`.env` 设 `PI_NODE_ENABLED=false` 重启即可。此时 `runtime.py` 逐字走原本地 `ProcessPool` 路径，零行为变化。
