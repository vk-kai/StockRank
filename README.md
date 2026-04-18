<div align="center">

# 📈 StockRank - A股智能分析系统

**实时监控 · AI分析 · 智能推送 · 专业决策**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8+-brightgreen.svg)](https://www.python.org/)
[![Vue](https://img.shields.io/badge/vue-3.0+-brightgreen.svg)](https://vuejs.org/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

[在线演示](#) · [快速开始](#快速开始) · [功能特性](#功能特性) · [部署指南](#部署指南)

</div>

---

## 📋 目录

- [项目简介](#项目简介)
- [功能特性](#功能特性)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API文档](#api文档)
- [部署指南](#部署指南)
- [开发指南](#开发指南)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)
- [联系方式](#联系方式)

---

## 🎯 项目简介

StockRank 是一个专业的A股市场智能分析系统，集成了实时数据采集、AI智能分析、飞书机器人推送等功能。通过对接东方财富和同花顺数据源，为投资者提供全方位的市场监控和决策支持。

### ✨ 核心亮点

| 特性 | 描述 |
|------|------|
| 🔄 **实时监控** | 每5分钟自动更新板块资金流入数据，15秒采集一次新闻 |
| 🤖 **AI分析** | 集成GPT等大模型，智能分析新闻对A股的影响 |
| 📢 **智能推送** | 支持飞书机器人推送重要新闻和关注股票动态 |
| 📊 **可视化大屏** | 使用ECharts构建专业金融数据可视化界面 |
| 🎯 **自定义监控** | 支持自定义股票监控，关键词匹配自动推送 |
| 🐳 **容器化部署** | 完整的Docker部署方案，一键启动 |

---

## 🚀 功能特性

### 1. 实时数据采集

- ✅ 板块资金流入数据（每5分钟更新）
- ✅ 同花顺实时新闻（每15秒采集）
- ✅ 历史数据追溯（支持30天）
- ✅ 异常自动重试机制

### 2. AI智能分析

- ✅ 自动识别重要新闻（importance=3）
- ✅ AI深度分析新闻影响
- ✅ 判断影响类型（即时/延迟）
- ✅ 识别相关板块和市场
- ✅ 生成投资建议

### 3. 智能推送系统

- ✅ 飞书机器人实时推送
- ✅ 重要新闻自动推送
- ✅ 自定义股票监控推送
- ✅ 卡片消息格式化

### 4. 可视化展示

- ✅ 板块资金流向趋势图
- ✅ 实时TOP10榜单
- ✅ 重要新闻滚动展示
- ✅ 金融风格界面设计

### 5. 配置管理

- ✅ AI模型配置界面
- ✅ 飞书机器人配置
- ✅ 股票监控配置
- ✅ AI提示词自定义

---

## 🏗️ 技术架构

### 技术栈

#### 后端
- **Python 3.8+** - 核心开发语言
- **Flask** - Web框架
- **Requests** - HTTP客户端
- **ECharts** - 数据可视化

#### 前端
- **Vue 3** - 前端框架
- **Vue Router** - 路由管理
- **Axios** - HTTP客户端
- **ECharts** - 图表库

#### 数据源
- **东方财富** - 板块资金流入数据
- **同花顺** - 实时新闻数据

#### AI服务
- **OpenAI API** - GPT模型
- **自定义API** - 支持其他兼容接口

#### 推送服务
- **飞书机器人** - Webhook推送

### 系统架构图

```
┌─────────────────┐
│   数据采集层     │
│  ┌───────────┐  │
│  │ 板块数据   │  │
│  │ 新闻数据   │  │
│  └───────────┘  │
└────────┬────────┘
         │
┌────────▼────────┐
│   数据处理层     │
│  ┌───────────┐  │
│  │ 数据清洗   │  │
│  │ AI分析    │  │
│  └───────────┘  │
└────────┬────────┘
         │
┌────────▼────────┐
│   业务逻辑层     │
│  ┌───────────┐  │
│  │ 资金分析   │  │
│  │ 新闻推送   │  │
│  └───────────┘  │
└────────┬────────┘
         │
┌────────▼────────┐
│   展示层         │
│  ┌───────────┐  │
│  │ Web界面   │  │
│  │ 飞书推送   │  │
│  └───────────┘  │
└─────────────────┘
```

---

## 🎬 快速开始

### 前置要求

- Python 3.8+
- Node.js 14+
- npm 或 yarn

### 安装步骤

#### 1. 克隆项目

```bash
git clone https://github.com/yourusername/StockRank.git
cd StockRank
```

#### 2. 后端配置

```bash
# 安装Python依赖
cd backend
pip install -r requirements.txt

# 配置AI服务（可选）
cp ../config/ai_config.json.example ../config/ai_config.json
# 编辑 ai_config.json 填入您的API密钥

# 配置飞书推送（可选）
cp ../config/feishu_config.json.example ../config/feishu_config.json
# 编辑 feishu_config.json 填入您的Webhook地址

# 启动后端服务
python app.py
```

#### 3. 前端配置

```bash
# 安装前端依赖
cd ../frontend
npm install

# 启动开发服务器
npm run dev
```

#### 4. 访问系统

打开浏览器访问：`http://localhost:5173`

---

## ⚙️ 配置说明

详细配置说明请查看：[配置文件说明](config/README.md)

### AI模型配置

编辑 `config/ai_config.json`：

```json
{
  "enabled": true,
  "api_url": "https://api.openai.com/v1/chat/completions",
  "api_key": "sk-your-api-key",
  "model": "gpt-3.5-turbo",
  "temperature": 0.7,
  "max_tokens": 1000,
  "timeout": 30
}
```

### 飞书机器人配置

编辑 `config/feishu_config.json`：

```json
{
  "enabled": true,
  "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/your-webhook",
  "secret": "your-secret",
  "msg_type": "interactive"
}
```

### 股票监控配置

编辑 `config/stock_monitor.json`：

```json
{
  "enabled": true,
  "stocks": [
    {
      "name": "同花顺",
      "code": "300338",
      "keywords": ["同花顺", "300338", "花顺"],
      "enabled": true
    }
  ]
}
```

---

## 📖 API文档

### 数据接口

#### 获取当前资金流入

```
GET /api/flow/current
```

**响应示例：**

```json
{
  "success": true,
  "data": [
    {
      "rank": 1,
      "name": "半导体",
      "flow": 123456789,
      "change": 0.05
    }
  ],
  "timestamp": "2026-04-18T12:00:00"
}
```

#### 获取历史数据

```
GET /api/flow/history?days=7
```

#### 获取新闻数据

```
GET /api/news?limit=50
```

### 配置接口

#### 获取AI配置

```
GET /api/config/ai
```

#### 更新AI配置

```
POST /api/config/ai
```

#### 获取飞书配置

```
GET /api/config/feishu
```

#### 更新飞书配置

```
POST /api/config/feishu
```

---

## 🐳 部署指南

### Docker部署（推荐）

#### 1. 构建镜像

```bash
docker build -t stockrank:latest .
```

#### 2. 运行容器

```bash
docker run -d \
  --name stockrank \
  -p 5000:5000 \
  -p 5173:5173 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config \
  stockrank:latest
```

#### 3. 访问系统

打开浏览器访问：`http://localhost:5173`

### 手动部署

详细的手动部署指南请查看：[部署文档](docs/deploy.md)

---

## 💻 开发指南

### 项目结构

```
StockRank/
├── backend/              # 后端代码
│   ├── app.py           # Flask应用
│   ├── config.py        # 配置管理
│   ├── data_collector.py # 数据采集
│   ├── data_processor.py # 数据处理
│   ├── news_collector.py # 新闻采集
│   ├── news_processor.py # 新闻处理
│   ├── ai_analyzer.py   # AI分析
│   ├── feishu_pusher.py # 飞书推送
│   └── stock_monitor.py # 股票监控
├── frontend/            # 前端代码
│   ├── src/
│   │   ├── App.vue      # 首页
│   │   ├── NewsPage.vue # 新闻页
│   │   ├── ConfigPage.vue # 配置页
│   │   └── router.js    # 路由配置
│   └── package.json
├── config/              # 配置文件
│   ├── ai_config.json   # AI配置
│   ├── feishu_config.json # 飞书配置
│   ├── stock_monitor.json # 股票监控
│   └── ai_prompt.txt    # AI提示词
├── data/                # 数据目录
├── logs/                # 日志目录
└── README.md            # 项目文档
```

### 开发环境搭建

```bash
# 安装开发依赖
pip install -r requirements-dev.txt

# 运行测试
pytest

# 代码格式化
black .

# 代码检查
flake8
```

---

## ❓ 常见问题

### Q: 如何获取OpenAI API密钥？

A: 访问 [OpenAI官网](https://platform.openai.com/) 注册账号，在API Keys页面创建密钥。

### Q: 如何创建飞书机器人？

A: 
1. 打开飞书群设置
2. 点击"群机器人" → "添加机器人"
3. 选择"自定义机器人"
4. 复制Webhook地址和签名密钥

### Q: 数据采集频率可以修改吗？

A: 可以。修改 `backend/config.py` 中的相关参数：
- `DATA_COLLECTION_INTERVAL`: 板块数据采集间隔（默认5分钟）
- `NEWS_COLLECTION_INTERVAL`: 新闻采集间隔（默认15秒）

### Q: 支持哪些AI模型？

A: 支持所有兼容OpenAI API格式的模型：
- OpenAI: GPT-3.5, GPT-4
- 国内镜像: 各种GPT镜像站
- 自定义模型: 任何兼容OpenAI API的服务

---

## 🤝 贡献指南

我们欢迎所有形式的贡献！

### 贡献方式

1. Fork本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

### 代码规范

- Python代码遵循PEP 8规范
- 使用Black进行代码格式化
- 编写单元测试
- 更新相关文档

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

---

## 📞 联系方式

- 项目主页: [https://github.com/yourusername/StockRank](https://github.com/yourusername/StockRank)
- 问题反馈: [Issues](https://github.com/yourusername/StockRank/issues)
- 邮箱: your.email@example.com

---

## 🙏 致谢

感谢以下开源项目：

- [Vue.js](https://vuejs.org/)
- [Flask](https://flask.palletsprojects.com/)
- [ECharts](https://echarts.apache.org/)
- [OpenAI](https://openai.com/)

---

<div align="center">

**⭐ 如果这个项目对您有帮助，请给一个Star支持一下！⭐**

Made with ❤️ by StockRank Team

</div>
