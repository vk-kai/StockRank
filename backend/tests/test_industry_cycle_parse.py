"""industry_cycle _parse_industry_result 容错回归。

2026-07-22：AI 在 detail 字符串里用了未转义的英文双引号（中文里很自然，如
…炒作"封装技术瓶颈"…），标准 json.loads 直接失败 → 业务层回退显示原始 JSON。
"""
import unittest

from analysis.industry_cycle import _parse_industry_result


UNESCAPED_QUOTE_CONTENT = '''```json
{
  "industry": "先进封装",
  "overall_verdict": "主升浪中后期",
  "overall_score": 37,
  "signals": [
    {"name": "全民讨论", "status": "关注度降温", "score": 20,
     "detail": "市场不再盲目炒作"封装技术瓶颈"，关注度回归理性"}
  ],
  "summary": "综合9维雷达，处于主升浪中后期。"
}
```'''


class IndustryCycleParseTests(unittest.TestCase):
    def test_unescaped_inner_quotes_do_not_break_parse(self):
        """用户实际案例：detail 内含未转义英文双引号，仍应解析成功。"""
        r = _parse_industry_result(UNESCAPED_QUOTE_CONTENT, "先进封装")
        self.assertIsNotNone(r, '未转义内嵌引号不应导致解析失败、显示原始 JSON')
        self.assertEqual(r['overall_score'], 37)
        self.assertEqual(r['industry'], "先进封装")
        self.assertIn('封装技术瓶颈', r['signals'][0]['detail'])

    def test_clean_fenced_object(self):
        content = '```json\n{"overall_verdict": "启动期", "signals": [{"name": "x"}]}\n```'
        r = _parse_industry_result(content, "测试行业")
        self.assertEqual(r['overall_verdict'], "启动期")
        self.assertEqual(r['industry'], "测试行业")

    def test_returns_none_when_no_valid_result(self):
        self.assertIsNone(_parse_industry_result("纯文本，没有 JSON", "x"))

    def test_ai_repair_kicks_in_when_local_parse_fails(self):
        """本地完全解析不出 JSON 时，回喂 AI 修正后应成功（Tier2）。"""
        bad = "AI 走神了，只有散乱文本 {signal 不完整，没有合法 JSON"
        fixed = '{"industry":"先进封装","overall_verdict":"启动期","signals":[{"name":"渗透率","score":10}]}'

        def fake_call(messages):
            return fixed  # 模拟 AI 把坏输出修正成合法 JSON

        r = _parse_industry_result(bad, "先进封装", call_fn=fake_call)
        self.assertIsNotNone(r, '本地失败时应触发 AI 自修复')
        self.assertEqual(r['overall_verdict'], "启动期")

    def test_local_success_skips_ai_repair(self):
        """本地容错能解析时，不应触发 AI 修正调用（省一次调用）。"""
        called = []

        def fake_call(messages):
            called.append(messages)
            return '{"industry":"x","signals":[]}'

        r = _parse_industry_result(UNESCAPED_QUOTE_CONTENT, "先进封装", call_fn=fake_call)
        self.assertIsNotNone(r)
        self.assertEqual(called, [], '本地成功就不该再调 AI 修正')


if __name__ == '__main__':
    unittest.main()
