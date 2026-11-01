# -*- coding: utf-8 -*-
"""临时核实: 关系网络的节点/边是否混入群聊"""
import json
import urllib.request

# 1) 档案里的类别分布
rel = json.load(open(r'c:\Users\Administrator\Desktop\WeChatExport\Agent知识库\联系人关系档案.json', encoding='utf-8'))
kinds = {}
for c in rel:
    kinds[c.get('类别', '?')] = kinds.get(c.get('类别', '?'), 0) + 1
print('档案类别分布:', kinds)

# 2) 运行中的接口: 关系图节点里有没有群聊
groups = {c['姓名'] for c in rel if c.get('类别') == '群聊'}
print('档案中群聊条目数:', len(groups))
g = json.loads(urllib.request.urlopen('http://127.0.0.1:8765/api/network/graph', timeout=30).read())
hit = [n['name'] for n in g['nodes'] if n['name'] in groups]
print('关系图节点总数:', len(g['nodes']), ' 其中群聊节点:', len(hit))
print('混入的群聊示例:', hit[:10])
print('共同群边总数:', len(g['edges']), ' 示例:', g['edges'][:3])
# 边的端点是否有人名不在节点里
names = {n['name'] for n in g['nodes']}
bad = [e for e in g['edges'] if e['a'] not in names or e['b'] not in names]
print('端点不在节点集的边:', len(bad))
