"""
接口3: 获取订单最大可买可卖及购买力聚合(改单)
============================================
POST /order-center-sg/api/order/order-replace-max/v2

入参 schema: ReplaceOrderMaxQtyReqVO
  必填          entrustPrice / entrustQty / orderId
  组合腿必填    entrustSide / legRatio / symbol
  条件必传      businessType(普通订单) / handQty(股票) / comboLegs + comboStrategy(组合)
  businessType  S-股票  SHORT-股票沽空  O-期权  OS-期权沽空

约束:
  入参不含 market / symbol / fundAccount, 标的与账号由 orderId 推导。
  orderId 必须属于当前 token 用户, 否则返回 450004。
  请求头 X-Type 需为 12, 其他取值返回 107005。
  委托属性影响结论: 市价单无委托价, 最大可买按标的市价计算, 此时 entrustPrice
  不参与计算属正常行为; 验证委托价敏感性需使用限价单。

覆盖 explain.md:
  CBO-04 组合改单最大可开仓
  SHT-04 股票沽空改单最大可买可卖
  STK    股票改单最大可改
  OPS    期权沽空改单最大可卖
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
    COMBO_ORDER_ID,
    COMBO_STRATEGIES,
    OPTION_SHORT_ORDER_ID,
    SHORT_ORDER_ID,
    STOCK_LIMIT_ORDER_ID,
    STOCK_ORDER_ID,
    url_for,
)

URL = url_for("order_replace_max")

# 响应字段按 businessType 分四组
FIELDS_STOCK = ["maxBuyQty", "maxSellQty", "maxPurchasePower",
                "maxCashBuyQty", "maxCashBuyMulti", "cashBalance"]
FIELDS_SHORT = ["maxBuyQty", "maxSellQty", "maxPurchasePower", "shortRate", "expectMargin"]
FIELDS_OPTION = ["buyMax", "sellMax", "maxPurchasePower", "expectMargin"]
FIELDS_COMBO = ["consumePurchasingPower", "holdQty", "openClose", "purchasePower"]

DRIFT = ("msg", "error", "cashBalance", "maxPurchasePower")


# ============================ 入参构造 ============================

def body(order_id, business_type="S", price=100, qty=1, hand=1, **override):
    """普通订单改单。股票需传 handQty, 期权传 hand=None 省略该字段。"""
    data = {
        "businessType": business_type,
        "entrustPrice": price,
        "entrustQty": qty,
        "orderId": order_id,
    }
    if hand is not None:
        data["handQty"] = hand
    data.update(override)
    return data


def body_combo(order_id, strategy="牛市价差", price=1.5, qty=1, **override):
    """组合订单改单。不传 businessType, 必传 comboLegs 与 comboStrategy。"""
    conf = COMBO_STRATEGIES[strategy]
    data = {
        "comboLegs": conf["comboLegs"],
        "comboStrategy": conf["comboStrategy"],
        "entrustPrice": price,
        "entrustQty": qty,
        "orderId": order_id,
    }
    data.update(override)
    return data


# ============================ 工具 ============================

ENV_CODES = {
    107005: "X-Type 取值不符或 token 无效",
    110002: "登录状态已失效",
    110003: "当前账号无该接口调用权限",
    100012: "下游服务不可用",
    100080: "订单信息找不到, orderId 不存在或已不在途",
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


def require_order(order_id, label):
    if not order_id:
        raise ValueError("需先在 config 配置%s在途订单ID(须属于当前 token 用户)" % label)
    return True


# ============================ STK 股票改单 ============================

def stk_replace_max():
    """STK 股票改单最大可改(businessType=S)"""
    require_order(STOCK_ORDER_ID, "股票")
    result = run_case("STK 股票改单最大可改", body(STOCK_ORDER_ID, "S"), FIELDS_STOCK, "REP-STK")
    data = data_of(result)
    if data:
        check((data.get("maxBuyQty") or 0) > 0, "最大可买大于 0")
    return result


def stk_price_effect():
    """
    委托价格对最大可买的影响(需限价单)
    预期: 价格递增时最大可买递减, 与新单接口口径一致。
    市价单无委托价, 结果恒定属正常, 因此本用例使用 STOCK_LIMIT_ORDER_ID。
    """
    require_order(STOCK_LIMIT_ORDER_ID, "股票限价")
    rows = []
    for price in [100, 500, 2000]:
        result = send_query("价格=%s" % price, URL,
                            body(STOCK_LIMIT_ORDER_ID, "S", price=price), quiet=True)
        if env_blocked(result):
            return
        data = data_of(result)
        rows.append((price, data.get("maxBuyQty"), data.get("maxPurchasePower")))
        print("    price=%-6s maxBuyQty=%s purchasePower=%s" % (
            price, data.get("maxBuyQty"), data.get("maxPurchasePower")))

    quantities = [q for _, q, _ in rows if q is not None]
    check(all(a > b for a, b in zip(quantities, quantities[1:])),
          "价格递增时最大可买严格递减")
    for price, qty, power in rows:
        if qty and power:
            check(qty <= power / price, "price=%s 最大可买不超过购买力除以价格" % price)


def stk_hand_qty_rounding():
    """最大可买按一手数量取整"""
    require_order(STOCK_ORDER_ID, "股票")
    for hand in [1, 10, 100]:
        result = send_query("handQty=%s" % hand, URL,
                            body(STOCK_ORDER_ID, "S", hand=hand), quiet=True)
        if env_blocked(result):
            return
        qty = data_of(result).get("maxBuyQty") or 0
        check(qty % hand == 0, "handQty=%s 时最大可买为其整数倍" % hand)


def stk_repeat_consistency(times=5):
    """同入参重复调用结果一致"""
    require_order(STOCK_ORDER_ID, "股票")
    values = []
    for idx in range(times):
        result = send_query("第%d次" % (idx + 1), URL, body(STOCK_ORDER_ID, "S"), quiet=True)
        if env_blocked(result):
            return
        data = data_of(result)
        values.append((data.get("maxBuyQty"), data.get("maxCashBuyQty")))
        print("    第%d次 maxBuyQty=%s" % (idx + 1, data.get("maxBuyQty")))
    check(len(set(map(str, values))) == 1, "%d 次数量类结果一致" % times)


# ============================ SHT / OPS / CBO 改单 ============================

def sht_04_short_replace_max():
    """SHT-04 股票沽空改单最大可买可卖(businessType=SHORT)"""
    require_order(SHORT_ORDER_ID, "股票沽空")
    return run_case("SHT-04 沽空改单最大可改", body(SHORT_ORDER_ID, "SHORT"),
                    FIELDS_SHORT, "REP-SHT")


def ops_replace_sell_max():
    """OPS 期权沽空改单最大可卖(businessType=OS), 期权不传 handQty"""
    require_order(OPTION_SHORT_ORDER_ID, "期权沽空")
    result = run_case("OPS 期权沽空改单最大可卖",
                      body(OPTION_SHORT_ORDER_ID, "OS", price=1.5, hand=None),
                      FIELDS_OPTION, "REP-OPS")
    data = data_of(result)
    if data:
        check((data.get("sellMax") or 0) > 0, "期权沽空最大可卖大于 0")
        check(data.get("expectMargin") is not None, "预计保证金有值")
    return result


def ops_qty_effect():
    """期权沽空改单: 预计保证金应随委托数量线性变化"""
    require_order(OPTION_SHORT_ORDER_ID, "期权沽空")
    margins = []
    for qty in [1, 10, 30]:
        result = send_query("entrustQty=%s" % qty, URL,
                            body(OPTION_SHORT_ORDER_ID, "OS", price=1.5, qty=qty, hand=None),
                            quiet=True)
        if env_blocked(result):
            return
        margin = data_of(result).get("expectMargin")
        margins.append((qty, margin))
        print("    entrustQty=%-4s expectMargin=%s" % (qty, margin))
    valid = [(q, m) for q, m in margins if isinstance(m, (int, float)) and m]
    if len(valid) == len(margins) and valid:
        base = valid[0][1] / valid[0][0]
        check(all(abs(m / q - base) < base * 0.01 for q, m in valid), "预计保证金随数量线性变化")


def cbo_04_combo_replace_max():
    """CBO-04 组合改单最大可开仓: 不传 businessType, 必传 comboLegs 与 comboStrategy"""
    require_order(COMBO_ORDER_ID, "组合期权")
    result = run_case("CBO-04 组合改单最大可开仓", body_combo(COMBO_ORDER_ID),
                      FIELDS_COMBO, "REP-CBO")
    data = data_of(result)
    if data:
        check(data.get("openClose") in ("O", "C"), "openClose 为 O 或 C")
        check(data.get("consumePurchasingPower") is not None, "消耗购买力有值")
    return result


def cbo_04_all_strategies():
    """CBO-04 各组合策略改单最大可开仓"""
    require_order(COMBO_ORDER_ID, "组合期权")
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑", "领式"]:
        run_case("CBO-04 %s" % name, body_combo(COMBO_ORDER_ID, name),
                 FIELDS_COMBO, "REP-CBO-%s" % name)


def cbo_04_qty_price_effect():
    """组合改单: 消耗购买力应随委托数量与委托价格变化"""
    require_order(COMBO_ORDER_ID, "组合期权")
    for label, cases in [("entrustQty", [1, 10, 36]), ("entrustPrice", [0.5, 1.5, 50])]:
        values = []
        for value in cases:
            payload = (body_combo(COMBO_ORDER_ID, qty=value) if label == "entrustQty"
                       else body_combo(COMBO_ORDER_ID, price=value))
            result = send_query("%s=%s" % (label, value), URL, payload, quiet=True)
            if env_blocked(result):
                return
            values.append(data_of(result).get("consumePurchasingPower"))
        print("    %s %s -> %s" % (label, cases, values))
        real = [v for v in values if v is not None]
        check(len(set(map(str, real))) > 1, "%s 参与消耗购买力计算" % label)


# ============================ 参数校验与鉴权 ============================

def param_validation():
    """必填与非法值校验"""
    order_id = STOCK_ORDER_ID or 1
    cases = [
        ("不传 orderId", {"businessType": "S", "entrustPrice": 100,
                        "entrustQty": 1, "handQty": 1}),
        ("不传 entrustPrice", {"businessType": "S", "entrustQty": 1,
                             "handQty": 1, "orderId": order_id}),
        ("不传 entrustQty", {"businessType": "S", "entrustPrice": 100,
                           "handQty": 1, "orderId": order_id}),
        ("orderId 不存在", body(1, "S")),
        ("entrustPrice=0", body(order_id, "S", price=0)),
        ("entrustPrice 负数", body(order_id, "S", price=-1)),
        ("entrustQty=0", body(order_id, "S", qty=0)),
        ("handQty=0", body(order_id, "S", hand=0)),
        ("股票不传 handQty", {"businessType": "S", "entrustPrice": 100,
                          "entrustQty": 1, "orderId": order_id}),
        ("businessType 非法", body(order_id, "XXX")),
    ]
    for tag, payload in cases:
        expect_no_server_error(send_query("校验 %s" % tag, URL, payload))

    legs = [dict(leg) for leg in COMBO_STRATEGIES["牛市价差"]["comboLegs"]]
    legs[0]["legRatio"], legs[1]["legRatio"] = 2, 4
    expect_no_server_error(send_query("校验 legRatio 非互质", URL,
                                      body_combo(COMBO_ORDER_ID or order_id, comboLegs=legs)))


def auth_validation():
    """鉴权: 缺失 token / 无效 token / X-Type 取值错误"""
    order_id = STOCK_ORDER_ID or 1
    headers = build_headers()
    headers.pop("Authorization", None)
    result = send_query("不传 token", URL, body(order_id, "S"), headers=headers)
    check(code_of(result) == 107003, "返回 107003 Token 不能为空")

    result = send_query("无效 token", URL, body(order_id, "S"),
                        headers=build_headers(token="INVALID_TOKEN"))
    check(code_of(result) != 0, "无效 token 不应成功")

    result = send_query("X-Type=1", URL, body(order_id, "S"),
                        headers=build_headers(extra={"X-Type": "1"}))
    check(code_of(result) == 107005, "返回 107005 非法请求")


def multi_language():
    """多语言错误文案, 使用不存在的 orderId 触发"""
    messages = {}
    for lang in ["1", "2", "3"]:
        result = send_query("X-Lang=%s" % lang, URL, body(1, "S"),
                            headers=build_headers(lang=lang))
        messages[lang] = (result["json"] or {}).get("msg")
    check(len({v for v in messages.values() if v}) > 1, "不同语言返回不同文案")


def trace_id():
    """CTX-01 链路标识连续性"""
    require_order(STOCK_ORDER_ID, "股票")
    request_id = "api-order-replace-max-trace"
    send_query("固定 requestId", URL, body(STOCK_ORDER_ID, "S"),
               headers=build_headers(fixed_request_id=request_id))
    print("    请在服务端日志按 X-Request-Id=%s 检索, 确认并行子任务归属同一链路" % request_id)


# ============================ 并发与性能 ============================

def concurrent(times=30, workers=10):
    """高频并发改单查询: 结果稳定一致"""
    require_order(STOCK_ORDER_ID, "股票")

    def task():
        return send_query("并发", URL, body(STOCK_ORDER_ID, "S"), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=DRIFT)
    return results


def performance(times=20):
    """PERF-01 响应时间采样"""
    require_order(STOCK_ORDER_ID, "股票")
    return measure("最大可买可卖聚合(改单)",
                   lambda: send_query("性能", URL, body(STOCK_ORDER_ID, "S"), quiet=True),
                   times=times)


# ============================ 批量执行 ============================

ALL = [stk_replace_max, stk_price_effect, stk_hand_qty_rounding, stk_repeat_consistency,
       sht_04_short_replace_max, ops_replace_sell_max, ops_qty_effect,
       cbo_04_combo_replace_max, cbo_04_qty_price_effect,
       param_validation, auth_validation, multi_language, trace_id,
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
