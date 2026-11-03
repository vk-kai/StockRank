# -*- coding: utf-8 -*-
"""自动部署远程执行器: paramiko SSH → git pull + docker 重建
由 deploy.ps1 调用; 等价于手工 ssh root@123.56.175.189 后执行远程命令。
密码优先读环境变量 DEPLOY_SSH_PASSWORD, 未设置则交互输入, 不再落盘仓库。
用法: python deploy_remote.py   (退出码 0=部署成功)"""
import os
import sys
import getpass
import paramiko

HOST, USER = '123.56.175.189', 'root'
PASSWORD = os.environ.get('DEPLOY_SSH_PASSWORD') or getpass.getpass(f'SSH密码 {USER}@{HOST}: ')
CMD = ('cd /root/StockRank/docker && git pull && '
       'docker compose down && docker compose up -d --build')


def main():
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())   # 服务器指纹首次记录
    cli.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    try:
        stdin, stdout, stderr = cli.exec_command(CMD, get_pty=True, timeout=900)
        for line in iter(stdout.readline, ''):
            print(line, end='')          # 实时回显远程输出(pull/构建进度)
        code = stdout.channel.recv_exit_status()
        print(f'\n[remote exit] {code}')
        sys.exit(code)
    finally:
        cli.close()


if __name__ == '__main__':
    main()
