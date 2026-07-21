POSITIVE_SCORE_THRESHOLD = 55
NEGATIVE_SCORE_THRESHOLD = 45

# 方向性新闻（利好+利空）达到该条数才用条数占比法算总分；
# 不足时回退到强度平均法，避免小样本（如开盘初 1-2 条）偶然打出极端分。
MIN_DIRECTIONAL_SAMPLES = 5


def _to_number(score):
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def classify_score(score):
    value = _to_number(score)
    if value is None:
        return None
    if value >= POSITIVE_SCORE_THRESHOLD:
        return "positive"
    if value <= NEGATIVE_SCORE_THRESHOLD:
        return "negative"
    return "neutral"


def get_score_label(score):
    direction = classify_score(score)
    if direction == "positive":
        return "利好"
    if direction == "negative":
        return "利空"
    if direction == "neutral":
        return "中性"
    return "未分析"


def is_directional_score(score):
    return classify_score(score) in ("positive", "negative")


def _clean_score_list(scores):
    """过滤掉 None/非数字/NaN，返回合法的 float 列表。"""
    if not scores:
        return []
    return [float(s) for s in scores if isinstance(s, (int, float)) and s == s]


def compute_overall_score(pos_scores, neg_scores):
    """根据今日利好/利空新闻的分数列表，计算综合情绪总分（0-100，50 为中性）。

    方向性新闻（利好+利空）达到 MIN_DIRECTIONAL_SAMPLES 时用【条数净占比法】：
        overall = 50 + (利好数 - 利空数) / (利好数 + 利空数) × 50
    让多空数量对比直接、明显地反映到总分（如 91 利好 / 37 利空 → 71）。

    不足 MIN_DIRECTIONAL_SAMPLES 时回退到【强度平均法】（原逻辑）：
    对方向性分数求平均，避免小样本偶然极端化（2 条全利好不至于直接得 100）。

    无方向性新闻时返回 50（中性）。
    """
    pos = _clean_score_list(pos_scores)
    neg = _clean_score_list(neg_scores)
    total_positive = len(pos)
    total_negative = len(neg)
    directional = total_positive + total_negative

    if directional == 0:
        return 50
    if directional >= MIN_DIRECTIONAL_SAMPLES:
        return round(50 + (total_positive - total_negative) / directional * 50)

    all_scores = pos + neg
    return round(sum(all_scores) / len(all_scores))
