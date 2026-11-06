# -*- coding: utf-8 -*-
"""手动部署接口:配置页按钮 → SSH 到宿主机执行 git pull + docker 重建。

与 deploy_remote.py / docker/auto_update.sh 同一套部署命令,SSH 密码由前端
弹窗传入(不落盘、不进日志、用完即弃),双保险:vk 登录态 + SSH 密码。

命令以 nohup 在宿主机后台执行:docker compose down 会杀掉 backend 容器
(即本进程),SSH 通道必然中断,不能同步等待部署完成,只等触发回显。
"""
import os
import shlex
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

from core.logger import get_logger
from .auth_routes import is_authenticated

deploy_bp = Blueprint('deploy', __name__, url_prefix='/api/deploy')
system_logger = get_logger('system')
error_logger = get_logger('error')

# SSH 目标:容器内默认走 host.docker.internal 网关内网回连(compose 已配
# extra_hosts host-gateway)——宿主机 22 端口有公网来源限制,容器走公网 IP
# 回连会被安全组挡;裸机/本地调试时可设 DEPLOY_SSH_HOST=公网IP 直连。
DEPLOY_SSH_HOST = os.environ.get('DEPLOY_SSH_HOST', 'host.docker.internal')
DEPLOY_SSH_USER = os.environ.get('DEPLOY_SSH_USER', 'root')
DEPLOY_MIN_INTERVAL = 30    # 两次手动部署最小间隔(秒),防连点

# 版本信息:仓库公开时匿名 API 够用;私有化后在 compose 配 GITHUB_TOKEN
GITHUB_REPO = os.environ.get('DEPLOY_GITHUB_REPO', 'vk-kai/StockRank')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
# 当前部署版本主数据源:compose 把宿主机仓库的 .git 只读挂载进容器
# (../.git:/app/repo/.git:ro),纯 stdlib 解析 HEAD→refs 即得 SHA,零依赖
_GIT_DIR = os.environ.get('DEPLOY_GIT_DIR', '/app/repo/.git')
# 兜底数据源:部署脚本写在 backend/DEPLOYED_VERSION 的标记文件
# (backend 目录 volume 挂载可见;.git 挂载异常时仍可用)
_VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'DEPLOYED_VERSION')
# 前端部署页签每 60s 轮询:180s 缓存让 GitHub API 实际只发 ~20 请求/h,
# 稳稳低于匿名限额 60/h;手动刷新(fresh=1)绕过缓存
_VERSION_TTL = 180.0
_version_cache = {'ts': 0.0, 'data': None}

# 进程内节流;down/up 期间本进程随容器重启,时间戳清零,重启后自然解锁
_last_deploy_ts = 0.0
_deploy_lock = threading.Lock()

# 部署实时状态:宿主机脚本每步写一行 "unix时间戳|phase|detail" 到
# backend/DEPLOY_STATUS(volume 挂载,容器内可读),/deploy/status 端点转述给
# 配置页。phase: triggered→pulling→pull_retry→building→done|failed
_STATUS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'DEPLOY_STATUS')

# 部署脚本与 auto_update.sh 同构:丢弃运行时状态改动 → ff-only pull →
# down --timeout 10 → 清 CNI 残留 DNAT(2026-09-06 事故根因,倒序删防行号移位) → up --build。
# 与旧版的差别:①不再用 && 静默串联——git pull 失败会把原因写进状态文件
# 并退出,配置页能看到死因(此前 && 链一断,页面永远"部署中",真相只在
# 宿主机 manual_deploy.log);②git pull 重试 3 次(国内服务器到 GitHub 的
# 网络抖动是高发死因);③每步进度落盘,面板实时显示;④拉取前对已解除
# git 跟踪的运行时状态文件做 checkout 丢弃——它们被后端每天自动重写,
# 本地改动与远端提交冲突会永久卡死拉取(2026-11-06 事故根因),内容运行
# 后自动再生,丢弃无损失;⑤部署成败同步追加写 logs/system.log(与
# core.logger 的行格式一致,日志页"系统日志"可直接检索;容器重建期间
# 后端已死,只有宿主机脚本能落这笔账)。
_SCRIPT = (
    "S=/root/StockRank/backend/DEPLOY_STATUS ; "
    "L=/root/manual_deploy.log ; "
    "SY=/root/StockRank/logs/system.log ; "
    "wr(){ printf '%s|%s|%s\\n' \"$(date +%s)\" \"$1\" \"$2\" >\"$S\" ; } ; "
    "slog(){ mkdir -p /root/StockRank/logs ; "
    "printf '%s | %s | system | 系统运行 | manual_deploy:0 | %s\\n' "
    "\"$(date '+%F %T,%3N')\" \"$1\" \"$2\" >>\"$SY\" ; } ; "
    "wr triggered '' ; "
    "cd /root/StockRank/docker || { wr failed 'cd docker 目录失败' ; exit 1 ; } ; "
    "wr pulling '' ; "
    "git -C /root/StockRank checkout -- "
    "config/ai_news_summary_status.json config/ai_news_summary_result.md "
    "config/ai_daily_status.json config/ai_daily_result.md "
    "config/industry_cycle_status.json config/industry_cycle_result.json "
    "config/name_code_cache.json 2>/dev/null ; "
    "OLD=$(git -C /root/StockRank rev-parse --short HEAD 2>/dev/null) ; "
    "ok=0 ; out=pull-not-run ; "
    "for i in 1 2 3 ; do "
    "out=$(git pull --ff-only origin main 2>&1) ; rc=$? ; "
    "out=$(printf '%s' \"$out\" | tr '\\n' ' ' | cut -c1-240) ; "
    "if [ \"$rc\" = 0 ] ; then ok=1 ; break ; fi ; "
    "wr pull_retry \"第${i}次拉取失败: $out\" ; sleep 5 ; "
    "done ; "
    "if [ \"$ok\" = 0 ] ; then wr failed \"git pull 失败: $out\" ; "
    "slog ERROR \"[部署] git pull 失败(3次重试后放弃): $out\" ; exit 1 ; fi ; "
    "NEW=$(git -C /root/StockRank rev-parse --short HEAD 2>/dev/null) ; "
    "slog INFO \"[部署] 代码拉取成功: ${OLD:-?} -> ${NEW:-?},开始重建容器\" ; "
    "T0=$(date +%s) ; "
    "wr building '' ; "
    "sleep 3 ; "  # 给 /docker-restart 的 HTTP 响应留送达窗口,防止 down 与响应竞态把前端吓成"触发失败"
    "{ docker compose down --timeout 10 && sleep 2 && "
    "iptables -t nat -L CNI-HOSTPORT-DNAT --line-numbers -n 2>/dev/null | "
    "grep docker_stock-network | awk '{print $1}' | sort -rn | "
    "xargs -r -I{} iptables -t nat -D CNI-HOSTPORT-DNAT {} ; "
    "docker compose up -d --build ; } >>\"$L\" 2>&1 ; "
    "rc=$? ; "
    "git rev-parse HEAD >/root/StockRank/backend/DEPLOYED_VERSION 2>/dev/null ; "
    "if [ \"$rc\" = 0 ] ; then wr done '' ; "
    "slog INFO \"[部署] 容器重建完成(耗时 $(($(date +%s)-T0))s),新代码已生效: ${NEW:-?}\" ; "
    "else wr failed \"compose 退出码 $rc(详见宿主机 $L)\" ; "
    "slog ERROR \"[部署] 容器重建失败(compose 退出码 $rc,详见宿主机 $L),代码已拉取到 ${NEW:-?} 但未生效\" ; fi"
)
REMOTE_CMD = ("nohup bash -c " + shlex.quote(_SCRIPT)
              + " >/root/manual_deploy.log 2>&1 & echo DEPLOY_TRIGGERED")


@deploy_bp.route('/docker-restart', methods=['POST', 'OPTIONS'])
def docker_restart():
    """触发宿主机后台部署。body: {password}。返回即代表"已触发",非"已完成"。"""
    if request.method == 'OPTIONS':
        return jsonify({'success': True})
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'auth_required',
                        'message': '仅管理员可操作'}), 401

    global _last_deploy_ts

    def _rollback_cooldown():
        """触发失败时释放冷却占位:冷却时间戳在锁内置位是为了防并发双触发,
        但密码错误/SSH 异常等失败路径若不回滚,用户改对密码还得干等满 5 分钟。"""
        global _last_deploy_ts
        with _deploy_lock:
            _last_deploy_ts = 0.0

    # 密码空检查放锁外:缺密码根本没到触发环节,不应触碰冷却状态
    password = (request.get_json(silent=True) or {}).get('password', '')
    if not password:
        return jsonify({'success': False, 'message': '缺少 SSH 密码'}), 400

    with _deploy_lock:
        now = time.time()
        if now - _last_deploy_ts < DEPLOY_MIN_INTERVAL:
            remain = int(DEPLOY_MIN_INTERVAL - (now - _last_deploy_ts))
            return jsonify({'success': False,
                            'message': f'部署太频繁,请 {remain}s 后再试'}), 429
        _last_deploy_ts = now

    try:
        import paramiko
    except ImportError:
        error_logger.error('paramiko 未安装,页面部署不可用(需重建镜像装依赖)')
        _rollback_cooldown()
        return jsonify({'success': False,
                        'message': '服务器缺少 paramiko 依赖,需重建镜像'}), 500

    try:
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(DEPLOY_SSH_HOST, username=DEPLOY_SSH_USER,
                    password=password, timeout=15)
        try:
            # 只等触发回显(down 启动后本容器随时可能被杀,不依赖长连接)
            _, stdout, _ = cli.exec_command(REMOTE_CMD, timeout=30)
            out = stdout.read().decode(errors='replace').strip()
        finally:
            cli.close()
        if 'DEPLOY_TRIGGERED' not in out:
            error_logger.error(f'手动部署远程命令无触发回显: {out[:200]}')
            _rollback_cooldown()
            return jsonify({'success': False,
                            'message': '远程命令触发异常,详见服务端日志'}), 500
        # 状态行由宿主机脚本自己写(第一步 wr triggered):此处不写,避免在脚本
        # 已推进到 pulling 后反而把它倒退覆盖成 triggered。前端 10s 后才首 poll,
        # 脚本早已落笔,不会读到上一轮残留。
        system_logger.info('手动部署已触发(配置页按钮): 宿主机后台执行 git pull + docker 重建')
        return jsonify({'success': True,
                        'message': '部署已触发,服务将中断 1-3 分钟后自动恢复'})
    except paramiko.AuthenticationException:
        error_logger.warning('手动部署失败: SSH 密码错误')
        _rollback_cooldown()
        return jsonify({'success': False, 'message': 'SSH 密码错误'}), 401
    except Exception as e:
        # 异常对象不含密码,可安全记录;提示保持模糊防探测
        error_logger.warning(f'手动部署触发失败: {repr(e)[:160]}')
        _rollback_cooldown()
        return jsonify({'success': False, 'message': '触发失败:SSH 连接异常'}), 500


def _read_local_head():
    """纯 stdlib 解析只读挂载的 .git,返回 (40位sha, 更新时间str)。

    HEAD → 'ref: refs/heads/main' → 读该 ref 文件得 sha(引用文件缺失则查
    packed-refs,git gc 会把引用打包)。git 更新引用走"写临时文件+原子
    rename",容器侧并发读最多拿到旧值,不会读到半截内容。
    """
    def _mtime(path):
        try:
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')
        except OSError:
            return None

    try:
        with open(os.path.join(_GIT_DIR, 'HEAD')) as f:
            head = f.read().strip()
        if not head.startswith('ref: '):
            # detached HEAD(部署流程不会出现,防御性支持)
            return (head[:40], _mtime(os.path.join(_GIT_DIR, 'HEAD'))) \
                if len(head) >= 40 else (None, None)
        ref = head[5:].strip()
        ref_path = os.path.join(_GIT_DIR, *ref.split('/'))
        try:
            with open(ref_path) as f:
                sha = f.read().strip()
            if len(sha) >= 40:
                return sha[:40], _mtime(ref_path)
        except OSError:
            pass
        # 引用被 git gc 打包进 packed-refs:格式 '<sha> <ref>' 每行
        packed = os.path.join(_GIT_DIR, 'packed-refs')
        try:
            with open(packed) as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref and len(parts[0]) >= 40:
                        return parts[0][:40], _mtime(packed)
        except OSError:
            pass
    except OSError:
        pass   # .git 未挂载/不可读 → 交给调用方走标记文件兜底
    return None, None


@deploy_bp.route('/status', methods=['GET'])
def deploy_status():
    """读宿主机脚本写的部署状态行,配置页轮询用。只读,无需 SSH 密码。"""
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'auth_required'}), 401
    try:
        with open(_STATUS_FILE) as f:
            ts, _, rest = f.read().strip().partition('|')
            phase, _, detail = rest.partition('|')
        ts = int(ts) if ts.isdigit() else None
    except (OSError, ValueError):
        return jsonify({'success': True, 'phase': 'none',
                        'detail': '', 'ts': None})
    # done/failed 超过 30 分钟视为陈旧,不再当作"进行中"展示
    fresh_window = 1800
    if phase in ('done', 'failed') and ts and time.time() - ts > fresh_window:
        phase = 'stale'
    return jsonify({'success': True, 'phase': phase, 'detail': detail, 'ts': ts})


def _gh(path):
    """GitHub REST API 只读访问(可带 token;仓库公开时匿名即可)。"""
    import requests
    headers = {'Accept': 'application/vnd.github+json'}
    if GITHUB_TOKEN:
        headers['Authorization'] = 'Bearer ' + GITHUB_TOKEN
    r = requests.get('https://api.github.com' + path, headers=headers, timeout=8)
    if r.status_code in (401, 403):
        raise RuntimeError('认证失败或被限流(仓库私有化后需配置 GITHUB_TOKEN)')
    if r.status_code == 404:
        raise RuntimeError('仓库不存在或无权限访问(私有化后需配置 GITHUB_TOKEN)')
    r.raise_for_status()
    return r.json()


@deploy_bp.route('/version-info', methods=['GET'])
def version_info():
    """部署版本 vs GitHub main:部署 SHA、最近 3 条提交、远程领先数。

    部署 SHA 优先从只读挂载的 .git 解析(HEAD→refs),兜底部署脚本写的
    DEPLOYED_VERSION 标记;远程信息走 GitHub API。只读、无需 SSH 密码,
    vk 登录态即可查看;前端部署页签每 60s 轮询本接口。
    """
    if not is_authenticated():
        return jsonify({'success': False, 'error': 'auth_required'}), 401

    fresh = request.args.get('fresh') == '1'
    now = time.time()
    if not fresh and _version_cache['data'] and now - _version_cache['ts'] < _VERSION_TTL:
        return jsonify(_version_cache['data'])

    # 当前部署 SHA:主读只读挂载的 .git;读不到退回部署脚本写的标记文件
    deployed_sha, deployed_at = _read_local_head()
    if not deployed_sha:
        try:
            with open(_VERSION_FILE) as f:
                deployed_sha = f.read().strip() or None
            if deployed_sha:
                deployed_at = datetime.fromtimestamp(
                    os.path.getmtime(_VERSION_FILE)).strftime('%Y-%m-%d %H:%M')
        except OSError:
            pass   # 两个数据源都无(挂载+脚本均未生效),前端显示"未知"

    result = {'success': True, 'deployed_sha': deployed_sha, 'deployed_at': deployed_at,
              'commits': [], 'ahead_by': None, 'remote_error': None}

    try:
        data = _gh('/repos/%s/commits?per_page=3' % GITHUB_REPO)
        result['commits'] = [{
            'sha': c['sha'][:7],
            'message': ((c.get('commit') or {}).get('message') or '').splitlines()[0][:120],
            'author': ((c.get('commit') or {}).get('author') or {}).get('name') or '',
            'date': ((c.get('commit') or {}).get('author') or {}).get('date') or '',
        } for c in data]
        if deployed_sha:
            if deployed_sha == data[0]['sha']:
                result['ahead_by'] = 0
            else:
                cmp_data = _gh('/repos/%s/compare/%s...main' % (GITHUB_REPO, deployed_sha))
                result['ahead_by'] = cmp_data.get('ahead_by')
    except Exception as e:
        # GitHub REST API 匿名限流(60次/h/IP)或国内访问间歇 403 —— 高发。
        # 兜底: git smart HTTP 的 info/refs 端点匿名可读公开仓库、无限流,
        # 能拿到远程 main 的 SHA,足够回答"当前部署是否落后"这一核心问题。
        try:
            import requests as _rq
            r2 = _rq.get('https://github.com/%s.git/info/refs?service=git-upload-pack' % GITHUB_REPO,
                         timeout=8, headers={'User-Agent': 'git/2.0'})
            import re as _re
            m = _re.search(r'([0-9a-f]{40}) HEAD', r2.text)
            if r2.status_code == 200 and m:
                remote_sha = m.group(1)
                if deployed_sha:
                    result['ahead_by'] = 0 if deployed_sha == remote_sha else -1
                    if result['ahead_by'] == -1:
                        result['remote_error'] = (
                            '远程 main 有更新(%s),GitHub 提交列表暂不可达(API 限流),可一键部署更新'
                            % remote_sha[:7])
                else:
                    result['remote_error'] = None   # 无本地 sha,本来就说"部署一次后显示"
            else:
                result['remote_error'] = str(e)[:160] or 'GitHub API 不可达'
        except Exception:
            result['remote_error'] = str(e)[:160] or 'GitHub API 不可达'

    _version_cache.update(ts=now, data=result)
    return jsonify(result)
