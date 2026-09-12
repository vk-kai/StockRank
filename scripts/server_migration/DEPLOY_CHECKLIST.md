# 服务器合并迁移操作清单(StockRank × TrendZen)

> 维护窗口执行,全程约 10~15 分钟。任一步失败可按"回退"小节整体回退。
> 本清单覆盖 M1.2 数据库统一 + M1.4 部署统一一次性切换。

## 前置确认

```
cd /path/to/StockRank
git pull                       # 拿到合并后的代码(quant/ 已并入本仓库)
docker ps                      # 记录当前运行的容器名(a-stock-backend / a-stock-nginx / trendzen-*)
df -h .                        # 确认磁盘余量(备份三库+account.json,总量很小)
```

## 第 1 步 停容器 + 备份

```
docker stop trendzen-backend trendzen-frontend 2>/dev/null
docker stop a-stock-backend a-stock-nginx 2>/dev/null

mkdir -p backup/unify_db_$(date +%Y%m%d)
cp -a data/stockrank.db backend/data/stockrank.db backup/unify_db_$(date +%Y%m%d)/ 2>/dev/null
cp -a backend/data/mp_game.db backend/data/mp_vpay.db quant/backend/trading.db backup/unify_db_$(date +%Y%m%d)/ 2>/dev/null
cp -a quant/backend/account.json backup/unify_db_$(date +%Y%m%d)/ 2>/dev/null
ls -la backup/unify_db_$(date +%Y%m%d)/       # 确认备份非空
```

## 第 2 步 数据库合并(幂等,可重跑)

```
cd quant && python ../scripts/server_migration/migrate_unify_db.py && cd ..
# 脚本自动发现三库+account.json,迁入 data/stockrank.db,输出表数/行数校验报告
# 旧库改名 .db.bak 保留;account.json 导入后改名 .imported
```

## 第 3 步 切换 compose 并启动新栈

```
# 停干净旧栈(含旧 frontend 容器)
docker rm -f trendzen-frontend 2>/dev/null
cd docker
docker compose up -d --build
docker compose ps              # 应有 backend / quant / nginx / node-bridge / autoheal
```

要点:
- quant 容器不再映射任何公网端口,只能被 nginx 在 stock-network 内网访问。
- quant 容器注入 `QUANT_GATE_MODE=1` + `QUANT_GATE_SECRET`(与 nginx tz_gate SECRET 同值),
  量化登录/注册/支付入口即 410 下线,鉴权统一走主站。
- quant 侧 secrets 仍读 `quant/.env`(原文件原样复用,无需改动)。

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
cd docker && docker compose down
git checkout <上一个tag/commit> -- .     # 或 git reset --hard 到切换前
# 恢复备份:
cp -a backup/unify_db_YYYYMMDD/. /path/to/对应位置/
cd quant/docker && docker compose up -d --build   # 旧栈文件在 git 历史里
```

## 常见问题

- **quant 容器反复重启**:看 `docker logs a-stock-quant`;多为 quant/.env 缺失或依赖没装全。
- **/quant/ 一直 302 回首页**:cookie 未带上;确认是从主站登录进入的(登录成功才下发 tz_gate)。
- **nginx 起不来**:`docker exec a-stock-nginx nginx -t` 看报错;多为证书路径。
- **套利监控连不上**:确认在容器网内 `docker exec a-stock-backend curl -s http://quant:8000/health`;
  本地开发机需把 config/trendzen_arb.json 的 base_url 改为 http://127.0.0.1:8000。
