# 🛡️ Jarvis - 通用网络安全防卫模块

一个可插拔式的网络安全防卫模块，支持多种攻击检测和IP封禁功能。

## ✨ 功能特性

- **SQL注入检测** - 检测各种SQL注入攻击模式
- **XSS攻击检测** - 检测跨站脚本攻击
- **命令注入检测** - 检测系统命令注入
- **路径遍历检测** - 检测目录遍历攻击
- **LDAP注入检测** - 检测LDAP注入攻击
- **XXE攻击检测** - 检测XML外部实体攻击
- **SSRF检测** - 检测服务端请求伪造

## 🚀 快速开始

### 基本使用

```python
from flask import Flask
from Jarvis import SecurityMiddleware

app = Flask(__name__)

# 初始化安全中间件
security = SecurityMiddleware(app)

if __name__ == '__main__':
    app.run()
```

### 自定义配置

```python
from Jarvis import SecurityMiddleware
from Jarvis.config import get_config

config = get_config({
    'enabled': True,
    'ban_duration': 3600,      # 封禁时长（秒）
    'max_attempts': 5,          # 最大尝试次数
    'attempt_window': 300,      # 尝试窗口（秒）
    'whitelist': ['127.0.0.1'], # IP白名单
    'exempt_routes': ['/api/health'],  # 豁免路由
})

security = SecurityMiddleware(app, config)
```

### 添加管理接口

```python
from Jarvis.middleware import create_security_blueprint

# 创建管理蓝图
jarvis_bp = create_security_blueprint(security)
app.register_blueprint(jarvis_bp)
```

## 📡 API接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/jarvis/stats` | GET | 获取安全统计 |
| `/api/jarvis/banned` | GET | 获取封禁IP列表 |
| `/api/jarvis/events` | GET | 获取安全事件日志 |
| `/api/jarvis/ban` | POST | 封禁IP |
| `/api/jarvis/unban` | POST | 解封IP |

## 🔧 配置说明

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | True | 是否启用安全检测 |
| `enabled_checks` | list | 全部 | 启用的检测类型 |
| `sensitivity` | str | medium | 检测灵敏度 |
| `ban_duration` | int | 3600 | 封禁时长（秒） |
| `max_attempts` | int | 5 | 最大攻击尝试次数 |
| `attempt_window` | int | 300 | 尝试计数窗口（秒） |
| `whitelist` | list | [] | IP白名单 |
| `exempt_routes` | list | [] | 豁免检测的路由 |
| `data_dir` | str | data/jarvis | 数据存储目录 |

## 🎯 检测类型

### SQL注入
检测SELECT、INSERT、UPDATE、DELETE、UNION等SQL关键字，以及注释、存储过程等。

### XSS攻击
检测script标签、事件处理器、javascript协议等。

### 命令注入
检测管道符、分号、反引号等命令执行符号，以及常见系统命令。

### 路径遍历
检测../、..\\等路径遍历模式，以及敏感文件访问。

### LDAP注入
检测LDAP查询注入模式。

### XXE攻击
检测DOCTYPE、ENTITY等XML外部实体声明。

### SSRF
检测对内网地址、本地地址的请求。

## 📊 响应格式

### 攻击检测响应

```json
{
  "success": false,
  "error": "security_violation",
  "message": "检测到危险操作，您的IP已被记录",
  "details": {
    "attack_type": "SQL注入攻击",
    "attempts_left": 3,
    "ip": "192.168.1.100"
  }
}
```

### IP封禁响应

```json
{
  "success": false,
  "error": "access_denied",
  "message": "您的IP已被封禁",
  "details": {
    "reason": "sql_injection",
    "remaining_seconds": 3542
  }
}
```

## 📁 文件结构

```
Jarvis/
├── __init__.py          # 模块入口
├── security.py          # 核心安全检测
├── middleware.py        # Flask中间件
├── ip_manager.py        # IP管理
├── attack_patterns.py   # 攻击模式定义
├── config.py            # 配置文件
└── README.md            # 使用说明
```

## 🔒 安全响应头

Jarvis自动添加以下安全响应头：

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security`
- `Content-Security-Policy`

## 📝 日志记录

所有安全事件都会记录到 `data/jarvis/security_events.json`，包括：

- 攻击尝试
- IP封禁
- IP解封

## ⚠️ 注意事项

1. 本模块提供基础安全防护，不能替代专业的WAF
2. 建议结合HTTPS使用
3. 定期检查安全日志
4. 根据实际情况调整检测灵敏度
