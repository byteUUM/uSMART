"""
3.7 组合腿行情批量查询 (QUO-01 ~ QUO-05)
=========================================
改动点: 组合腿行情批量取价；标的去重(多腿同标的只查一次)。

验证方式: 通过组合类查询接口(计算消耗购买力 / 订单最大可买可卖)间接观察各腿取价结果。
关注点:
  - 各腿期权价与对应标的正股价是否正确
  - 多腿共享同一标的时标的行情只查一次(需配合服务端日志/调用次数观测)
  - 某腿行情缺失时该腿委托价为 null, 不报错, 不影响其他腿
  - 行情服务失败时抛 SERVICE_BUSY_ERROR
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import (
    check_baseline,
    expect_code,
    expect_no_server_error,
    measure,
    send_query,
    show_fields,
    safe,
)
from common.config import (
    ACCOUNT_TYPE,
    COMBO_LEGS_DIFF_UNDERLYING,
    COMBO_LEGS_NO_QUOTE,
    COMBO_LEGS_SAME_UNDERLYING,
    DEFAULT_FUND_ACCOUNT,
    OPTION_MARKET,
    OPTION_MULTIPLIER,
    url_for,
)

# ============================ 业务字段 ============================
ENTRUST_PRICE = 1.5
ENTRUST_QTY = 1

# 关注字段(响应 data)
QUO_FIELDS = ["consumePurchasingPower", "purchasePower", "comboLegs", "legs"]


# ============================ 请求体构造 ============================

def _combo_body(combo_legs, **override):
    """组合计算消耗购买力 请求体(用于触发组合腿行情批量查询)。"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "O",
        "comboLegs": combo_legs,
        "comboStrategy": "VERTICAL",
        "currencyCode": "USD",
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "B",
        "entrustWay": "NET",
        "fundAccount": DEFAULT_FUND_ACCOUNT,
        "market": OPTION_MARKET,
        "multiplier": OPTION_MULTIPLIER,
        "price": ENTRUST_PRICE,
        "symbol": combo_legs[0]["symbol"],
    }
    body.update(override)
    return body


# ============================ QUO-01 ============================

def quo_01_diff_underlying():
    """QUO-01 多腿不同标的批量取价 —— 各腿期权价与对应标的正股价正确"""
    result = send_query("QUO-01 多腿不同标的", url_for("consume_power"),
                        _combo_body(COMBO_LEGS_DIFF_UNDERLYING))
    show_fields(result, QUO_FIELDS)
    check_baseline("QUO-01", result)
    print("[校验] 请核对各腿的期权价 / 标的正股价是否与行情一致")
    return result


# ============================ QUO-02 ============================

def quo_02_same_underlying():
    """
    QUO-02 多腿共享同一标的 —— 标的行情只查一次, 各腿标的价均正确
    「只查一次」需配合服务端行情调用日志确认; 这里同时对比耗时作为辅助证据。
    """
    result = send_query("QUO-02 多腿同标的", url_for("consume_power"),
                        _combo_body(COMBO_LEGS_SAME_UNDERLYING))
    show_fields(result, QUO_FIELDS)
    check_baseline("QUO-02", result)

    print("\n[辅助观测] 同标的 vs 不同标的 耗时对比(同标的应因去重而不更慢):")
    measure("同标的", lambda: send_query("QUO-02 同标的", url_for("consume_power"),
                                        _combo_body(COMBO_LEGS_SAME_UNDERLYING), quiet=True), times=5)
    measure("不同标的", lambda: send_query("QUO-02 不同标的", url_for("consume_power"),
                                         _combo_body(COMBO_LEGS_DIFF_UNDERLYING), quiet=True), times=5)
    print("[校验] 请到服务端日志确认标的行情查询次数已去重(同标的只查 1 次)")
    return result


# ============================ QUO-03 ============================

def quo_03_option_quote_missing():
    """QUO-03 期权行情缺失 —— 该腿委托价为 null, 不报错, 不影响其他腿"""
    result = send_query("QUO-03 某腿行情缺失", url_for("consume_power"),
                        _combo_body(COMBO_LEGS_NO_QUOTE))
    show_fields(result, QUO_FIELDS)
    expect_no_server_error(result)
    print("[校验] 缺行情的腿委托价应为 null, 其他腿正常(与优化前表现一致)")
    return result


# ============================ QUO-04 ============================

def quo_04_quote_service_failed():
    """
    QUO-04 行情服务失败 —— 应抛 SERVICE_BUSY_ERROR
    制造方式(选一): 让行情服务下线 / 网络隔离 / mock 返回失败码。
    """
    print("[QUO-04] 请先制造行情服务失败(下线行情服务或 mock 失败码), 再执行本用例")
    result = send_query("QUO-04 行情服务失败", url_for("consume_power"),
                        _combo_body(COMBO_LEGS_SAME_UNDERLYING))
    expect_code(result, "SERVICE_BUSY_ERROR")
    return result


# ============================ QUO-05 ============================

def quo_05_unknown_symbol_log():
    """
    QUO-05 代码冲突/未知 symbol 日志(P2, 观测类)
    行情返回集合外 symbol 时应有 warn/error 日志便于排查, 不影响主流程。
    """
    result = send_query("QUO-05 未知symbol", url_for("consume_power"),
                        _combo_body(COMBO_LEGS_NO_QUOTE))
    expect_no_server_error(result)
    print("[校验] 主流程不受影响 [PASS]")
    print("[校验] 请到服务端日志检索 warn/error, 确认有未知 symbol 的告警记录")
    return result


if __name__ == "__main__":
    safe(quo_01_diff_underlying)
    # quo_02_same_underlying()
    # quo_03_option_quote_missing()
    # quo_04_quote_service_failed()
    # quo_05_unknown_symbol_log()
