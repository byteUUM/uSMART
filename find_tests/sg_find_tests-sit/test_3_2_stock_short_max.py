"""
3.2 股票沽空 最大可买可卖 (SHT-01 ~ SHT-06)
============================================
接口:
  沽空最大可买可卖 : /order-center-sg/api/order/short-order-max-qty-get/v1
  沽空改单最大可改 : /order-center-sg/api/order/short-order-replace-max/v1

改动点: 购买力 + 风控数据并行；用户信息走缓存。
验证重点: 最大可买/最大可卖/购买力/融券利率/预计保证金 与基线一致；
         不可沽空标的最大可卖为 0；最大可卖受可沽空上限(maxAvailable)约束。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import (
    check_baseline,
    expect_no_server_error,
    send_query,
    show_fields,
    safe,
)
from common.config import (
    ACCOUNT_TYPE,
    NOT_SHORTABLE_STOCK,
    SHORT_ORDER_ID,
    SHORTABLE_STOCK,
    url_for,
)

# ============================ 沽空业务字段(可单独修改) ============================
ENTRUST_PRICE = 100          # 委托价格(必填)
ENTRUST_QTY = 10             # 委托数量(必填)
ENTRUST_SIDE = "S"           # 沽空为卖出
ENTRUST_WAY = "NET"          # 委托方式

# 关注字段(响应 data) —— 以下为实测 short-order-replace-max/v1 的真实字段名
SHORT_FIELDS = [
    "maxBuyQty",             # 最大可买
    "maxSellQty",            # 最大可卖
    "maxPurchasePower",      # 最大购买力
    "shortRate",             # 融券利率
    "businessQty",           # 可交易数量
    "entrustQty",            # 委托数量
    "modifiedLowerAmount",   # 改单下限
    "modifiedUpperAmount",   # 改单上限
]
# 注意: 文档场景里提到的 availableTag(可沽空标识) / maxAvailable(可沽空上限) /
#      estimateMargin(预计保证金) 在实测响应里**并不存在**。
#      SHT-02 / SHT-03 的验证点需要与开发确认改从哪个字段判断。


# ============================ 请求体构造 ============================

def _short_max_body(stock=SHORTABLE_STOCK, **override):
    """沽空最大可买可卖 请求体。"""
    body = {
        "accountType": ACCOUNT_TYPE,        # 1-普通账户, 2-高级账户(必填)
        "entrustPrice": ENTRUST_PRICE,      # 委托价格(必填)
        "entrustQty": ENTRUST_QTY,          # 委托数量(必填)
        "entrustSide": ENTRUST_SIDE,        # B-买入 S-卖出(必填)
        "entrustWay": ENTRUST_WAY,          # 委托方式
        "handQty": stock["handQty"],        # 一手数量(必填, 碎股可不传)
        "market": stock["market"],          # 市场(必填)
        "symbol": stock["symbol"],          # 股票代码(必填)
    }
    body.update(override)
    return body


def _short_replace_body(order_id, **override):
    """沽空改单最大可改 请求体。"""
    body = {
        "entrustPrice": ENTRUST_PRICE,              # 委托价格(必填)
        "entrustQty": ENTRUST_QTY,                  # 委托数量(必填)
        "handQty": SHORTABLE_STOCK["handQty"],      # 一手数量(必填)
        "orderId": order_id,                        # 订单ID(必填, int64)
    }
    body.update(override)
    return body


# ============================ SHT-01 ============================

def sht_01_normal():
    """SHT-01 正常沽空最大可买可卖 —— 传价格+手数查询, 各字段与基线一致"""
    result = send_query("SHT-01 沽空最大可买可卖", url_for("short_max"), _short_max_body())
    show_fields(result, SHORT_FIELDS)
    check_baseline("SHT-01", result)
    return result


# ============================ SHT-02 ============================

def sht_02_available_tag():
    """SHT-02 可沽空标识 —— availableTag=1 正常计算, =2 时最大可卖为 0"""
    r1 = send_query("SHT-02 可沽空标的(availableTag=1)", url_for("short_max"),
                    _short_max_body(SHORTABLE_STOCK))
    show_fields(r1, SHORT_FIELDS)

    r2 = send_query("SHT-02 不可沽空标的(availableTag=2)", url_for("short_max"),
                    _short_max_body(NOT_SHORTABLE_STOCK))
    data = show_fields(r2, SHORT_FIELDS)
    print("[校验] 不可沽空时最大可卖应为 0, 实际:", data.get("maxSellQty"))
    return r1, r2


# ============================ SHT-03 ============================

def sht_03_max_available_limit():
    """
    SHT-03 最大可卖受可沽空上限约束
    构造 maxAvailable 小于计算值(可用很低的委托价放大计算值), 最大可卖应取两者较小值。
    """
    result = send_query("SHT-03 沽空上限约束", url_for("short_max"),
                        _short_max_body(entrustPrice=0.01))
    data = show_fields(result, SHORT_FIELDS)
    print("[校验] maxSellQty 应 = min(计算值, maxAvailable), 实际:",
          data.get("maxSellQty"), "maxAvailable:", data.get("maxAvailable"))
    return result


# ============================ SHT-04 ============================

def sht_04_replace_max(order_id=SHORT_ORDER_ID):
    """SHT-04 改单最大可买可卖 —— 需先有一笔沽空在途单"""
    if not order_id:
        print("[SHT-04] 跳过: 请先在 config.SHORT_ORDER_ID 填入沽空在途订单ID")
        return None
    result = send_query("SHT-04 沽空改单最大可改", url_for("short_replace_max"),
                        _short_replace_body(order_id))
    show_fields(result, SHORT_FIELDS)
    check_baseline("SHT-04", result)
    return result


# ============================ SHT-05 ============================

def sht_05_user_info_none():
    """SHT-05 用户信息缓存为空 —— 抛业务异常, 不出现 NPE"""
    from common.config import NOT_EXIST_FUND_ACCOUNT
    result = send_query("SHT-05 用户信息为空", url_for("short_max"),
                        _short_max_body(fundAccount=NOT_EXIST_FUND_ACCOUNT))
    expect_no_server_error(result)
    return result


# ============================ SHT-06 ============================

def sht_06_parallel_consistency(times=5):
    """
    SHT-06 并行取数一致性
    连续多次查询结果应完全一致; 若购买力与风控两路都失败, 应优先暴露购买力异常。
    """
    baseline = None
    for i in range(times):
        result = send_query(f"SHT-06 第{i + 1}次查询", url_for("short_max"), _short_max_body())
        data = (result.get("json") or {}).get("data")
        if baseline is None:
            baseline = data
        elif data != baseline:
            print(f"[校验] 第{i + 1}次与首次结果不一致 [FAIL]")
            print("   首次:", baseline)
            print("   本次:", data)
            return False
    print(f"[校验] {times} 次查询结果完全一致 [PASS]")
    return True


if __name__ == "__main__":
    safe(sht_01_normal)
    # sht_02_available_tag()
    # sht_03_max_available_limit()
    # sht_04_replace_max()
    # sht_05_user_info_none()
    # sht_06_parallel_consistency()
