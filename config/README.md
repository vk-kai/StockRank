# 配置文件说明

本目录包含系统的所有配置文件，请根据以下说明进行配置。

## 📁 配置文件列表

### 1. AI大模型配置 (`ai_config.json`)

用于配置AI大模型API，用于分析重要新闻。

```json
{
  "enabled": false,
  "api_url": "https://api.openai.com/v1/chat/completions",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "model": "gpt-3.5-turbo",
  "temperature": 0.7,
  "max_tokens": 1000,
  "timeout": 30
}
```

**字段说明：**
- `enabled`: 是否启用AI分析功能（true/false）
- `api_url`: AI模型API地址
  - OpenAI: `https://api.openai.com/v1/chat/completions`
  - 国内镜像: 根据实际情况填写
  - 自定义模型: 填写您的模型API地址
- `api_key`: API密钥
  - OpenAI: 以 `sk-` 开头的密钥
  - 其他平台: 根据平台要求填写
- `model`: 使用的模型名称
  - OpenAI: `gpt-3.5-turbo`, `gpt-4`, `gpt-4-turbo`等
  - 其他平台: 根据平台支持的模型填写
- `temperature`: 温度参数（0-1），控制回答的随机性
  - 0: 最确定性的回答
  - 1: 最随机的回答
  - 建议: 0.7
- `max_tokens`: 最大返回token数
  - 建议: 1000
- `timeout`: API请求超时时间（秒）
  - 建议: 30

**示例配置：**

```json
{
  "enabled": true,
  "api_url": "https://api.openai.com/v1/chat/completions",
  "api_key": "sk-proj-xxxxxxxxxxxxx",
  "model": "gpt-3.5-turbo",
  "temperature": 0.7,
  "max_tokens": 1000,
  "timeout": 30
}
```

---

### 2. 飞书机器人配置 (`feishu_config.json`)

用于配置飞书机器人，实现重要新闻推送。

```json
{
  "enabled": false,
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxx",
  "secret": "xxxxxxxxxx",
  "msg_type": "interactive"
}
```

**字段说明：**
- `enabled`: 是否启用飞书推送（true/false）
- `webhook_url`: 飞书机器人Webhook地址
  - 获取方式: 飞书群设置 → 群机器人 → 添加机器人 → 自定义机器人
  - 格式: `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxx`
- `secret`: 机器人签名密钥（可选）
  - 获取方式: 创建机器人时显示
  - 如果不使用签名验证，可以留空
- `msg_type`: 消息类型
  - `interactive`: 卡片消息（推荐）
  - `text`: 文本消息

**示例配置：**

```json
{
  "enabled": true,
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/12345678-1234-1234-1234-1234567890ab",
  "secret": "your-secret-key-here",
  "msg_type": "interactive"
}
```

---

### 3. 股票监控配置 (`stock_monitor.json`)

用于配置需要监控的股票，当新闻中出现相关关键词时自动推送。

```json
{
  "enabled": false,
  "stocks": [
    {
      "name": "股票名称",
      "code": "股票代码",
      "keywords": ["关键词1", "关键词2"],
      "enabled": true
    }
  ]
}
```

**字段说明：**
- `enabled`: 是否启用股票监控（true/false）
- `stocks`: 监控的股票列表
  - `name`: 股票名称（用于显示）
  - `code`: 股票代码（如：300338）
  - `keywords`: 关键词列表，新闻中出现这些关键词会触发推送
  - `enabled`: 是否启用该股票监控

**示例配置：**

```json
{
  "enabled": true,
  "stocks": [
    {
      "name": "同花顺",
      "code": "300338",
      "keywords": ["同花顺", "300338", "花顺"],
      "enabled": true
    },
    {
      "name": "东方财富",
      "code": "300059",
      "keywords": ["东方财富", "300059", "东财"],
      "enabled": true
    },
    {
      "name": "贵州茅台",
      "code": "600519",
      "keywords": ["茅台", "600519", "贵州茅台"],
      "enabled": true
    }
  ]
}
```

---

### 4. AI提示词配置 (`ai_prompt.txt`)

用于配置AI分析新闻时使用的提示词。

**说明：**
- 该文件包含AI分析新闻的系统提示词
- 可以根据需要自定义修改
- 默认提示词已针对A股市场优化

**示例：**
```
你是一个专业A股交易信息分析助手。 

你的任务是：判断一条信息（新闻或行情异动）是否对A股产生"实质性影响"...

（完整提示词请查看文件内容）
```

---

## 🔧 配置步骤

### 1. 启用AI分析功能

1. 打开 `ai_config.json`
2. 设置 `enabled` 为 `true`
3. 填写您的AI模型API地址和密钥
4. 选择合适的模型名称
5. 保存文件

### 2. 启用飞书推送

1. 在飞书群中添加自定义机器人
2. 复制Webhook地址和签名密钥
3. 打开 `feishu_config.json`
4. 设置 `enabled` 为 `true`
5. 填写Webhook地址和密钥
6. 保存文件

### 3. 配置股票监控

1. 打开 `stock_monitor.json`
2. 设置 `enabled` 为 `true`
3. 在 `stocks` 数组中添加您关注的股票
4. 为每个股票设置关键词
5. 保存文件

### 4. 自定义AI提示词（可选）

1. 打开 `ai_prompt.txt`
2. 根据需要修改提示词
3. 保存文件

---

## ⚠️ 注意事项

1. **安全性**：
   - 请勿将包含密钥的配置文件提交到Git仓库
   - 这些文件已在 `.gitignore` 中配置，不会被提交

2. **配置生效**：
   - 修改配置文件后需要重启后端服务才能生效
   - 前端配置页面修改会立即生效

3. **API限制**：
   - AI API可能有调用频率限制
   - 飞书机器人有消息发送频率限制
   - 请合理配置监控关键词

4. **测试建议**：
   - 先使用测试数据验证配置是否正确
   - 确认推送功能正常后再启用正式环境

---

## 📞 获取帮助

如有问题，请查看：
- [README.md](../README.md) - 项目总体说明
- [API文档](../docs/api.md) - API接口文档
- [部署指南](../docs/deploy.md) - 部署说明
