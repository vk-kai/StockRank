import unittest

from news_score_thresholds import compute_overall_score


class NewsScoreAggregationTests(unittest.TestCase):
    """总分聚合算法（条数占比法）测试。"""

    def test_real_data_today_91_positive_37_negative_scores_71(self):
        # 2026-07-21 真实分布：91 利好 / 37 利空 → 明显偏利好
        pos = [60] * 91
        neg = [30] * 37
        self.assertEqual(compute_overall_score(pos, neg), 71)

    def test_balanced_counts_score_50(self):
        self.assertEqual(compute_overall_score([60] * 50, [30] * 50), 50)

    def test_all_positive_scores_100(self):
        self.assertEqual(compute_overall_score([60] * 90, []), 100)

    def test_all_negative_scores_0(self):
        self.assertEqual(compute_overall_score([], [30] * 90), 0)

    def test_no_directional_news_scores_50(self):
        self.assertEqual(compute_overall_score([], []), 50)

    def test_negative_dominant_scores_below_50(self):
        # 30 利好 / 90 利空 → 50 + (30-90)/120*50 = 25
        self.assertEqual(compute_overall_score([60] * 30, [30] * 90), 25)

    def test_small_sample_falls_back_to_strength_average(self):
        # 仅 2 条利好（均 60），不足 5 条 → 回退强度平均，不直接给 100
        self.assertEqual(compute_overall_score([58, 62], []), 60)

    def test_threshold_boundary_5_directional_uses_ratio(self):
        # 正好 5 条（>=MIN）走条数占比法：5 利好 / 0 利空 → 100
        self.assertEqual(compute_overall_score([60] * 5, []), 100)

    def test_none_and_non_numeric_inputs_are_ignored(self):
        # route 可能传入 None 或脏数据，函数应容错
        self.assertEqual(compute_overall_score(None, None), 50)
        # [60, None, 'x', 70] 过滤后 [60,70]，2 条小样本回退 → 均值 65
        self.assertEqual(compute_overall_score([60, None, 'x', 70], []), 65)


if __name__ == "__main__":
    unittest.main()
