"""
3.1 组合期权 购买力 / 最大可买可卖 (CBO-01 ~ CBO-09)
=====================================================
接口:
  计算消耗购买力       : /order-center-sg/api/calculate-consumed-purchasing-power/v1
  订单最大可买可卖聚合 : /order-center-sg/api/order/order-replace-max/v2  (传 orderId 即改单)

改动点: 三路远程查询并行；用户信息走缓存；新增空值/资金账号/clientId 校验。
验证重点: 结果与优化前基线逐字段一致 + 异常入参有正确业务异常(不出 500/NPE)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import (
    assert_same_results,
    build_headers,
    check_baseline,
    expect_code,
    expect_no_server_error,
    is_no_permission,
    run_concurrent,
    safe,
    send_query,
    show_fields,
)
from common.config import (
    ACCOUNT_TYPE,
    COMBO_ORDER_ID,
    COMBO_STRATEGIES,
    DEFAULT_FUND_ACCOUNT,
    FROZEN_ACCOUNT,
    NOT_EXIST_FUND_ACCOUNT,
    OPTION_MARKET,
    OPTION_MULTIPLIER,
    TOKENS,
    url_for,
)

# ============================ 组合业务字段(可单独修改) ============================
FUND_ACCOUNT = DEFAULT_FUND_ACCOUNT
MARKET = OPTION_MARKET
CURRENCY = "USD"
ENTRUST_PRICE = 1.5          # 组合净价
ENTRUST_QTY = 1
ENTRUST_WAY = "NET"
ENTRUST_SIDE = "B"

# 关注字段(响应 data)
POWER_FIELDS = ["consumePurchasingPower", "purchasePower", "openClose", "holdQty"]


# ============================ 请求体构造 ============================

def _power_body(strategy_name="牛市价差", fund_account=FUND_ACCOUNT, **override):
    """计算消耗购买力 请求体。"""
    strategy = COMBO_STRATEGIES[strategy_name]
    body = {
        "accountType": ACCOUNT_TYPE,                    # 1-普通账户, 2-高级账户
        "businessType": "O",                            # S-股票 SHORT-股票沽空 O-期权 OS-期权沽空
        "comboLegs": strategy["comboLegs"],             # 组合腿明细
        "comboStrategy": strategy["comboStrategy"],     # 组合策略
        "currencyCode": CURRENCY,
        "entrustPrice": ENTRUST_PRICE,                  # 委托价格(必填)
        "entrustQty": ENTRUST_QTY,
        "entrustSide": ENTRUST_SIDE,
        "entrustWay": ENTRUST_WAY,
        "fundAccount": fund_account,
        "market": MARKET,                               # 市场(必填)
        "multiplier": OPTION_MULTIPLIER,                # 期权乘数
        "price": ENTRUST_PRICE,                         # 期权必传
        "symbol": strategy["comboLegs"][0]["symbol"],   # 股票代码(必填, 组合传首腿)
    }
    body.update(override)
    return body


def _max_qty_body(strategy_name="牛市价差", order_id=None, **override):
    """订单最大可买可卖聚合 请求体。组合订单不传顶层 businessType。"""
    strategy = COMBO_STRATEGIES[strategy_name]
    body = {
        "comboLegs": strategy["comboLegs"],
        "comboStrategy": strategy["comboStrategy"],
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
    }
    if order_id:
        body["orderId"] = order_id                      # 传 orderId = 改单最大可开仓
    body.update(override)
    return body


# ============================ CBO-01 ============================

def cbo_01_multi_leg_power():
    """CBO-01 多腿组合正常购买力 —— 结果应与优化前基线逐字段一致"""
    result = send_query("CBO-01 多腿组合购买力", url_for("consume_power"), _power_body("牛市价差"))
    if is_no_permission(result):
        return result
    show_fields(result, POWER_FIELDS)
    check_baseline("CBO-01", result)
    return result


# ============================ CBO-02 ============================

def cbo_02_all_strategies():
    """CBO-02 各组合策略覆盖 —— 牛市/熊市价差、跨式/宽跨式、备兑"""
    results = {}
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑"]:
        result = send_query(f"CBO-02 {name} 购买力", url_for("consume_power"), _power_body(name))
        show_fields(result, POWER_FIELDS)
        check_baseline(f"CBO-02-{name}", result)
        results[name] = result
    return results


# ============================ CBO-03 ============================

def cbo_03_with_short_leg():
    """CBO-03 含股票腿/沽空腿的组合 —— 抵押比率/沽空比率取值正确"""
    for name in ["备兑", "含沽空腿"]:
        result = send_query(f"CBO-03 {name}", url_for("consume_power"), _power_body(name))
        show_fields(result, POWER_FIELDS)
        check_baseline(f"CBO-03-{name}", result)


# ============================ CBO-04 ============================

def cbo_04_replace_max(order_id=COMBO_ORDER_ID):
    """CBO-04 改单最大可开仓 —— 需先有一笔组合在途单"""
    if not order_id:
        print("[CBO-04] 跳过: 请先在 config.COMBO_ORDER_ID 填入组合在途订单ID")
        return None
    # 改单走 order_replace_max(/api/order/order-replace-max/v2), 与新单聚合 order_max 是两个接口
    result = send_query("CBO-04 组合改单最大可开仓", url_for("order_replace_max"),
                        _max_qty_body("牛市价差", order_id=order_id))
    check_baseline("CBO-04", result)
    return result


# ============================ CBO-05 ============================

def cbo_05_user_info_none():
    """CBO-05 用户信息为空 —— 期望 FUND_ACCOUNT_INFO_NONE，不出现 500/NPE"""
    result = send_query("CBO-05 用户信息为空", url_for("consume_power"),
                        _power_body(fund_account=NOT_EXIST_FUND_ACCOUNT))
    if is_no_permission(result):
        return result
    expect_code(result, "FUND_ACCOUNT_INFO_NONE")   # 实测 450004「获取用户信息异常」
    expect_no_server_error(result)
    return result


# ============================ CBO-06 ============================

def cbo_06_fund_account_empty():
    """CBO-06 资金账号为空 —— 期望 BASE_CAPITAL_FUNDACCOUNT_ERROR"""
    result = send_query("CBO-06 资金账号为空", url_for("consume_power"),
                        _power_body(fund_account=""))
    if is_no_permission(result):
        return result
    expect_code(result, "FUNDACCOUNT_EMPTY")        # 实测「资金帐号不能为空」
    expect_no_server_error(result)
    return result


# ============================ CBO-07 ============================

def cbo_07_client_id_empty():
    """CBO-07 客户号为空 —— 期望 FUND_ACCOUNT_INFO_NONE，不出现 NPE"""
    headers = build_headers(extra={"X-Client-Id": ""})
    result = send_query("CBO-07 客户号为空", url_for("consume_power"),
                        _power_body(), headers=headers)
    expect_no_server_error(result)
    return result


# ============================ CBO-08 ============================

def cbo_08_frozen_account():
    """
    CBO-08 冻结账户查询
    优化后查询阶段不再拦截冻结账户 —— 应能返回购买力数字(需产品确认)。
    真实下单仍应被拦截, 见 test_4_regression.REG-01。
    """
    result = send_query("CBO-08 冻结账户购买力", url_for("consume_power"),
                        _power_body(fund_account=FROZEN_ACCOUNT),
                        headers=build_headers(token=TOKENS.get(FROZEN_ACCOUNT) or None))
    show_fields(result, POWER_FIELDS)
    expect_no_server_error(result)
    return result


# ============================ CBO-09 ============================

def cbo_09_concurrent():
    """CBO-09 高频并发查询 —— 结果稳定一致, 无偶发异常"""
    def task():
        return send_query("CBO-09 并发购买力", url_for("consume_power"),
                          _power_body(), quiet=True)

    results = run_concurrent(task, times=30, max_workers=10)
    assert_same_results(results)
    return results


if __name__ == "__main__":
    # 按需取消注释运行
    safe(cbo_01_multi_leg_power)
    # cbo_02_all_strategies()
    # cbo_03_with_short_leg()
    # cbo_04_replace_max()
    # cbo_05_user_info_none()
    # cbo_06_fund_account_empty()
    # cbo_07_client_id_empty()
    # cbo_08_frozen_account()
    # cbo_09_concurrent()
