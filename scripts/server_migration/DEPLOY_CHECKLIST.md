# 服务器合并迁移操作清单(StockRank × TrendZen)

> 维护窗口执行,全程约 10~15 分钟。任一步失败可按"回退"小节整体回退。
> 本清单覆盖 M1.2 数据库统一 + M1.4 部署统一一次性切换。
> 服务器容器引擎是 podman(命令用 podman/podman-compose);本清单所有命令已按服务器实际环境写。

## 前置确认

```
cd /root/StockRank
git pull                       # 拿到合并后的代码(quant/ 已并入本仓库)
podman ps                      # 记录当前运行的容器名(a-stock-backend / a-stock-nginx / trendzen-*)
df -h .                        # 确认磁盘余量(备份三库+account.json,总量很小)
ls /root/TrendZen/.env         # 确认旧 TrendZen 仓库根下有 .env(第 0 步要用)
```

## 第 0 步 补 quant/.env(新栈需要,一次性)

旧栈的 secrets 在独立仓库 /root/TrendZen/.env;合并后 quant 容器从 StockRank/quant/.env 读:

```
cp -a /root/TrendZen/.env /root/StockRank/quant/.env
grep -c ALIPAY /root/StockRank/quant/.env   # 确认内容拷到位
```

## 第 1 步 停容器 + 删容器 + 备份

```
podman stop trendzen-backend trendzen-frontend a-stock-backend a-stock-nginx 2>/dev/null
# 必须删掉(stop 不够):否则新栈 up 时报容器名已被占用
podman rm -f trendzen-backend trendzen-frontend a-stock-backend a-stock-nginx 2>/dev/null

mkdir -p backup/unify_db_$(date +%Y%m%d)
cp -a data/stockrank.db backend/data/stockrank.db backup/unify_db_$(date +%Y%m%d)/ 2>/dev/null
cp -a backend/data/mp_game.db backend/data/mp_vpay.db /root/TrendZen/data/trading.db backup/unify_db_$(date +%Y%m%d)/ 2>/dev/null
cp -a /root/TrendZen/backend/account.json /root/TrendZen/quant/backend/account.json quant/backend/account.json backup/unify_db_$(date +%Y%m%d)/ 2>/dev/null
ls -la backup/unify_db_$(date +%Y%m%d)/       # 确认备份非空
```

## 第 2 步 数据库合并 + 数据目录搬迁(幂等,可重跑)

```
cd /root/StockRank
python3 scripts/server_migration/migrate_unify_db.py
# 脚本自动发现三库(含 /root/TrendZen/data/trading.db)+quant account.json,
# 迁入 data/stockrank.db,输出表数/行数校验报告;旧库改名 .db.bak 保留

# K线 parquet 与运行缓存不在 SQLite 里,必须从旧 TrendZen 数据目录拷过来:
cp -a /root/TrendZen/data/kline /root/StockRank/quant/data/
cp -a /root/TrendZen/data/pytdx_hosts.json /root/TrendZen/data/a_share_spot.json \
      /root/TrendZen/data/download_universe.json /root/TrendZen/data/custom_etfs.json \
      /root/TrendZen/data/removed_etfs.json /root/StockRank/quant/data/ 2>/dev/null

# 核对业务库行数(自选/扫描/回测/持仓应非零):
sqlite3 data/stockrank.db "SELECT 'watchlist',COUNT(*) FROM watchlist UNION ALL \
 SELECT 'scan_signals',COUNT(*) FROM scan_signals UNION ALL \
 SELECT 'backtest_results',COUNT(*) FROM backtest_results UNION ALL \
 SELECT 'positions',COUNT(*) FROM positions;"
```

## 第 3 步 启动新栈

```
cd /root/StockRank
git pull                        # 先拉最新修正
```

### 3.1 彻底清理旧栈(podman 关键坑:容器挂在 pod 里,只删容器不够)

```
cd /root/StockRank/docker
podman-compose down                        # 收掉半成品新栈
podman pod ps                              # 看旧栈 pod(名字通常含 trendzen/docker_*)
podman pod rm -f $(podman pod ps -q) 2>/dev/null   # 旧 pod 整个删(连带里面旧容器)
podman rm -f a-stock-backend a-stock-nginx trendzen-backend trendzen-frontend 2>/dev/null
podman network ls                          # 看残留网络(trendzen_*/docker_* )
podman network rm trendzen_default docker_default docker_stock-network 2>/dev/null
podman ps -a; podman network ls            # 确认无 a-stock/trendzen 残留
```

> 不删旧网络的话,它会占着 10.89.0.0/24 网段,新 stock-network 被迫换网段,
> node-bridge 绑定旧网关 IP 会直接 Exited(1)。

### 3.2 起新栈

```
podman-compose up -d --build
podman-compose ps             # 应有 backend / quant / nginx / node-bridge / autoheal
```

### 3.3 node-bridge 网关校准(一次性)

```
podman network ls | grep stock-network        # 找实际网络名(如 stockrank_stock-network)
podman network inspect <网络名> --format '{{(index .subnets 0).gateway}}'
# 把查到的网关写进 .env 并重建 node-bridge:
sed -i "s/^DOCKER_GATEWAY_IP=.*/DOCKER_GATEWAY_IP=<查到的网关>/" .env
podman rm -f a-stock-node-bridge && podman-compose up -d node-bridge
podman ps | grep node-bridge                  # 状态应为 Up
```

### 3.4 autoheal 前置:启用 podman socket(一次性)

```
systemctl enable --now podman.socket
ls /run/podman/podman.sock                    # 确认 socket 存在
podman rm -f a-stock-autoheal && podman-compose up -d autoheal
```

要点:
- quant 容器不再映射任何公网端口,只能被 nginx 在 stock-network 内网访问。
- quant 容器注入 `QUANT_GATE_MODE=1` + `QUANT_GATE_SECRET`(与 nginx tz_gate SECRET 同值),
  量化登录/注册/支付入口即 410 下线,鉴权统一走主站。
- quant 侧 secrets 读 `quant/.env`(第 0 步从旧 TrendZen 仓库拷来)。
- 容器互访一律用容器名(a-stock-quant / a-stock-backend):podman 的 aardvark DNS
  保证注册容器名,compose 服务名不保证。

## 第 4 步 验证清单(逐项过)

| 项目 | 方法 | 预期 |
|---|---|---|
| 主站登录 | 主站输入每日密码(+OTP) | 登录成功,响应 Set-Cookie 含 tz_gate |
| 量化入口 | 已登录状态访问 https://0vk.top/quant/ | 直接进入量化界面(无需二次登录) |
| 门禁拦截 | 无痕窗口直接访问 /quant/ | 302 踢回主站首页 |
| 旧链接 | 访问 /TrendZen/ 或 /TrendZen/api/x | 301 到 /quant/... |
| quant 内部端口 | 宿主机 `curl http://127.0.0.1:8001` | 拒绝连接(端口已收回) |
| 量化策略 | 量化区选任一策略跑扫描 | 正常执行(vk 管理员全策略开放) |
| 模拟盘 | 量化区买入/卖出一笔 | 余额/持仓变化,重启容器后仍在(已入库) |
| 套利监控 | 等待 60s 看 Flask 日志 trendzen_arb | 正常轮询(Flask 容器内网直连 quant:8000) |
| 云图推送 | quant 推送大盘云图 | Flask 收到(MARKET_MAP_PUSH_URL 指向 backend:5000) |
| WS 行情 | 量化区订阅自选 | 实时推送正常 |
| 小程序 | 小程序端任一接口 | 正常(mp 表已并入统一库) |

## 回退(整体)

```
cd /root/StockRank/docker && podman-compose down
cd /root/StockRank && git reset --hard <切换前的commit>   # 本地已推远端则 git push -f 恢复
# 恢复备份:
cp -a /root/StockRank/backup/unify_db_YYYYMMDD/. /root/StockRank/data/   # 按原路径放回
cd /root/TrendZen/docker && podman-compose up -d --build   # 旧栈文件还在 /root/TrendZen 独立仓库
```

## 常见问题

- **up 报 container has joined pod ... dependency container ... is not a member of the pod**:
  旧栈容器没删干净(挂在旧 pod 里)。按 3.1 步 `podman pod rm -f` 连 pod 一起删后重试。
- **up 报容器名已被占用**:`podman rm -f a-stock-backend a-stock-nginx trendzen-backend trendzen-frontend` 后重试。
- **up 报 Env file ... does not exist**:没做第 0 步,`cp -a /root/TrendZen/.env /root/StockRank/quant/.env`。
- **node-bridge 起来就 Exited(1)**:绑定的网关 IP 不是本机网段的网关。按 3.3 步查实际网关并改 .env。
- **autoheal 起来就 Exited(1)**:宿主机没启用 podman socket。按 3.4 步 `systemctl enable --now podman.socket`。
- **quant 容器反复重启**:看 `podman logs a-stock-quant`;多为 quant/.env 缺失或依赖没装全。
- **容器读到的行数和宿主机 sqlite3 不一致**:quant 没指向统一库。核查 DB_PATH 应为
  /app/unified_data/stockrank.db;若显示 /app/data/stockrank.db,说明容器还是旧配置,force-recreate 重建。
  (注意 quant 的 /app/data 挂的是 quant/data,只放K线parquet/缓存,不是统一库)
- **/quant/ 一直 302 回首页**:cookie 未带上;确认是从主站登录进入的(登录成功才下发 tz_gate)。
- **nginx 起不来**:`podman exec a-stock-nginx nginx -t` 看报错;多为证书路径。
- **套利监控连不上**:确认在容器网内 `podman exec a-stock-backend curl -s http://a-stock-quant:8000/health`;
  本地开发机需把 config/trendzen_arb.json 的 base_url 改为 http://127.0.0.1:8000。
