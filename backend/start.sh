#!/bin/bash

# A股资金流入服务启动脚本

echo "======================================="
echo "  A股资金流入服务启动脚本"
echo "======================================="
echo

# 启动服务
echo "启动A股资金流入服务..."

# 启动服务（前台运行）
# exec 关键字:让 python 替换 bash 成为该进程(PID 1 由 compose 的 init:true 接管,
# tini 负责转发 SIGTERM)。没有 exec 时 SIGTERM 只给 bash、python 收不到,
# 每次停容器都要等 10 秒 SIGKILL——而 SIGKILL 会跳过 CNI 的端口规则清理,
# 残留的 DNAT 规则会遮蔽下一代规则,导致"容器 Up 但端口不通"(2026-09-06 事故根因)。
exec python3 /app/backend/app.py
