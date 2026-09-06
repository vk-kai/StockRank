#!/bin/bash
# =============================================================================
# StockRank 自动更新脚本
# -----------------------------------------------------------------------------
# 长期轮询 git 远端:发现新提交 -> git pull -> 重建并重启容器
# (docker compose down && docker compose up -d --build),完全复刻手动部署流程。
#
# 盘中稳定性优先:默认 AVOID_TRADING_HOURS=1,在 A 股交易时段
# (工作日 09:30-11:30、13:00-15:00)只 pull 代码到磁盘(运行中的容器仍用旧代码,
# Python 不会热重载,安全),把"重建"推迟到收盘后执行,避免盘中 down 容器导致
# 采集/价格监控线程中断。设 AVOID_TRADING_HOURS=0 可关闭该守卫,随时重建。
#
# 可配置项(环境变量):
#   CHECK_INTERVAL        轮询间隔秒数,默认 300(5 分钟)
#   GIT_BRANCH            监控的分支,默认 main
#   AVOID_TRADING_HOURS   1=避开交易时段重建(默认),0=随时重建
#   LOG_FILE              日志文件路径,默认 <仓库>/logs/auto_update.log
#   HEALTH_PORT           重建后本地自检的端口(nginx 发布端口),默认 80
#
# 部署(systemd,推荐):
#   sudo cp docker/auto_update.systemd.service /etc/systemd/system/auto_update.service
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now auto_update
#   journalctl -u auto_update -f        # 看实时日志
#
# 手动临时运行:
#   nohup bash docker/auto_update.sh >/dev/null 2>&1 &
# =============================================================================
set -u

# ── 强制启用 BuildKit ──────────────────────────────────────────────────────
# 关键:systemd 启动的进程环境是"干净"的最小集,不会继承交互 shell 里的
# DOCKER_BUILDKIT=1,导致 docker build 回退到旧版 builder,缓存命中率骤降——
# 表现为"自动重建慢(每次重装 pandas/numpy/akshare),手动跑却快(缓存命中)"。
# 这里统一强制开启,让两种执行路径走同一套 BuildKit 缓存。
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# 注意:本脚本在服务器上的运行位置是 /root/auto_update.sh(在仓库外),
# 不能按脚本位置推导仓库根(会推出 /),所以这里写死;挪动仓库时改这两行即可。
REPO_DIR="/root/StockRank"
DOCKER_DIR="$REPO_DIR/docker"
COMPOSE_FILE="$DOCKER_DIR/docker-compose.yml"

CHECK_INTERVAL="${CHECK_INTERVAL:-300}"
GIT_BRANCH="${GIT_BRANCH:-main}"
AVOID_TRADING_HOURS="${AVOID_TRADING_HOURS:-1}"
LOG_FILE="${LOG_FILE:-$REPO_DIR/logs/auto_update.log}"

mkdir -p "$(dirname "$LOG_FILE")"

log() {
    # 同时写文件和标准输出(供 systemd journal 捕获)
    echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

# 判断当前是否处于 A 股交易时段(工作日 09:30-11:30 / 13:00-15:00)
is_trading_hours() {
    local dow hour min now_min
    dow=$(date +%u)          # 1=周一 ... 6=周六 7=周日
    [ "$dow" -ge 6 ] && return 1
    hour=$(date +%H)
    min=$(date +%M)
    now_min=$((hour * 60 + min))
    # 09:30-11:30 = 570-690 ; 13:00-15:00 = 780-900
    if [ "$now_min" -ge 570 ] && [ "$now_min" -le 690 ]; then return 0; fi
    if [ "$now_min" -ge 780 ] && [ "$now_min" -le 900 ]; then return 0; fi
    return 1
}

# 清理 CNI 端口转发残留:容器被 SIGKILL 时 CNI 不执行清理,发布端口的 DNAT 规则
# 会漏在共享链 CNI-HOSTPORT-DNAT 里;iptables 首条命中,旧规则(指向已死容器IP)
# 会永远遮蔽新规则——表现为容器 Up 且健康、端口却 No route to host / 公网超时。
# 2026-09-06 事故根因。在容器已 down、up 之前调用,保证每次重建后只剩唯一一代规则。
clean_stale_dnat() {
    local n
    while n=$(iptables -t nat -L CNI-HOSTPORT-DNAT --line-numbers -n 2>/dev/null \
              | grep docker_stock-network | head -1 | awk '{print $1}'); [ -n "$n" ]; do
        iptables -t nat -D CNI-HOSTPORT-DNAT "$n"
    done
}

# 检查 docker compose v2 可用
if ! docker compose version >/dev/null 2>&1; then
    log "错误: 未检测到 'docker compose'(v2)。请安装或改用 docker-compose 后调整本脚本。"
    exit 1
fi

cd "$REPO_DIR" || { log "错误: 无法进入仓库目录 $REPO_DIR"; exit 1; }

log "自动更新脚本启动 | 仓库=$REPO_DIR | 分支=$GIT_BRANCH | 间隔=${CHECK_INTERVAL}s | 避交易时段=$AVOID_TRADING_HOURS"

PENDING_REBUILD=0   # 已 pull 但尚未重建的标志
NEED_BUILD=""       # 本次是否需 --build(空=只重启;requirements/Dockerfile 变了才 --build)

while true; do
    # ---- 1. 探测远端是否有新提交 ----
    if git fetch origin "$GIT_BRANCH" >/dev/null 2>&1; then
        LOCAL=$(git rev-parse HEAD 2>/dev/null)
        REMOTE=$(git rev-parse "origin/$GIT_BRANCH" 2>/dev/null)
        if [ -n "$LOCAL" ] && [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
            log "======== 检测到新提交: $LOCAL -> $REMOTE ========"
            # pull 之前列出本次将合入的提交(pull 后 HEAD..origin 就空了),便于追溯是什么代码触发了重建
            log "待合入提交列表:"
            git log --oneline --no-decorate "HEAD..origin/$GIT_BRANCH" >>"$LOG_FILE" 2>&1 || \
                log "(无法获取提交明细)"
            # --ff-only:仅快进合并,避免本地有意外的分叉提交被合并,失败则不破坏工作区
            if git pull --ff-only origin "$GIT_BRANCH" >>"$LOG_FILE" 2>&1; then
                log "git pull 成功,代码已更新到磁盘(运行中容器仍用旧代码,需重建生效)"
                # 判断是否需要重建镜像:只有 Dockerfile 依赖的文件(requirements*/start.sh)变了才 --build。
                # 业务 .py 靠 volume 挂载,只重启即生效,不必 build(每次 build 即使全 cache 命中也有开销)。
                NEED_BUILD=""
                if git diff --name-only "$LOCAL" HEAD 2>/dev/null | \
                   grep -qE '(^|/)(requirements[^/]*\.txt|start\.sh|.*Dockerfile)$'; then
                    NEED_BUILD="--build"
                    log "检测到依赖/Dockerfile 变更,本次将 --build 重建镜像"
                fi
                PENDING_REBUILD=1
            else
                log "git pull 失败(可能有本地改动或非快进可合并),跳过本次,工作区未改动"
            fi
        fi
    else
        log "git fetch 失败(网络/远端不可达),稍后重试"
    fi

    # ---- 2. 有待重建的更新 -> 判断是否允许重建 ----
    if [ "$PENDING_REBUILD" = "1" ]; then
        if [ "$AVOID_TRADING_HOURS" = "1" ] && is_trading_hours; then
            log "处于交易时段,推迟容器重建到收盘后(已 pull 的代码会在收盘后自动生效)"
        else
            # 业务代码靠 volume(../backend:/app/backend)挂载进容器,pull 后只需重启即生效,
            # 无需重建镜像。只有依赖文件(requirements*/start.sh)或 Dockerfile 变了才 --build。
            # 关键:compose 命令必须在 docker/ 目录下执行——compose 文件在子目录 docker/ 里,
            # 在仓库根目录跑会报 "no compose file found",down/up 全是空操作(rc=255)。
            cd "$DOCKER_DIR" || { log "错误: 无法进入 $DOCKER_DIR"; sleep "$CHECK_INTERVAL"; continue; }
            log "======== 开始重建容器: docker compose down && up -d $NEED_BUILD ========"
            t0=$(date +%s)
            # --timeout 10:backend 是 Werkzeug 开发服务器,不响应 SIGTERM,快速进 SIGKILL 不干等。
            docker compose down --timeout 10 >>"$LOG_FILE" 2>&1
            down_rc=$?
            t1=$(date +%s)
            log "  down 完成,耗时 $((t1 - t0))s (rc=$down_rc)"
            # down 后清掉本网络全部残留 DNAT(含刚停容器的旧代),up 重写唯一一代,不被影子遮蔽
            clean_stale_dnat
            docker compose up -d $NEED_BUILD >>"$LOG_FILE" 2>&1
            up_rc=$?
            t2=$(date +%s)
            log "  up 完成,耗时 $((t2 - t1))s (rc=$up_rc)"
            if [ "$down_rc" -eq 0 ] && [ "$up_rc" -eq 0 ]; then
                # 起来自检:podman(netavark) 的端口转发规则偶发不生效(容器 Up 但内外都不通)。
                # 只有探测失败才走修复流程,绝不无脑每轮 restart podman。
                sleep 5
                if curl -s -m 5 -o /dev/null "http://127.0.0.1:${HEALTH_PORT:-80}/"; then
                    log "======== 容器重建完成(总耗时 $((t2 - t0))s),本地探测正常,新代码已生效 ========"
                    PENDING_REBUILD=0
                else
                    log "  本地探测不通,执行转发修复: down -> 清残留DNAT -> up"
                    docker compose down --timeout 10 >>"$LOG_FILE" 2>&1
                    clean_stale_dnat
                    docker compose up -d $NEED_BUILD >>"$LOG_FILE" 2>&1
                    sleep 5
                    if curl -s -m 5 -o /dev/null "http://127.0.0.1:${HEALTH_PORT:-80}/"; then
                        log "======== 转发修复成功,容器已恢复,新代码已生效 ========"
                    else
                        log "======== 转发修复后仍不通!代码已生效,请人工检查: docker compose ps / iptables -t nat -S ========"
                    fi
                    PENDING_REBUILD=0   # 代码已部署,不再无限重试;转发问题转人工,避免循环破坏
                fi
            else
                log "======== 容器重建失败(down_rc=$down_rc up_rc=$up_rc),保留待重建标志,下一轮重试 ========"
            fi
        fi
    fi

    sleep "$CHECK_INTERVAL"
done
