"""
接口2: 获取订单最大可买可卖及购买力聚合(新单)
============================================
POST /order-center-sg/api/order/stock-order-max-qty-get/v2

入参 schema: PurchasePowerReqVO
  必填          businessType / entrustPrice / market / symbol
  组合腿必填    entrustSide / legRatio / symbol
  条件必传      comboLegs + comboStrategy(组合多腿) / price(期权)
  businessType  S-股票  SHORT-股票沽空  O-期权  OS-期权沽空

约束:
  请求头 X-Type 需为 12, 其他取值返回 107005。
  响应字段随 businessType 变化, 见 FIELDS_* 四组。
  账号由 token 决定, 请求体中的 fundAccount 不用于切换账号。

覆盖 explain.md:
  3.3 股票最大可买可卖      STK-01 ~ STK-07   businessType=S
  3.2 股票沽空最大可买可卖  SHT-01 ~ SHT-03   businessType=SHORT
  3.4 期权沽空最大可卖      OPS               businessType=OS
  3.1 组合最大可买可卖      CBO-02            comboLegs
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import (
    assert_same_results,
    build_headers,
    check_baseline,
    expect_no_server_error,
    measure,
    run_concurrent,
    safe,
    send_query,
)
from common.config import (
    A_STOCK,
    ACCOUNT_TYPE,
    COMBO_STRATEGIES,
    HK_STOCK,
    NOT_SHORTABLE_STOCK,
    OPTION_MULTIPLIER,
    OPTION_SYMBOL,
    OTC_STOCK,
    SHORTABLE_STOCK,
    US_STOCK,
    url_for,
)

URL = url_for("order_max")

# 响应字段按 businessType 分四组
FIELDS_STOCK = ["maxBuyQty", "maxSellQty", "maxPurchasePower",
                "maxCashBuyQty", "maxCashBuyMulti", "cashBalance"]
FIELDS_SHORT = ["maxBuyQty", "maxSellQty", "maxPurchasePower", "shortRate", "expectMargin"]
FIELDS_OPTION = ["buyMax", "sellMax", "maxPurchasePower", "expectMargin"]
FIELDS_COMBO = ["consumePurchasingPower", "holdQty", "openClose", "purchasePower"]

# 金额类字段随账户资金变动, 基线比对时忽略
DRIFT = ("msg", "error", "cashBalance", "maxPurchasePower")


# ============================ 入参构造 ============================

def body(business_type="S", stock=US_STOCK, side="B", **override):
    data = {
        "accountType": ACCOUNT_TYPE,
        "businessType": business_type,
        "currencyCode": stock["currency"],
        "entrustPrice": 100,
        "entrustSide": side,
        "entrustWay": "NET",
        "handQty": stock["handQty"],
        "market": stock["market"],
        "symbol": stock["symbol"],
    }
    data.update(override)
    return data


def body_option(business_type="O", **override):
    """
    期权 O / 期权沽空 OS, price 必传。
    组合请求需同时携带 entrustQty 与 entrustSide。
    """
    data = {
        "accountType": ACCOUNT_TYPE,
        "businessType": business_type,
        "currencyCode": "USD",
        "entrustPrice": 1.5,
        "entrustQty": 1,
        "entrustSide": "B" if business_type == "O" else "S",
        "entrustWay": "NET",
        "market": "US",
        "multiplier": OPTION_MULTIPLIER,
        "price": 1.5,
        "symbol": OPTION_SYMBOL,
    }
    data.update(override)
    return data


def body_combo(strategy="牛市价差", **override):
    conf = COMBO_STRATEGIES[strategy]
    data = body_option("O", comboLegs=conf["comboLegs"],
                       comboStrategy=conf["comboStrategy"],
                       symbol=conf["comboLegs"][0]["symbol"])
    data.update(override)
    return data


# ============================ 工具 ============================

ENV_CODES = {
    107005: "X-Type 取值不符或 token 无效",
    110002: "登录状态已失效",
    110003: "当前账号无该接口调用权限",
    100012: "下游服务不可用",
    400064: "期权代码不存在, 可能已到期",
    450004: "该码被复用, 需结合 error 字段定位",
    800025: "行情最新价获取失败",
}


def data_of(result):
    return (result.get("json") or {}).get("data") or {}


def code_of(result):
    return (result.get("json") or {}).get("code")


def check(condition, message):
    print("    校验 %s: %s" % (message, "PASS" if condition else "FAIL"))
    return bool(condition)


def env_blocked(result):
    payload = result.get("json") or {}
    code = payload.get("code")
    if code in ENV_CODES:
        print("    环境阻塞 code=%s %s (%s)%s" % (
            code, payload.get("msg"), ENV_CODES[code],
            " error=%s" % payload["error"] if payload.get("error") else ""))
        return True
    return False


def run_case(name, payload, fields, case=None):
    result = send_query(name, URL, payload)
    if env_blocked(result):
        return result
    data = data_of(result)
    print("    字段 %s" % {k: data.get(k) for k in fields})
    check(code_of(result) == 0, "返回 code=0")
    missing = [f for f in fields if f not in data]
    check(not missing, "响应字段齐全" + ("" if not missing else "(缺失 %s)" % missing))
    if case:
        check_baseline(case, result, ignore_keys=DRIFT)
    return result


# ============================ STK 股票 ============================

def stk_01_max_buy():
    """STK-01 股票最大可买(含费用二分查找)"""
    result = run_case("STK-01 股票最大可买", body("S", US_STOCK, "B"), FIELDS_STOCK, "STK-01")
    data = data_of(result)
    if data:
        check((data.get("maxBuyQty") or 0) > 0, "最大可买大于 0")
        check((data.get("maxCashBuyQty") or 0) <= (data.get("maxBuyQty") or 0),
              "现金可买不大于融资可买")
    return result


def stk_02_max_sell():
    """STK-02 股票最大可卖"""
    return run_case("STK-02 股票最大可卖", body("S", US_STOCK, "S"), FIELDS_STOCK, "STK-02")


def stk_03_otc_fee():
    """STK-03 美股 OTC 标的费用"""
    return run_case("STK-03 美股OTC", body("S", OTC_STOCK, "B"), FIELDS_STOCK, "STK-03")


def stk_04_stamp_duty():
    """STK-04 港股印花税标的费用"""
    return run_case("STK-04 港股", body("S", HK_STOCK, "B"), FIELDS_STOCK, "STK-04")


def stk_05_multi_market():
    """STK-05/06 多市场多币种: A 股市场归一化与币种校验"""
    for stock in [US_STOCK, HK_STOCK, A_STOCK]:
        run_case("STK-05/06 %s/%s" % (stock["market"], stock["currency"]),
                 body("S", stock, "B"), FIELDS_STOCK, "STK-05-%s" % stock["market"])


def stk_07_fee_consistency(times=5):
    """STK-07 费用二分查找一致性: 多次调用最终数量应完全一致"""
    values = []
    for idx in range(times):
        result = send_query("STK-07 第%d次" % (idx + 1), URL, body("S", US_STOCK, "B"), quiet=True)
        if env_blocked(result):
            return
        data = data_of(result)
        values.append((data.get("maxBuyQty"), data.get("maxCashBuyQty")))
        print("    第%d次 maxBuyQty=%s maxCashBuyQty=%s" % (
            idx + 1, data.get("maxBuyQty"), data.get("maxCashBuyQty")))
    check(len(set(map(str, values))) == 1, "%d 次最大可买一致" % times)


def stk_price_monotonic():
    """委托价格递增时最大可买递减, 且不超过购买力除以价格"""
    rows = []
    for price in [100, 500, 2000]:
        result = send_query("价格=%s" % price, URL,
                            body("S", US_STOCK, "B", entrustPrice=price), quiet=True)
        if env_blocked(result):
            return
        data = data_of(result)
        rows.append((price, data.get("maxBuyQty"), data.get("maxPurchasePower")))
        print("    price=%-6s maxBuyQty=%s purchasePower=%s" % (
            price, data.get("maxBuyQty"), data.get("maxPurchasePower")))
    quantities = [q for _, q, _ in rows if q is not None]
    check(quantities == sorted(quantities, reverse=True), "价格递增时最大可买递减")
    for price, qty, power in rows:
        if qty and power:
            check(qty <= power / price, "price=%s 最大可买已扣除费用" % price)


def stk_hand_qty_rounding():
    """最大可买按一手数量取整"""
    for hand in [1, 10, 100]:
        result = send_query("handQty=%s" % hand, URL,
                            body("S", US_STOCK, "B", handQty=hand), quiet=True)
        if env_blocked(result):
            return
        qty = data_of(result).get("maxBuyQty") or 0
        check(qty % hand == 0, "handQty=%s 时最大可买为其整数倍" % hand)


def stk_fund_account_source():
    """账号来源: 请求体 fundAccount 不用于切换账号, 结果应保持一致"""
    from common.config import CASH_ACCOUNT, MARGIN_ACCOUNT, TOKEN_FUND_ACCOUNT

    quantities = {}
    for account in [TOKEN_FUND_ACCOUNT, CASH_ACCOUNT, MARGIN_ACCOUNT, ""]:
        result = send_query("fundAccount=%s" % (account or "(空)"), URL,
                            body("S", US_STOCK, "B", fundAccount=account), quiet=True)
        if env_blocked(result):
            return
        quantities[account or "(空)"] = data_of(result).get("maxBuyQty")
        print("    fundAccount=%-12s maxBuyQty=%s" % (
            account or "(空)", data_of(result).get("maxBuyQty")))
    check(len(set(quantities.values())) == 1, "不同 fundAccount 结果一致")


# ============================ SHT 股票沽空 ============================

def sht_01_short_max():
    """SHT-01 股票沽空最大可买可卖"""
    result = run_case("SHT-01 沽空最大可买可卖", body("SHORT", SHORTABLE_STOCK, "S"),
                      FIELDS_SHORT, "SHT-01")
    data = data_of(result)
    if data:
        check(data.get("shortRate") is not None, "融券利率有值")
        check((data.get("maxSellQty") or 0) > 0, "可沽空标的最大可卖大于 0")
    return result


def sht_02_available_tag():
    """SHT-02 可沽空标识: 不可沽空标的最大可卖应为 0"""
    result = run_case("SHT-02 不可沽空标的", body("SHORT", NOT_SHORTABLE_STOCK, "S"), FIELDS_SHORT)
    data = data_of(result)
    if data:
        check(data.get("maxSellQty") == 0, "不可沽空时最大可卖为 0")
    return result


def sht_03_max_available_limit():
    """SHT-03 最大可卖受可沽空上限约束: 用低价放大计算值观察是否被截断"""
    result = run_case("SHT-03 低价放大计算值",
                      body("SHORT", SHORTABLE_STOCK, "S", entrustPrice=0.01), FIELDS_SHORT)
    data = data_of(result)
    if data:
        print("    maxSellQty=%s, 需与标的可沽空上限核对" % data.get("maxSellQty"))
    return result


def sht_repeat_consistency(times=5):
    """沽空多次查询结果一致"""
    values = []
    for idx in range(times):
        result = send_query("沽空第%d次" % (idx + 1), URL,
                            body("SHORT", SHORTABLE_STOCK, "S"), quiet=True)
        if env_blocked(result):
            return
        data = data_of(result)
        values.append((data.get("maxSellQty"), data.get("shortRate")))
        print("    第%d次 maxSellQty=%s shortRate=%s" % (
            idx + 1, data.get("maxSellQty"), data.get("shortRate")))
    check(len(set(map(str, values))) == 1, "%d 次沽空结果一致" % times)


# ============================ 期权与组合 ============================

def opt_max_qty():
    """期权最大可买可卖(businessType=O), 字段为 buyMax / sellMax"""
    result = run_case("期权最大可买可卖(O)", body_option("O"), FIELDS_OPTION, "OPT-MAX")
    data = data_of(result)
    if data:
        check((data.get("buyMax") or 0) > 0, "期权最大可买大于 0")
    return result


def ops_max_sell():
    """OPS 期权沽空最大可卖(businessType=OS)"""
    result = run_case("期权沽空最大可卖(OS)", body_option("OS"), FIELDS_OPTION, "OPS-MAX")
    data = data_of(result)
    if data:
        check((data.get("sellMax") or 0) > 0, "期权沽空最大可卖大于 0")
        check(data.get("expectMargin") is not None, "预计保证金有值")
    return result


def opt_symbol_sensitivity():
    """不同期权代码(行权价与方向不同)的结果差异"""
    conf = COMBO_STRATEGIES["牛市价差"]["comboLegs"]
    symbols = [conf[0]["symbol"], conf[1]["symbol"], OPTION_SYMBOL]
    values = {}
    for symbol in symbols:
        result = send_query("期权 %s" % symbol, URL, body_option("O", symbol=symbol), quiet=True)
        if env_blocked(result):
            return
        values[symbol] = data_of(result).get("buyMax")
        print("    %-20s buyMax=%s" % (symbol, values[symbol]))
    check(len(set(values.values())) > 1, "不同期权代码返回不同的 buyMax")


def cbo_02_all_strategies():
    """CBO-02 各组合策略最大可买可卖"""
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑", "领式"]:
        run_case("CBO-02 %s" % name, body_combo(name), FIELDS_COMBO, "CBO-02-%s" % name)


# ============================ 参数校验与鉴权 ============================

def param_validation():
    """必填与非法值校验"""
    for tag, key in [("不传 businessType", "businessType"), ("不传 entrustPrice", "entrustPrice"),
                     ("不传 market", "market"), ("不传 symbol", "symbol")]:
        payload = body()
        payload.pop(key, None)
        result = send_query("校验 %s" % tag, URL, payload)
        expect_no_server_error(result)
        check(code_of(result) != 0, "%s 应被拒绝" % tag)

    for tag, kwargs in [("entrustPrice=0", {"entrustPrice": 0}),
                        ("entrustPrice 负数", {"entrustPrice": -1}),
                        ("handQty=0", {"handQty": 0}),
                        ("businessType 非法", {"businessType": "XXX"}),
                        ("symbol 不存在", {"symbol": "NOTEXIST999"})]:
        expect_no_server_error(send_query("校验 %s" % tag, URL, body(**kwargs)))

    legs = [dict(leg) for leg in COMBO_STRATEGIES["牛市价差"]["comboLegs"]]
    legs[0]["legRatio"], legs[1]["legRatio"] = 2, 4
    expect_no_server_error(send_query("校验 legRatio 非互质", URL, body_combo(comboLegs=legs)))


def auth_validation():
    """鉴权: 缺失 token / 无效 token / X-Type 取值错误"""
    headers = build_headers()
    headers.pop("Authorization", None)
    result = send_query("不传 token", URL, body(), headers=headers)
    check(code_of(result) == 107003, "返回 107003 Token 不能为空")

    result = send_query("无效 token", URL, body(), headers=build_headers(token="INVALID_TOKEN"))
    check(code_of(result) != 0, "无效 token 不应成功")

    result = send_query("X-Type=1", URL, body(), headers=build_headers(extra={"X-Type": "1"}))
    check(code_of(result) == 107005, "返回 107005 非法请求")


def multi_language():
    """多语言错误文案"""
    messages = {}
    for lang in ["1", "2", "3"]:
        result = send_query("X-Lang=%s" % lang, URL, body(symbol="NOTEXIST999"),
                            headers=build_headers(lang=lang))
        messages[lang] = (result["json"] or {}).get("msg")
    check(len({v for v in messages.values() if v}) > 1, "不同语言返回不同文案")


# ============================ 并发与性能 ============================

def concurrent(times=30, workers=10):
    """高频并发查询: 结果稳定一致"""
    def task():
        return send_query("并发", URL, body("S", US_STOCK, "B"), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=DRIFT)
    failed = [r for r in results if code_of(r) != 0]
    check(not failed, "%d 次并发全部成功" % times)
    return results


def performance(times=20):
    """PERF-01 响应时间采样"""
    return measure("最大可买可卖聚合(新单)",
                   lambda: send_query("性能", URL, body("S", US_STOCK, "B"), quiet=True),
                   times=times)


# ============================ 批量执行 ============================

ALL = [stk_01_max_buy, stk_02_max_sell, stk_03_otc_fee, stk_04_stamp_duty,
       stk_05_multi_market, stk_07_fee_consistency, stk_price_monotonic,
       stk_hand_qty_rounding, stk_fund_account_source,
       sht_01_short_max, sht_02_available_tag, sht_03_max_available_limit,
       sht_repeat_consistency,
       opt_max_qty, ops_max_sell, opt_symbol_sensitivity, cbo_02_all_strategies,
       param_validation, auth_validation, multi_language,
       concurrent, performance]


def run_all():
    print("接口: %s" % URL)
    for func in ALL:
        print("\n" + "-" * 88)
        print(func.__doc__.strip().splitlines()[0])
        print("-" * 88)
        safe(func)


if __name__ == "__main__":
    run_all()
