"""parse_ai_response JSON 提取鲁棒性回归。

2026-07-22：原实现用 find('[')/rfind(']') 切 JSON，当 AI 返回的散文里带 [] 时
（如"本批[共2条]"、"PE[历史90%分位]"）会切到错误区间 → 整批解析失败、静默返回 None。
改为括号匹配（字符串感知）定位真正的 JSON 数组/对象。
"""
import unittest

from analysis.ai_analyzer import parse_ai_response


class ParseAiResponseTests(unittest.TestCase):
    def test_clean_fenced_array(self):
        content = '```json\n[{"id":"1","score":80},{"id":"2","score":30}]\n```'
        r = parse_ai_response(content)
        self.assertEqual(set(r.keys()), {'1', '2'})
        self.assertEqual(r['1']['score'], 80)

    def test_prose_brackets_outside_array_do_not_break_parse(self):
        """AI 散文含 []（且无代码围栏）时仍能正确提取 JSON 数组——用户实际遇到的失败场景。"""
        content = (
            '分析完成。说明：本批[共2条]结果如下：\n'
            '[\n'
            '  {"id":"1","reason":"PE[历史90%分位]","score":80},\n'
            '  {"id":"2","reason":"正常","score":30}\n'
            ']\n'
            '以上。'
        )
        r = parse_ai_response(content)
        self.assertIsNotNone(r, '带 [] 的散文不应导致解析失败')
        self.assertEqual(set(r.keys()), {'1', '2'})
        self.assertEqual(r['1']['reason'], 'PE[历史90%分位]')

    def test_single_object_wrapped_to_list(self):
        content = '{"id":"1","score":80}'
        self.assertEqual(parse_ai_response(content), {'1': {'id': '1', 'score': 80}})

    def test_returns_none_when_no_json(self):
        self.assertIsNone(parse_ai_response('纯文本，没有 JSON'))


if __name__ == '__main__':
    unittest.main()
