"""
3.3 股票 最大可买可卖 (STK-01 ~ STK-07)
========================================
接口:
  订单最大可买可卖聚合 : /order-center-sg/api/order/order-replace-max/v2  (businessType=S)
  股票改单最大可改     : /order-center-sg/api/order/stock-order-replace-max/v1
  计算消耗购买力       : /order-center-sg/api/calculate-consumed-purchasing-power/v1

改动点: 用户信息走缓存；费用二分查找 req 对象提到循环外复用；OTC/印花税取数合并只查一次。
验证重点: 最大可买数量与基线**完全一致**(二分查找复用 req 不能影响结果)；
         OTC 标记 / 印花税标记 / A股市场归一化 / 多币种 费用正确。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import safe, check_baseline, send_query, show_fields
from common.config import (
    A_STOCK,
    A_STOCK_SZ,
    ACCOUNT_TYPE,
    HK_STOCK,
    OTC_STOCK,
    STOCK_ORDER_ID,
    US_STOCK,
    url_for,
)

# ============================ 股票业务字段(可单独修改) ============================
ENTRUST_PRICE = 100         # 委托价格(必填)
ENTRUST_QTY = 10            # 委托数量(必填)
ENTRUST_WAY = "NET"

# 关注字段(响应 data) —— 以下为实测 stock-order-replace-max/v1 的真实字段名
MAX_FIELDS = [
    "maxBuyQty",             # 最大可买
    "maxSellQty",            # 最大可卖
    "maxPurchasePower",      # 最大购买力
    "maxCashBuyQty",         # 现金最大可买
    "maxCashBuyMulti",       # 现金最大可买(乘数)
    "cashBalance",           # 现金余额
    "businessQty",           # 可交易数量
    "entrustQty",            # 委托数量
    "modifiedLowerAmount",   # 改单下限
    "modifiedUpperAmount",   # 改单上限
]
# 注意: 费用相关字段 fee / otc / stampDuty 在实测响应里**并不存在**。
#      STK-03(OTC费用) / STK-04(印花税) 的验证点需与开发确认:
#      费用是否只体现在 maxBuyQty 的计算结果里(即通过数量差异反推)?


# ============================ 请求体构造 ============================

def _max_body(stock=US_STOCK, entrust_side="B", **override):
    """订单最大可买可卖 请求体(股票 businessType=S)。"""
    body = {
        "businessType": "S",                # S-股票(普通订单必传)
        "entrustPrice": ENTRUST_PRICE,      # 委托价格(必填)
        "entrustQty": ENTRUST_QTY,          # 委托数量(必填)
        "entrustSide": entrust_side,        # B-买入 S-卖出
        "handQty": stock["handQty"],        # 一手数量(股票必传)
        "market": stock["market"],
        "symbol": stock["symbol"],
    }
    body.update(override)
    return body


def _power_body(stock=US_STOCK, **override):
    """计算消耗购买力 请求体(股票)。"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "S",
        "currencyCode": stock["currency"],
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "B",
        "entrustWay": ENTRUST_WAY,
        "handQty": stock["handQty"],
        "market": stock["market"],
        "symbol": stock["symbol"],
    }
    body.update(override)
    return body


# ============================ STK-01 ============================

def stk_01_max_buy():
    """
    STK-01 最大可买(含费用二分查找)
    重点: 费用请求对象已提到二分循环外复用, 最大可买数量必须与基线完全一致。
    """
    result = send_query("STK-01 股票最大可买", url_for("order_max"), _max_body(US_STOCK, "B"))
    show_fields(result, MAX_FIELDS)
    check_baseline("STK-01", result)
    return result


# ============================ STK-02 ============================

def stk_02_max_sell():
    """STK-02 最大可卖"""
    result = send_query("STK-02 股票最大可卖", url_for("order_max"), _max_body(US_STOCK, "S"))
    show_fields(result, MAX_FIELDS)
    check_baseline("STK-02", result)
    return result


# ============================ STK-03 ============================

def stk_03_otc_fee():
    """STK-03 OTC 标的费用 —— OTC 标记为 true, 费用含 OTC 差异"""
    result = send_query("STK-03 OTC标的最大可买", url_for("order_max"), _max_body(OTC_STOCK, "B"))
    show_fields(result, MAX_FIELDS)
    check_baseline("STK-03", result)

    # 同步核对购买力接口的费用
    power = send_query("STK-03 OTC标的消耗购买力", url_for("consume_power"), _power_body(OTC_STOCK))
    check_baseline("STK-03-power", power)
    return result, power


# ============================ STK-04 ============================

def stk_04_stamp_duty_fee():
    """STK-04 印花税标的费用 —— 港股印花税标记正确, 费用含印花税"""
    result = send_query("STK-04 港股最大可买", url_for("order_max"), _max_body(HK_STOCK, "B"))
    show_fields(result, MAX_FIELDS)
    check_baseline("STK-04", result)

    power = send_query("STK-04 港股消耗购买力", url_for("consume_power"), _power_body(HK_STOCK))
    check_baseline("STK-04-power", power)
    return result, power


# ============================ STK-05 ============================

def stk_05_a_share_market():
    """STK-05 A股市场归一化 —— 沪港通/深港通子市场归一化后费用正确"""
    for stock in [A_STOCK, A_STOCK_SZ]:
        result = send_query(f"STK-05 A股({stock['market']})最大可买",
                            url_for("order_max"), _max_body(stock, "B"))
        show_fields(result, MAX_FIELDS)
        check_baseline(f"STK-05-{stock['market']}", result)


# ============================ STK-06 ============================

def stk_06_multi_currency():
    """STK-06 多币种 —— 多市场多币种标的, 币种校验与费用正确"""
    for stock in [US_STOCK, HK_STOCK, A_STOCK]:
        result = send_query(f"STK-06 {stock['currency']} 消耗购买力",
                            url_for("consume_power"), _power_body(stock))
        show_fields(result, MAX_FIELDS)
        check_baseline(f"STK-06-{stock['currency']}", result)


# ============================ STK-07 ============================

def stk_07_fee_binary_search_consistency(times=5):
    """
    STK-07 费用二分查找一致性
    同标的多次查询, 最大可买数量必须每次都相同(req 复用不能带来累积污染)。
    """
    values = []
    for i in range(times):
        result = send_query(f"STK-07 第{i + 1}次最大可买", url_for("order_max"),
                            _max_body(US_STOCK, "B"), quiet=True)
        data = (result.get("json") or {}).get("data") or {}
        values.append(data.get("maxBuyQty"))
        print(f"  第{i + 1}次 maxBuyQty =", data.get("maxBuyQty"))

    if len(set(map(str, values))) == 1:
        print(f"[校验] {times} 次最大可买数量一致: {values[0]} [PASS]")
        return True
    print(f"[校验] 最大可买数量出现波动 [FAIL] {values}")
    return False


# ============================ 股票改单最大可改 ============================

def stk_replace_max(order_id=STOCK_ORDER_ID):
    """股票改单最大可改(配合 STK-01/02 一起回归)"""
    if not order_id:
        print("[STK-改单] 跳过: 请先在 config.STOCK_ORDER_ID 填入股票在途订单ID")
        return None
    body = {
        "entrustPrice": ENTRUST_PRICE,          # 委托价格(必填)
        "handQty": US_STOCK["handQty"],         # 一手数量(必填)
        "orderId": order_id,                    # 订单ID(必填)
    }
    result = send_query("STK 股票改单最大可改", url_for("stock_replace_max"), body)
    show_fields(result, MAX_FIELDS)
    check_baseline("STK-replace", result)
    return result


if __name__ == "__main__":
    # safe(stk_01_max_buy)
    # stk_02_max_sell()
    # stk_03_otc_fee()
    # stk_04_stamp_duty_fee()
    # stk_05_a_share_market()
    # stk_06_multi_currency()
    # stk_07_fee_binary_search_consistency()
    stk_replace_max()
