# -*- coding: utf-8 -*-
"""自动部署远程执行器: paramiko SSH(密码内置, 服务器为本人的低风险环境) → git pull + docker 重建
由 deploy.ps1 调用; 等价于手工 ssh root@123.56.175.189 后执行远程命令。
用法: python deploy_remote.py   (退出码 0=部署成功)"""
import sys
import paramiko

HOST, USER, PASSWORD = '123.56.175.189', 'root', 'Wk20010826!'
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
