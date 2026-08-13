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

# 仓库根 = 本脚本所在 docker 目录的上一级(不硬编码 /root/StockRank,便于迁移)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
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
            # 无需重建镜像。只依赖文件(requirements*/start.sh)或 Dockerfile 变了才 --build。
            # 注意:这个 NEED_BUILD 判断用的是上次 pull 前记录的 HEAD(见上方 git pull 成功处)。
            log "======== 开始重建容器: docker compose down && up -d $NEED_BUILD ========"
            t0=$(date +%s)
            # --timeout 10:backend 是 Werkzeug 开发服务器,不响应 SIGTERM,快速进 SIGKILL 不干等。
            docker compose -f "$COMPOSE_FILE" down --timeout 10 >>"$LOG_FILE" 2>&1
            down_rc=$?
            t1=$(date +%s)
            log "  down 完成,耗时 $((t1 - t0))s (rc=$down_rc)"
            docker compose -f "$COMPOSE_FILE" up -d $NEED_BUILD >>"$LOG_FILE" 2>&1
            up_rc=$?
            t2=$(date +%s)
            log "  up 完成,耗时 $((t2 - t1))s (rc=$up_rc)"
            if [ "$down_rc" -eq 0 ] && [ "$up_rc" -eq 0 ]; then
                log "======== 容器重建并启动完成(总耗时 $((t2 - t0))s),新代码已生效 ========"
                PENDING_REBUILD=0
            else
                log "======== 容器重建失败(down_rc=$down_rc up_rc=$up_rc),保留待重建标志,下一轮重试 ========"
            fi
        fi
    fi

    sleep "$CHECK_INTERVAL"
done
