# 一键部署脚本: git push -> SSH 到服务器 -> git pull -> docker 重建
# 用法: 在 StockRank 目录下执行  .\deploy.ps1  或  git deploy
# 密码: ssh 连接时会提示 "root@123.56.175.189's password:", 手动输入即可(密码不落盘)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# ---------- 1. 推送代码 ----------
Write-Host ''
Write-Host '=====> [1/3] git push origin main ...' -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] push 失败, 跳过远程部署' -ForegroundColor Red
    exit 1
}
Write-Host '[OK] push 完成' -ForegroundColor Green

# ---------- 2. 远程拉取 + 重建 ----------
Write-Host ''
Write-Host '=====> [2/3] 连接服务器 123.56.175.189 (提示密码时输入, 预计 2-5 分钟)...' -ForegroundColor Cyan
$remote = 'cd /root/StockRank/docker && git pull && docker compose down && docker compose up -d --build'
ssh -t root@123.56.175.189 $remote
if ($LASTEXITCODE -ne 0) {
    Write-Host '[!] 部署命令返回异常, 请上服务器 docker compose logs 检查' -ForegroundColor Yellow
    exit 1
}

# ---------- 3. 完成 ----------
Write-Host ''
Write-Host '=====> [3/3] 部署完成' -ForegroundColor Green
Write-Host '站点: https://0vk.top  (容器重启后经济周期采集线程 1 分钟内自动首采)' -ForegroundColor Green
