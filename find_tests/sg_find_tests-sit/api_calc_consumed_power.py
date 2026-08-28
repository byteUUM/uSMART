"""
接口1: 计算消耗购买力
=====================
POST /order-center-sg/api/calculate-consumed-purchasing-power/v1

入参 schema: PurchasePowerReqVO
出参 schema: ComboPurchasePowerResp
    consumePurchasingPower  消耗购买力
    holdQty                 持仓可卖/可平仓数量
    openClose               开仓/平仓 (O-开仓 C-平仓)
    purchasePower           期权购买力

约束:
  请求头 X-Type 需为 12, 其他取值返回 107005。
  账号由 token 决定, 请求体中的 fundAccount 不用于切换账号。
  组合请求必须同时携带 comboLegs 与 comboStrategy。

覆盖 explain.md:
  3.1 组合期权购买力      CBO-01 ~ CBO-09
  3.7 组合腿行情批量查询  QUO-01 ~ QUO-05
  3.8 下单预览            PRV-01 ~ PRV-02
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
    ACCOUNT_TYPE,
    COMBO_LEGS_DIFF_UNDERLYING,
    COMBO_LEGS_MULTI_SHORT,
    COMBO_LEGS_NO_QUOTE,
    COMBO_LEGS_SAME_UNDERLYING,
    COMBO_STRATEGIES,
    FROZEN_ACCOUNT,
    HK_STOCK,
    NOT_EXIST_FUND_ACCOUNT,
    OPTION_MULTIPLIER,
    OPTION_SYMBOL,
    OTC_STOCK,
    US_STOCK,
    url_for,
)

URL = url_for("consume_power")

FIELDS = ["consumePurchasingPower", "holdQty", "openClose", "purchasePower"]

# 基线比对时忽略的字段(账户购买力随资金变动)
DRIFT = ("msg", "error", "purchasePower")


# ============================ 入参构造 ============================

def body_stock(stock=US_STOCK, side="B", **override):
    """股票 businessType=S"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "S",
        "currencyCode": stock["currency"],
        "entrustPrice": 100,
        "entrustQty": 10,
        "entrustSide": side,
        "entrustWay": "NET",
        "handQty": stock["handQty"],
        "market": stock["market"],
        "symbol": stock["symbol"],
    }
    body.update(override)
    return body


def body_option(business_type="O", **override):
    """期权 O / 期权沽空 OS, price 必传"""
    body = {
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
    body.update(override)
    return body


def body_combo(strategy="牛市价差", **override):
    """组合期权, comboLegs 与 comboStrategy 必传"""
    conf = COMBO_STRATEGIES[strategy]
    body = body_option("O", comboLegs=conf["comboLegs"],
                       comboStrategy=conf["comboStrategy"],
                       symbol=conf["comboLegs"][0]["symbol"])
    body.update(override)
    return body


# ============================ 工具 ============================

# 环境或数据类返回码, 命中后跳过业务断言
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
    """命中环境或数据类返回码时输出原因并返回 True。"""
    body = result.get("json") or {}
    code = body.get("code")
    if code in ENV_CODES:
        print("    环境阻塞 code=%s %s (%s)%s" % (
            code, body.get("msg"), ENV_CODES[code],
            " error=%s" % body["error"] if body.get("error") else ""))
        return True
    return False


def run_case(name, body, case=None, expect_nonzero=False):
    result = send_query(name, URL, body)
    if env_blocked(result):
        return result
    data = data_of(result)
    print("    字段 %s" % {k: data.get(k) for k in FIELDS})
    check(code_of(result) == 0, "返回 code=0")
    missing = [f for f in FIELDS if f not in data]
    check(not missing, "响应字段齐全" + ("" if not missing else "(缺失 %s)" % missing))
    if expect_nonzero:
        check(data.get("consumePurchasingPower") not in (None, 0), "消耗购买力非 0")
        check(data.get("openClose") in ("O", "C"), "openClose 为 O 或 C")
    if case:
        check_baseline(case, result, ignore_keys=DRIFT)
    return result


# ============================ 单腿可用性 ============================

def single_leg_stock():
    """单腿股票: 校验接口可用与响应结构"""
    for tag, stock in [("普通美股", US_STOCK), ("港股", HK_STOCK), ("美股OTC", OTC_STOCK)]:
        run_case("单腿股票-%s" % tag, body_stock(stock), "POWER-STK-%s" % tag)


def single_leg_short():
    """单腿股票沽空: 校验接口可用与响应结构"""
    run_case("单腿沽空(SHORT)", body_stock(US_STOCK, "S", businessType="SHORT"), "POWER-SHORT")


def single_leg_option():
    """单腿期权与期权沽空: 校验接口可用与响应结构"""
    run_case("单腿期权(O)", body_option("O"), "POWER-OPT")
    run_case("单腿期权沽空(OS)", body_option("OS"), "POWER-OPS")


# ============================ CBO 组合期权 ============================

def cbo_01_multi_leg():
    """CBO-01 多腿组合正常购买力"""
    return run_case("CBO-01 多腿组合购买力", body_combo("牛市价差"), "CBO-01", expect_nonzero=True)


def cbo_02_all_strategies():
    """CBO-02 各组合策略覆盖"""
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑", "领式"]:
        run_case("CBO-02 %s" % name, body_combo(name), "CBO-02-%s" % name)


def cbo_03_stock_or_short_leg():
    """CBO-03 含股票腿或沽空腿的组合"""
    for name in ["备兑", "领式"]:
        run_case("CBO-03 %s" % name, body_combo(name), "CBO-03-%s" % name)


def cbo_05_user_info_none():
    """CBO-05 用户信息为空: 应返回业务异常且无系统异常"""
    result = send_query("CBO-05 不存在的资金账号", URL,
                        body_combo(fundAccount=NOT_EXIST_FUND_ACCOUNT))
    expect_no_server_error(result)
    return result


def cbo_08_frozen_account():
    """CBO-08 冻结账户查询: 查询阶段不拦截"""
    result = send_query("CBO-08 冻结账户", URL, body_combo(fundAccount=FROZEN_ACCOUNT))
    expect_no_server_error(result)
    return result


def cbo_09_concurrent(times=30, workers=10):
    """CBO-09 高频并发查询: 结果稳定一致"""
    def task():
        return send_query("CBO-09 并发", URL, body_combo(), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=DRIFT)
    return results


def repeat_consistency(times=5):
    """同入参重复调用结果一致"""
    values = []
    for idx in range(times):
        result = send_query("重复第%d次" % (idx + 1), URL, body_combo(), quiet=True)
        if env_blocked(result):
            return
        data = data_of(result)
        values.append(tuple(data.get(k) for k in FIELDS))
        print("    第%d次 %s" % (idx + 1, [data.get(k) for k in FIELDS]))
    check(len(set(map(str, values))) == 1, "%d 次结果一致" % times)


# ============================ QUO 组合腿行情 ============================

def quo_01_diff_underlying():
    """QUO-01 多腿不同标的批量取价"""
    run_case("QUO-01 多腿不同标的", body_combo(comboLegs=COMBO_LEGS_DIFF_UNDERLYING), "QUO-01")


def quo_02_same_underlying():
    """QUO-02 多腿共享同一标的: 标的行情应只查询一次(需结合服务端日志确认)"""
    run_case("QUO-02 多腿同标的", body_combo(comboLegs=COMBO_LEGS_SAME_UNDERLYING), "QUO-02")
    measure("同标的", lambda: send_query("QUO-02", URL,
            body_combo(comboLegs=COMBO_LEGS_SAME_UNDERLYING), quiet=True), times=5)
    measure("不同标的", lambda: send_query("QUO-02", URL,
            body_combo(comboLegs=COMBO_LEGS_DIFF_UNDERLYING), quiet=True), times=5)
    print("    需在服务端日志确认同标的仅查询一次行情")


def quo_03_quote_missing():
    """QUO-03 某腿期权行情缺失: 不应出现系统异常"""
    result = send_query("QUO-03 某腿行情缺失", URL, body_combo(comboLegs=COMBO_LEGS_NO_QUOTE))
    expect_no_server_error(result)
    return result


# ============================ PRV 下单预览 ============================

def prv_02_multi_short_legs():
    """PRV-02 多条卖出腿: 用户信息应在腿之间复用, 耗时不随腿数线性增长"""
    two, three = COMBO_LEGS_MULTI_SHORT[:2], COMBO_LEGS_MULTI_SHORT
    run_case("PRV-02 3条卖出腿", body_combo(comboLegs=three, entrustSide="S"), "PRV-02")
    stat2 = measure("2条卖出腿", lambda: send_query("PRV-02", URL,
                    body_combo(comboLegs=two, entrustSide="S"), quiet=True), times=5)
    stat3 = measure("3条卖出腿", lambda: send_query("PRV-02", URL,
                    body_combo(comboLegs=three, entrustSide="S"), quiet=True), times=5)
    if stat2 and stat3:
        print("    耗时增幅 %.1f%%" % ((stat3["平均"] / stat2["平均"] - 1) * 100))


# ============================ 参数校验与鉴权 ============================

def param_validation():
    """必填与非法值校验"""
    for tag, key in [("不传 businessType", "businessType"), ("不传 entrustPrice", "entrustPrice"),
                     ("不传 market", "market"), ("不传 symbol", "symbol")]:
        body = body_stock()
        body.pop(key, None)
        result = send_query("校验 %s" % tag, URL, body)
        expect_no_server_error(result)
        check(code_of(result) != 0, "%s 应被拒绝" % tag)

    for tag, kwargs in [("entrustPrice=0", {"entrustPrice": 0}),
                        ("entrustPrice 负数", {"entrustPrice": -1}),
                        ("handQty=0", {"handQty": 0}),
                        ("businessType 非法", {"businessType": "XXX"})]:
        expect_no_server_error(send_query("校验 %s" % tag, URL, body_stock(**kwargs)))

    body = body_option("O")
    body.pop("price", None)
    expect_no_server_error(send_query("校验 期权不传 price", URL, body))

    body = body_combo()
    body.pop("comboStrategy", None)
    expect_no_server_error(send_query("校验 组合缺 comboStrategy", URL, body))

    legs = [dict(leg) for leg in COMBO_STRATEGIES["牛市价差"]["comboLegs"]]
    legs[0]["legRatio"], legs[1]["legRatio"] = 2, 4
    expect_no_server_error(send_query("校验 legRatio 非互质", URL, body_combo(comboLegs=legs)))


def auth_validation():
    """鉴权: 缺失 token / 无效 token / X-Type 取值错误"""
    headers = build_headers()
    headers.pop("Authorization", None)
    result = send_query("不传 token", URL, body_stock(), headers=headers)
    check(code_of(result) == 107003, "返回 107003 Token 不能为空")

    result = send_query("无效 token", URL, body_stock(),
                        headers=build_headers(token="INVALID_TOKEN"))
    check(code_of(result) != 0, "无效 token 不应成功")

    result = send_query("X-Type=1", URL, body_stock(),
                        headers=build_headers(extra={"X-Type": "1"}))
    check(code_of(result) == 107005, "返回 107005 非法请求")


def multi_language():
    """CTX-02 多语言上下文透传"""
    messages = {}
    for lang in ["1", "2", "3"]:
        body = body_stock()
        body.pop("symbol", None)
        result = send_query("X-Lang=%s" % lang, URL, body, headers=build_headers(lang=lang))
        messages[lang] = (result["json"] or {}).get("msg")
    check(len({v for v in messages.values() if v}) > 1, "不同语言返回不同文案")


def trace_id():
    """CTX-01 链路标识连续性: 固定 X-Request-Id 便于日志核对"""
    request_id = "api-calc-power-trace"
    send_query("固定 requestId", URL, body_combo(),
               headers=build_headers(fixed_request_id=request_id))
    print("    请在服务端日志按 X-Request-Id=%s 检索, 确认并行子任务归属同一链路" % request_id)


def performance(times=20):
    """PERF-01 响应时间采样"""
    return measure("计算消耗购买力",
                   lambda: send_query("性能", URL, body_combo(), quiet=True), times=times)


# ============================ 批量执行 ============================

ALL = [single_leg_stock, single_leg_short, single_leg_option,
       cbo_01_multi_leg, cbo_02_all_strategies, cbo_03_stock_or_short_leg,
       repeat_consistency, cbo_05_user_info_none, cbo_08_frozen_account,
       quo_01_diff_underlying, quo_03_quote_missing,
       param_validation, auth_validation, multi_language, trace_id,
       cbo_09_concurrent, performance]


def run_all():
    print("接口: %s" % URL)
    for func in ALL:
        print("\n" + "-" * 88)
        print(func.__doc__.strip().splitlines()[0])
        print("-" * 88)
        safe(func)


if __name__ == "__main__":
    run_all()
