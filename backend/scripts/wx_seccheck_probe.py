#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""微信 msgSecCheck 实测探针 —— 排查「敏感词微信竟然放行」到底是调用问题还是模型判定。

背景:弹幕墙留言服务端强制送检(scene=2),但实测微信对部分敏感内容仍返回
suggest=pass。本探针直接调与业务完全相同的 _do_msg_sec_check(),把
「本地词库判定」与「微信判定」并排打出来,方便对照定位。

隐私/安全约定:
  - 待测文本与 openid 由使用者手动填写在 scripts/sec_probe_words.txt(已 git 忽略);
  - 本脚本输出**永不回显文本内容**,只报 序号/字数/本地判定/错误码/trace_id,
    避免敏感内容进终端、日志或 AI 对话。

用法(在 backend 目录运行):
    python scripts/wx_seccheck_probe.py              # scene=2(评论,同弹幕墙)
    python scripts/wx_seccheck_probe.py --scene 1    # 换场景对比:1资料 3论坛 4社交日志
    python scripts/wx_seccheck_probe.py --openid oXX # 命令行覆盖 words 文件里的 openid

words 文件格式(每行一条,# 开头为注释):
    openid=你的真实openid       ← 必填;该用户须「近2小时访问过小程序」
    <待测文本第1条>
    <待测文本第2条>

判读:
    本地=拦 微信=pass   → 微信确实放行(既有结论),本地词库兜底是唯一防线
    本地=放 微信=pass   → 微信模型漏判;trace_id 留证,词按口径补进 _LOCAL_BLOCK_CN
    errcode=61010       → openid 不合法/近2小时未活跃:判定不可信,先换真实 openid
    errcode!=0(其他)    → 调用侧问题,看 errmsg(api.weixin.qq.com 文档对码)
"""
import os
import sys
import time
import argparse

# 脚本位于 backend/scripts/,把 backend/ 加入 sys.path 以导入各子包
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from routes.mp_sec_routes import (  # noqa: E402
    LABEL_NAMES, _call_wx_api, get_access_token,
    load_mp_sec_config, local_text_blocked)

WORDS_FILE = os.path.join(_HERE, 'sec_probe_words.txt')


def load_inputs():
    """读 words 文件:openid= 行取 openid,其余非注释行逐条作待测文本。"""
    openid, texts = '', []
    if not os.path.exists(WORDS_FILE):
        return openid, texts
    with open(WORDS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            if s.lower().startswith('openid='):
                openid = s.split('=', 1)[1].strip()
            else:
                texts.append(s)
    return openid, texts


def main():
    ap = argparse.ArgumentParser(description='微信 msgSecCheck 实测探针(输出不回显文本)')
    ap.add_argument('--scene', type=int, choices=(1, 2, 3, 4), default=2,
                    help='送检场景:1资料 2评论(默认,同弹幕墙) 3论坛 4社交日志')
    ap.add_argument('--openid', default='', help='覆盖 words 文件里的 openid=')
    args = ap.parse_args()

    openid, texts = load_inputs()
    openid = args.openid or openid
    if not openid:
        print('未提供 openid:请在 scripts/sec_probe_words.txt 加一行 openid=真实openid')
        print('  msgSecCheck 2.0 判定依赖真实用户身份(须近2小时访问过小程序),')
        print('  拿编造的 openid 送检,微信判定会明显偏松——这是「没拦住」最常见的假象。')
        return 1
    if not texts:
        print('待测文本为空:请在 scripts/sec_probe_words.txt 里每行填一条(我来留空,你来填)。')
        return 1
    cfg = load_mp_sec_config()
    if not cfg.get('appid') or not cfg.get('appsecret'):
        print('config/mp_sec_config.json 缺 appid/appsecret,无法送检。')
        return 1
    try:
        get_access_token()   # 预热并验证凭证,失败早暴露
    except Exception as e:
        print(f'access_token 获取失败: {e}')
        return 1

    print(f'接口: POST /wxa/msg_sec_check  version=2  scene={args.scene}')
    print(f'openid: {openid[:6]}…({len(openid)}位)  待测 {len(texts)} 条  输出不含文本\n')

    pass_cnt = risky_cnt = err_cnt = 0
    for i, text in enumerate(texts, 1):
        local = '拦' if local_text_blocked(text) else '放'
        try:
            # 直接打 /wxa/msg_sec_check,与业务完全同参:version=2 + openid + scene + content
            resp = _call_wx_api('/wxa/msg_sec_check', {
                'version': 2, 'openid': openid, 'scene': args.scene,
                'content': text})
            err = resp.get('errcode')
            result = resp.get('result') or {}
            suggest, label = result.get('suggest'), result.get('label')
            if err == 0 and suggest == 'pass':
                pass_cnt += 1
            elif err == 0:
                risky_cnt += 1
            else:
                err_cnt += 1
            label_str = f'{label}({LABEL_NAMES.get(label, "?")})' \
                if label is not None else '-'
            trace = resp.get('trace_id') or '-'
            print(f'#{i:<4} len={len(text):<3} 本地={local}  errcode={err}  '
                  f'suggest={suggest}  label={label_str}  trace={trace}')
        except Exception as e:   # 网络/凭证异常:只含错误信息,不含文本
            err_cnt += 1
            print(f'#{i:<4} len={len(text):<3} 本地={local}  调用异常: {type(e).__name__}: {e}')
        print('-' * 60)
        time.sleep(0.5)          # 温和限速,避开微信 QPS 限制

    print(f'\n合计: 微信放行 {pass_cnt} / 拦截 {risky_cnt} / 出错 {err_cnt}')
    if pass_cnt:
        print('有被微信放行的条目:若其 本地=放,说明模型漏判(凭 trace_id 留证),'
              '按词库口径补进 _LOCAL_BLOCK_CN。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
