# -*- coding: utf-8 -*-
"""个人数字分身 Agent 核心包

源项目: 桌面 WeChatExport/个人Agent (本地长期运行的主战场, 代码只增不删)。
本包由 scripts/sync_agent_local.py(或源项目里的 同步到云端.bat)从源项目同步而来,
同步时会自动把顶层导入改写为 agent_core. 前缀(见 scripts/agent_adapt_imports.py)。

数据目录: backend/agent_data/(git 忽略, 由人工/同步器维护)
  - agent_data/Agent知识库/   ← 本地 Agent知识库
  - agent_data/聊天记录数据/  ← 本地 聊天记录数据
配置文件: agent_core/config.json(git 忽略, 模板见 config.example.json)
"""
