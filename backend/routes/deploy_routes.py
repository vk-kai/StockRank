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
    "docker compose up -d --build"
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
