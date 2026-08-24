"""
接口3: 获取订单最大可买可卖以及购买力聚合接口(改单)
==================================================
POST /order-center-sg/api/order/order-replace-max/v2      (APP 网关 jy-sit)
入参 schema: ReplaceOrderMaxQtyReqVO

必填(文档标 true): entrustPrice / entrustQty / orderId
组合腿必填        : entrustSide / legRatio / symbol
条件必传          : businessType  普通订单必传, 组合订单不需要
                    handQty       股票必传
                    comboLegs + comboStrategy  组合多腿订单必传
businessType      : S-股票  SHORT-股票沽空  O-期权  OS-期权沽空

注意:
  1. 入参里没有 market / symbol / fundAccount —— 标的和账号都由 orderId 推导。
  2. orderId 必须属于当前 token 的用户, 否则返回 450004「客户信息认证失败」。
  3. 请求头 X-Type 必须是 12, 写 1 会返回 107005「非法请求」。

对应 explain.md:
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
    STOCK_ORDER_ID,
    url_for,
)

URL = url_for("order_replace_max")

# 响应字段按 businessType 分套
FIELDS_STOCK = ["maxBuyQty", "maxSellQty", "maxPurchasePower",
                "maxCashBuyQty", "maxCashBuyMulti", "cashBalance"]
FIELDS_SHORT = ["maxBuyQty", "maxSellQty", "maxPurchasePower", "shortRate", "expectMargin"]
# 期权/期权沽空: 用 buyMax/sellMax, 且带 expectMargin
FIELDS_OPTION = ["buyMax", "sellMax", "maxPurchasePower", "expectMargin"]
# 组合改单: 返回的是 ComboPurchasePowerResp, 与上面几套完全不同
FIELDS_COMBO = ["consumePurchasingPower", "holdQty", "openClose", "purchasePower"]

DRIFT = ("msg", "error", "cashBalance", "maxPurchasePower")


# ============================ 入参构造 ============================

def body(order_id, business_type="S", price=100, qty=1, hand=1, **override):
    """普通订单改单 —— businessType 必传; 股票传 handQty(期权传 hand=None 省略)"""
    b = {
        "businessType": business_type,
        "entrustPrice": price,
        "entrustQty": qty,
        "orderId": order_id,
    }
    if hand is not None:
        b["handQty"] = hand
    b.update(override)
    return b


def body_combo(order_id, strategy="牛市价差", price=1.5, qty=1, **override):
    """组合订单改单 —— 不传 businessType, 必传 comboLegs + comboStrategy"""
    s = COMBO_STRATEGIES[strategy]
    b = {
        "comboLegs": s["comboLegs"],
        "comboStrategy": s["comboStrategy"],
        "entrustPrice": price,
        "entrustQty": qty,
        "orderId": order_id,
    }
    b.update(override)
    return b


# ============================ 小工具 ============================

def data_of(r):
    return (r.get("json") or {}).get("data") or {}


def code_of(r):
    return (r.get("json") or {}).get("code")


def ok(cond, msg):
    print(f"[校验] {msg} {'[PASS]' if cond else '[FAIL]'}")
    return bool(cond)


def blocked(r):
    """环境/数据类阻塞: 打印原因并返回 True。"""
    c, m = code_of(r), (r.get("json") or {}).get("msg")
    known = {
        107005: "X-Type 不是 12 或 token 无效",
        110002: "token 已失效, 需重新获取",
        450004: "该码被复用(客户信息认证失败/服务器处理异常等), 看 error 字段定位",
        100080: "订单信息找不到 —— orderId 不存在",
        800025: "行情最新价获取失败 —— 标的/期权代码无效",
    }
    if c in known:
        err = (result.get("json") or {}).get("error")
        print(f"[阻塞] code={c} {m}" + (f" error={err}" if err else "") + f" => {known[c]}")
        return True
    return False


def _run(name, b, fields, case=None):
    r = send_query(name, URL, b)
    if blocked(r):
        return r
    d = data_of(r)
    print("[关注字段]", {k: d.get(k) for k in fields})
    ok(code_of(r) == 0, "返回 code=0")
    missing = [f for f in fields if f not in d]
    ok(not missing, f"字段齐全(缺失: {missing or '无'})")
    if case:
        check_baseline(case, r, ignore_keys=DRIFT)
    return r


def _need(order_id, tag):
    if not order_id:
        print(f"[跳过] 需先在 config 填入{tag}在途订单ID(且必须属于当前 JWT 用户)")
        return False
    return True


# ============================ STK 股票改单 ============================

def stk_replace_max():
    """STK 股票改单最大可改(businessType=S) —— 字段齐全, 与基线一致"""
    if not _need(STOCK_ORDER_ID, "股票"):
        return
    r = _run("STK 股票改单最大可改", body(STOCK_ORDER_ID, "S"), FIELDS_STOCK, "REP-STK")
    d = data_of(r)
    if d:
        ok((d.get("maxBuyQty") or 0) > 0, "最大可买 > 0")
    return r


def stk_price_effect():
    """
    委托价格是否影响最大可买
    预期: 价格越高最大可买越少(与新单接口一致)。
    """
    if not _need(STOCK_ORDER_ID, "股票"):
        return
    rows = []
    for price in [100, 500, 2000]:
        r = send_query(f"价格={price}", URL, body(STOCK_ORDER_ID, "S", price=price), quiet=True)
        if blocked(r):
            return
        d = data_of(r)
        rows.append((price, d.get("maxBuyQty"), d.get("maxPurchasePower")))
        print(f"  price={price:<6} maxBuyQty={d.get('maxBuyQty')} pp={d.get('maxPurchasePower')}")

    qtys = [q for _, q, _ in rows if q is not None]
    if len(set(qtys)) == 1:
        ok(False, f"价格从 100 涨到 2000, 最大可买始终是 {qtys[0]} -> entrustPrice 未生效")
        return
    ok(all(a > b for a, b in zip(qtys, qtys[1:])), "价格递增时最大可买严格递减")
    for price, qty, pp in rows:
        if qty and pp:
            ok(qty <= pp / price, f"price={price} 最大可买 <= 购买力/价格")


def stk_hand_qty_rounding():
    """最大可买按一手数量取整(股票必传 handQty)"""
    if not _need(STOCK_ORDER_ID, "股票"):
        return
    for hand in [1, 10, 100]:
        r = send_query(f"handQty={hand}", URL, body(STOCK_ORDER_ID, "S", hand=hand), quiet=True)
        if blocked(r):
            return
        q = data_of(r).get("maxBuyQty") or 0
        ok(q % hand == 0, f"handQty={hand} 时最大可买({q}) 是 {hand} 的整数倍")


def stk_repeat_consistency(times=5):
    """同入参重复调用结果一致(对应 STK-07 费用二分查找一致性)"""
    if not _need(STOCK_ORDER_ID, "股票"):
        return
    vals = []
    for i in range(times):
        r = send_query(f"第{i + 1}次", URL, body(STOCK_ORDER_ID, "S"), quiet=True)
        if blocked(r):
            return
        d = data_of(r)
        vals.append((d.get("maxBuyQty"), d.get("maxCashBuyQty")))
        print(f"  第{i + 1}次 maxBuyQty={d.get('maxBuyQty')}")
    ok(len(set(map(str, vals))) == 1, f"{times} 次数量类结果完全一致")


# ============================ SHT-04 / OPS / CBO-04 ============================

def sht_04_short_replace_max():
    """SHT-04 股票沽空改单最大可买可卖(businessType=SHORT)"""
    if not _need(SHORT_ORDER_ID, "股票沽空"):
        return
    return _run("SHT-04 沽空改单最大可改", body(SHORT_ORDER_ID, "SHORT"),
                FIELDS_SHORT, "REP-SHT")


def ops_replace_sell_max():
    """OPS 期权沽空改单最大可卖(businessType=OS) —— 期权不传 handQty"""
    if not _need(OPTION_SHORT_ORDER_ID, "期权沽空"):
        return
    r = _run("OPS 期权沽空改单最大可卖",
             body(OPTION_SHORT_ORDER_ID, "OS", price=1.5, hand=None),
             FIELDS_OPTION, "REP-OPS")
    d = data_of(r)
    if d:
        ok((d.get("sellMax") or 0) > 0, f"期权沽空最大可卖 > 0(实际 {d.get('sellMax')})")
        ok(d.get("expectMargin") is not None, f"预计保证金有值(实际 {d.get('expectMargin')})")
    return r


def cbo_04_combo_replace_max():
    """CBO-04 组合改单最大可开仓 —— 不传 businessType, 必传 comboLegs+comboStrategy"""
    if not _need(COMBO_ORDER_ID, "组合期权"):
        return
    r = _run("CBO-04 组合改单最大可开仓", body_combo(COMBO_ORDER_ID),
             FIELDS_COMBO, "REP-CBO")
    d = data_of(r)
    if d:
        ok(d.get("openClose") in ("O", "C"), f"openClose 应为 O/C(实际 {d.get('openClose')!r})")
        ok(d.get("consumePurchasingPower") is not None, "消耗购买力有值")
    return r


def cbo_04_all_strategies():
    """CBO-04 各组合策略改单最大可开仓"""
    if not _need(COMBO_ORDER_ID, "组合期权"):
        return
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑"]:
        _run(f"CBO-04 {name}", body_combo(COMBO_ORDER_ID, name),
             FIELDS_COMBO, f"REP-CBO-{name}")


# ============================ 参数校验 / 鉴权 ============================

def param_validation():
    """必填校验 —— entrustPrice / entrustQty / orderId; 股票 handQty; legRatio 互质"""
    oid = STOCK_ORDER_ID or 1
    cases = [
        ("不传 orderId", {"businessType": "S", "entrustPrice": 100, "entrustQty": 1, "handQty": 1}),
        ("不传 entrustPrice", {"businessType": "S", "entrustQty": 1, "handQty": 1, "orderId": oid}),
        ("不传 entrustQty", {"businessType": "S", "entrustPrice": 100, "handQty": 1, "orderId": oid}),
        ("orderId 不存在", body(1, "S")),
        ("entrustPrice=0", body(oid, "S", price=0)),
        ("entrustPrice 负数", body(oid, "S", price=-1)),
        ("entrustQty=0", body(oid, "S", qty=0)),
        ("handQty=0", body(oid, "S", hand=0)),
        ("股票不传 handQty", {"businessType": "S", "entrustPrice": 100,
                            "entrustQty": 1, "orderId": oid}),
        ("businessType 非法", body(oid, "XXX")),
    ]
    for tag, b in cases:
        r = send_query(f"校验 {tag}", URL, b)
        expect_no_server_error(r)
        print(f"       code={code_of(r)} msg={(r['json'] or {}).get('msg')}")

    legs = [dict(x) for x in COMBO_STRATEGIES["牛市价差"]["comboLegs"]]
    legs[0]["legRatio"], legs[1]["legRatio"] = 2, 4
    expect_no_server_error(send_query("校验 legRatio=2/4(非互质)", URL,
                                      body_combo(COMBO_ORDER_ID or oid, comboLegs=legs)))


def auth_validation():
    """鉴权 —— 不传 token / 错 token / X-Type 写错"""
    oid = STOCK_ORDER_ID or 1
    h = build_headers()
    h.pop("Authorization", None)
    r = send_query("不传 token", URL, body(oid, "S"), headers=h)
    ok(code_of(r) == 107003, f"应返回 107003 Token 不能为空(实际 {code_of(r)})")

    r = send_query("错误 token", URL, body(oid, "S"),
                   headers=build_headers(token="INVALID_TOKEN_1234567890"))
    ok(code_of(r) != 0, "错误 token 不应成功")

    r = send_query("X-Type=1(错误的app类型)", URL, body(oid, "S"),
                   headers=build_headers(extra={"X-Type": "1"}))
    ok(code_of(r) == 107005, f"X-Type 写错应返回 107005 非法请求(实际 {code_of(r)})")


def multi_language():
    """多语言错误文案 —— X-Lang 1简体/2繁体/3英文(用不存在的 orderId 触发错误)"""
    msgs = {}
    for lang in ["1", "2", "3"]:
        r = send_query(f"X-Lang={lang}", URL, body(1, "S"), headers=build_headers(lang=lang))
        msgs[lang] = (r["json"] or {}).get("msg")
        print(f"  X-Lang={lang} -> {msgs[lang]}")
    ok(len(set(v for v in msgs.values() if v)) > 1, "不同语言返回不同文案(语言已透传)")


def trace_id():
    """CTX-01 traceId 连续性 —— 固定 X-Request-Id, 便于日志核对并行子任务"""
    if not _need(STOCK_ORDER_ID, "股票"):
        return
    rid = "api-order-replace-max-trace"
    send_query("固定 requestId", URL, body(STOCK_ORDER_ID, "S"),
               headers=build_headers(fixed_request_id=rid))
    print("=" * 60)
    print("请到服务端日志按此 ID 检索, 确认并行子任务日志关联同一 traceId:")
    print("   X-Request-Id =", rid)
    print("=" * 60)


# ============================ 并发 / 性能 ============================

def concurrent(times=30, workers=10):
    """高频并发改单查询 —— 结果稳定一致"""
    if not _need(STOCK_ORDER_ID, "股票"):
        return

    def task():
        return send_query("并发", URL, body(STOCK_ORDER_ID, "S"), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=DRIFT)
    return results


def performance(times=20):
    """PERF-01 响应时间采样"""
    if not _need(STOCK_ORDER_ID, "股票"):
        return
    return measure("最大可买可卖聚合(改单)",
                   lambda: send_query("性能", URL, body(STOCK_ORDER_ID, "S"), quiet=True),
                   times=times)


# ============================ 批量运行 ============================

ALL = [stk_replace_max, stk_price_effect, stk_hand_qty_rounding, stk_repeat_consistency,
       sht_04_short_replace_max, ops_replace_sell_max, cbo_04_combo_replace_max,
       param_validation, auth_validation, multi_language, trace_id,
       concurrent, performance]


def run_all():
    print("接口:", URL)
    for fn in ALL:
        print("\n" + "#" * 72)
        print("#", fn.__doc__.strip().splitlines()[0])
        print("#" * 72)
        safe(fn)


if __name__ == "__main__":
    run_all()
    # cbo_04_all_strategies()
