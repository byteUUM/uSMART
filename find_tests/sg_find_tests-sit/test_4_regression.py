"""
4. 回归重点 (REG-01 ~ REG-05) —— 确保未破坏既有能力
====================================================
核心: 查询类接口放开了冻结账户拦截, 但**真实下单/改单/撤单仍必须拦截**。

真实交易接口(统一下单, 与 order_api_tests 一致):
  下单: /order-center-sg/admin-api/unified-order-create/v1
  改单: /order-center-sg/admin-api/unified-order-replace/v1
  撤单: /order-center-sg/admin-api/unified-order-cancel/v1

注意: 本文件会**真实下单**, 只在 SIT/UAT 执行, 且用小数量。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import (
    build_headers,
    check_baseline,
    expect_code,
    expect_error,
    send_query,
    safe,
)
from common.config import (
    ACCOUNT_TYPE,
    BASE_URL,
    DEFAULT_FUND_ACCOUNT,
    FROZEN_ACCOUNT,
    HK_STOCK,
    OPTION_SYMBOL,
    OTC_STOCK,
    TOKENS,
    US_STOCK,
    url_for,
)

# ============================ 真实交易接口路径 ============================
UNIFIED_CREATE = BASE_URL + "/order-center-sg/admin-api/unified-order-create/v1"
UNIFIED_REPLACE = BASE_URL + "/order-center-sg/admin-api/unified-order-replace/v1"
UNIFIED_CANCEL = BASE_URL + "/order-center-sg/admin-api/unified-order-cancel/v1"

# ============================ 交易字段 ============================
ENTRUST_PRICE = "1"          # 用极低价挂单, 避免真实成交
ENTRUST_QTY = 1
TRADE_CHANNEL = "IB-30%-U90117214"
OPTION_TRADE_CHANNEL = "VELOX-30%-2UT00110"


def _create_body(fund_account, stock=US_STOCK, business_type="S", entrust_side="B"):
    """统一下单 请求体。"""
    return {
        "accountType": ACCOUNT_TYPE,
        "businessType": business_type,
        "currency": stock["currency"],
        "entrustPrice": ENTRUST_PRICE,
        "entrustProp": "LMT",
        "entrustQty": ENTRUST_QTY,
        "entrustSide": entrust_side,
        "entrustWay": "NET",
        "forceEntrustFlag": True,
        "fundAccount": fund_account,
        "market": stock["market"],
        "notice": True,
        "symbol": stock["symbol"],
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": "N",
    }


# ============================ REG-01 ============================

def reg_01_frozen_account_real_trade():
    """
    REG-01 冻结/异常账户真实下单/改单/撤单
    预期: 仍被拦截并抛 BASE_COMMON_FUNDACCOUNT_ERROR
         (真实交易链路仍做实时账户状态校验, 未受缓存改造影响)
    """
    headers = build_headers(token=TOKENS.get(FROZEN_ACCOUNT) or None)

    print("\n### 1) 冻结账户查询购买力 —— 优化后允许返回数字")
    from test_3_1_combo_option_power import cbo_08_frozen_account
    cbo_08_frozen_account()

    print("\n### 2) 冻结账户真实下单 —— 必须被拦截")
    create = send_query("REG-01 冻结账户下单", UNIFIED_CREATE,
                        _create_body(FROZEN_ACCOUNT), headers=headers)
    ok = expect_code(create, "BASE_COMMON_FUNDACCOUNT_ERROR")
    if not ok:
        print("[风险] 冻结账户下单未被拦截, 属严重缺陷, 需立即提单 [FAIL]")

    print("\n### 3) 冻结账户改单 —— 必须被拦截")
    send_query("REG-01 冻结账户改单", UNIFIED_REPLACE, {
        "accountType": ACCOUNT_TYPE,
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "forceEntrustFlag": True,
        "orderId": 1,
    }, headers=headers)

    print("\n### 4) 冻结账户撤单 —— 必须被拦截")
    send_query("REG-01 冻结账户撤单", UNIFIED_CANCEL, {
        "accountType": ACCOUNT_TYPE,
        "isForceCancel": True,
        "orderId": 1,
    }, headers=headers)
    return create


# ============================ REG-02 ============================

def reg_02_fee_item_other_callers():
    """
    REG-02 费用项获取其他调用方
    费用计算(getFeeItem)在其他业务入口结果不变 —— 覆盖 OTC / 印花税 / 普通标的。
    """
    from test_3_3_stock_max import _max_body, _power_body

    for tag, stock in [("普通美股", US_STOCK), ("港股印花税", HK_STOCK), ("美股OTC", OTC_STOCK)]:
        r1 = send_query(f"REG-02 {tag} 最大可买", url_for("order_max"), _max_body(stock, "B"))
        check_baseline(f"REG-02-{tag}-max", r1)
        r2 = send_query(f"REG-02 {tag} 消耗购买力", url_for("consume_power"), _power_body(stock))
        check_baseline(f"REG-02-{tag}-power", r2)


# ============================ REG-03 ============================

def reg_03_option_short_full_flow():
    """
    REG-03 期权沽空真实下单全流程
    预期: 下单、报盘、冻结资金等流程正常。
    """
    print("\n### 1) 先查最大可卖")
    from test_3_4_option_short_max import ops_02_with_fund_account
    ops_02_with_fund_account()

    print("\n### 2) 期权沽空真实下单")
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "OS",               # OS-期权沽空
        "currency": "USD",
        "entrustPrice": ENTRUST_PRICE,
        "entrustProp": "LMT",
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "S",
        "entrustWay": "NET",
        "forceEntrustFlag": True,
        "fundAccount": DEFAULT_FUND_ACCOUNT,
        "market": "US",
        "notice": True,
        "symbol": OPTION_SYMBOL,
        "tradeChannel": OPTION_TRADE_CHANNEL,
        "tradePeriod": "N",
    }
    create = send_query("REG-03 期权沽空下单", UNIFIED_CREATE, body)
    order_id = ((create.get("json") or {}).get("data") or {}).get("orderId")
    print("[提示] 下单返回 orderId:", order_id, " 请核对报盘状态与冻结资金")

    if order_id:
        print("\n### 3) 撤单收尾")
        send_query("REG-03 期权沽空撤单", UNIFIED_CANCEL, {
            "accountType": ACCOUNT_TYPE,
            "isForceCancel": True,
            "orderId": order_id,
        })
    return create


# ============================ REG-04 ============================

def reg_04_combo_option_full_flow():
    """
    REG-04 组合期权真实下单/改单/撤单
    预期: 流程正常, 账户状态/权限校验正常。
    """
    from common.config import COMBO_STRATEGIES
    strategy = COMBO_STRATEGIES["牛市价差"]

    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "O",
        "comboLegs": strategy["comboLegs"],
        "currency": "USD",
        "entrustPrice": 1.5,
        "entrustProp": "LMT",
        "entrustQty": 1,
        "entrustSide": "B",
        "entrustWay": "NET",
        "forceEntrustFlag": True,
        "fundAccount": DEFAULT_FUND_ACCOUNT,
        "market": "US",
        "notice": True,
        "tradeChannel": OPTION_TRADE_CHANNEL,
        "tradePeriod": "N",
    }
    create = send_query("REG-04 组合期权下单", UNIFIED_CREATE, body)
    order_id = ((create.get("json") or {}).get("data") or {}).get("orderId")
    print("[提示] 组合下单 orderId:", order_id)

    if order_id:
        print("\n### 改单最大可开仓(顺带回归 CBO-04)")
        from test_3_1_combo_option_power import cbo_04_replace_max
        cbo_04_replace_max(order_id)

        send_query("REG-04 组合改单", UNIFIED_REPLACE, {
            "accountType": ACCOUNT_TYPE,
            "entrustPrice": 1.8,
            "entrustQty": 1,
            "forceEntrustFlag": True,
            "orderId": order_id,
        })
        send_query("REG-04 组合撤单", UNIFIED_CANCEL, {
            "accountType": ACCOUNT_TYPE,
            "isForceCancel": True,
            "orderId": order_id,
        })
    return create


# ============================ REG-05 ============================

def reg_05_multi_language():
    """
    REG-05 多语言/文案
    各语言(1-简体 2-繁体 3-英文)错误提示正确,
    新增文案「无对应交易权限」(NO_CORRESPONDING_TRADE_PERMISSION)显示正确。
    """
    from common.config import NO_OPTION_SHORT_ACCOUNT
    from test_3_4_option_short_max import _sell_max_body

    account = NO_OPTION_SHORT_ACCOUNT or DEFAULT_FUND_ACCOUNT
    if not NO_OPTION_SHORT_ACCOUNT:
        print("[提示] config.NO_OPTION_SHORT_ACCOUNT 未配置, 无法稳定触发无权限错误")

    expects = {"1": "无对应交易权限", "2": "無對應交易權限", "3": "permission"}
    for lang, keyword in expects.items():
        headers = build_headers(lang=lang)
        result = send_query(f"REG-05 无权限文案(X-Lang={lang})", url_for("option_short_max"),
                            _sell_max_body(account), headers=headers)
        expect_error(result, keyword)
    print("[校验] 三种语言文案均应正确返回")


if __name__ == "__main__":
    # 注意: 本文件会真实下单, 确认在 SIT 环境再执行
    safe(reg_02_fee_item_other_callers)
    # reg_01_frozen_account_real_trade()
    # reg_03_option_short_full_flow()
    # reg_04_combo_option_full_flow()
    # reg_05_multi_language()
