POSITIVE_SCORE_THRESHOLD = 55
NEGATIVE_SCORE_THRESHOLD = 45


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
