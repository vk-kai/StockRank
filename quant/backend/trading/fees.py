"""A股交易费用模型(回测与模拟账户共用,确保口径一致)。

费率:
- 佣金:双边,率由调用方传入(默认万分之一 0.0001),最低 5 元
- 印花税:仅卖出,0.05%(2023-08-28 起现行,原 0.1%)
- 过户费:双边,0.001%(沪深 2022 年起统一)
"""

COMMISSION_RATE_DEFAULT = 0.0001
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
MIN_COMMISSION = 5.0


def calc_a_share_fee(
    amount: float, is_sell: bool = False, commission_rate: float = COMMISSION_RATE_DEFAULT
) -> dict:
    """单笔交易费用明细。amount = 成交金额(正数)。"""
    commission = max(amount * commission_rate, MIN_COMMISSION)
    stamp_tax = amount * STAMP_TAX_RATE if is_sell else 0.0
    transfer_fee = amount * TRANSFER_FEE_RATE
    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "total": round(commission + stamp_tax + transfer_fee, 2),
    }


def calc_a_share_fee_total(
    amount: float, is_sell: bool = False, commission_rate: float = COMMISSION_RATE_DEFAULT
) -> float:
    """单笔交易总费用。"""
    return calc_a_share_fee(amount, is_sell, commission_rate)["total"]
