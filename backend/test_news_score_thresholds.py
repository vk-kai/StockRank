import unittest

from news_score_thresholds import classify_score, get_score_label, is_directional_score


class NewsScoreThresholdTests(unittest.TestCase):
    def test_classifies_five_point_band_around_50_as_neutral(self):
        neutral_scores = [46, 49, 50, 51, 54]
        for score in neutral_scores:
            with self.subTest(score=score):
                self.assertEqual(classify_score(score), "neutral")
                self.assertEqual(get_score_label(score), "中性")
                self.assertFalse(is_directional_score(score))

    def test_classifies_scores_at_or_beyond_thresholds_as_directional(self):
        cases = [
            (55, "positive", "利好"),
            (100, "positive", "利好"),
            (45, "negative", "利空"),
            (0, "negative", "利空"),
        ]

        for score, direction, label in cases:
            with self.subTest(score=score):
                self.assertEqual(classify_score(score), direction)
                self.assertEqual(get_score_label(score), label)
                self.assertTrue(is_directional_score(score))


if __name__ == "__main__":
    unittest.main()
