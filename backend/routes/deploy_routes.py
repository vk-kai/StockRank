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
DEPLOY_MIN_INTERVAL = 300   # 两次手动部署最小间隔(秒),防连点

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

# 部署脚本与 auto_update.sh 同构:ff-only pull → down --timeout 10 →
# 清 CNI 残留 DNAT(2026-09-06 事故根因,倒序删防行号移位) → up --build
_SCRIPT = (
    "cd /root/StockRank/docker && "
    "git pull --ff-only origin main && "
    "docker compose down --timeout 10 && sleep 2 && "
    "iptables -t nat -L CNI-HOSTPORT-DNAT --line-numbers -n 2>/dev/null | "
    "grep docker_stock-network | awk '{print $1}' | sort -rn | "
    "xargs -r -I{} iptables -t nat -D CNI-HOSTPORT-DNAT {} ; "
    "docker compose up -d --build ; "
    "git rev-parse HEAD > /root/StockRank/backend/DEPLOYED_VERSION"
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
    with _deploy_lock:
        now = time.time()
        if now - _last_deploy_ts < DEPLOY_MIN_INTERVAL:
            remain = int(DEPLOY_MIN_INTERVAL - (now - _last_deploy_ts))
            return jsonify({'success': False,
                            'message': f'部署太频繁,请 {remain}s 后再试'}), 429
        _last_deploy_ts = now

    password = (request.get_json(silent=True) or {}).get('password', '')
    if not password:
        return jsonify({'success': False, 'message': '缺少 SSH 密码'}), 400

    try:
        import paramiko
    except ImportError:
        error_logger.error('paramiko 未安装,页面部署不可用(需重建镜像装依赖)')
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
            return jsonify({'success': False,
                            'message': '远程命令触发异常,详见服务端日志'}), 500
        system_logger.info('手动部署已触发(配置页按钮): 宿主机后台执行 git pull + docker 重建')
        return jsonify({'success': True,
                        'message': '部署已触发,服务将中断 1-3 分钟后自动恢复'})
    except paramiko.AuthenticationException:
        error_logger.warning('手动部署失败: SSH 密码错误')
        return jsonify({'success': False, 'message': 'SSH 密码错误'}), 401
    except Exception as e:
        # 异常对象不含密码,可安全记录;提示保持模糊防探测
        error_logger.warning(f'手动部署触发失败: {repr(e)[:160]}')
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
        result['remote_error'] = str(e)[:160] or 'GitHub API 不可达'

    _version_cache.update(ts=now, data=result)
    return jsonify(result)
