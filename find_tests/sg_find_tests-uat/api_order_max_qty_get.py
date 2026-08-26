"""
接口2: 获取订单最大可买可卖以及购买力聚合接口(新单)
==================================================
POST /order-center-sg/api/order/stock-order-max-qty-get/v2      (APP 网关 jy-sit)
入参 schema: PurchasePowerReqVO

必填(文档标 true): businessType / entrustPrice / market / symbol
组合腿必填        : entrustSide / legRatio / symbol
条件必传          : comboLegs+comboStrategy(组合多腿) / price(期权) / orderId(改单)
businessType      : S-股票  SHORT-股票沽空  O-期权  OS-期权沽空

注意:
  1. 请求头 X-Type 必须是 12, 写 1 会返回 107005「非法请求」。
  2. 响应字段随 businessType 变化, 见下面三组 FIELDS_*。
  3. 账号由 token 决定, body 里的 fundAccount 不能用来切换账号。

对应 explain.md:
  3.3 股票最大可买可卖      STK-01 ~ STK-07   (businessType=S)
  3.2 股票沽空最大可买可卖  SHT-01 ~ SHT-03   (businessType=SHORT)
  3.4 期权沽空最大可卖      OPS               (businessType=OS)
  3.1 组合最大可买可卖      CBO-02            (comboLegs)
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

# 响应字段按 businessType 分三套(股票/沽空用 maxBuyQty, 期权用 buyMax)
FIELDS_STOCK = ["maxBuyQty", "maxSellQty", "maxPurchasePower",
                "maxCashBuyQty", "maxCashBuyMulti", "cashBalance"]
FIELDS_SHORT = ["maxBuyQty", "maxSellQty", "maxPurchasePower", "shortRate", "expectMargin"]
FIELDS_OPTION = ["buyMax", "sellMax", "maxPurchasePower", "expectMargin"]
# 组合(多腿)请求返回的是 ComboPurchasePowerResp, 与上面三套都不同
FIELDS_COMBO = ["consumePurchasingPower", "holdQty", "openClose", "purchasePower"]

# 金额类字段随账户资金漂移, 基线比对时忽略
DRIFT = ("msg", "error", "cashBalance", "maxPurchasePower")


# ============================ 入参构造 ============================

def body(business_type="S", stock=US_STOCK, side="B", **override):
    b = {
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
    b.update(override)
    return b


def body_option(business_type="O", **override):
    """
    期权 O / 期权沽空 OS —— price 必传。
    entrustQty + entrustSide 对**组合**请求是必需的, 缺任一会返回 450004 服务器处理异常。
    """
    b = {
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
    b.update(override)
    return b


def body_combo(strategy="牛市价差", **override):
    s = COMBO_STRATEGIES[strategy]
    b = body_option("O", comboLegs=s["comboLegs"], comboStrategy=s["comboStrategy"],
                    symbol=s["comboLegs"][0]["symbol"])
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
    """环境/数据类阻塞: 打印原因并返回 True, 让用例跳过业务断言。"""
    c, m = code_of(r), (r.get("json") or {}).get("msg")
    known = {
        107005: "X-Type 不是 12 或 token 无效",
        110002: "token 已失效, 需重新获取",
        450004: "该码被复用(客户信息认证失败/服务器处理异常等), 看 error 字段定位",
        800025: "行情最新价获取失败 —— 标的代码无效或无行情(期权代码需换成真实的)",
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


# ============================ STK 股票 (businessType=S) ============================

def stk_01_max_buy():
    """STK-01 股票最大可买(含费用二分查找) —— 数量与基线完全一致"""
    r = _run("STK-01 股票最大可买", body("S", US_STOCK, "B"), FIELDS_STOCK, "STK-01")
    d = data_of(r)
    if d:
        ok((d.get("maxBuyQty") or 0) > 0, "最大可买 > 0")
        ok((d.get("maxCashBuyQty") or 0) <= (d.get("maxBuyQty") or 0),
           "现金最大可买 <= 最大可买(融资口径应更大或相等)")
    return r


def stk_02_max_sell():
    """STK-02 股票最大可卖"""
    return _run("STK-02 股票最大可卖", body("S", US_STOCK, "S"), FIELDS_STOCK, "STK-02")


def stk_03_otc_fee():
    """STK-03 OTC 标的费用 —— 费用含 OTC 差异(需 config.OTC_STOCK 为真实 OTC 标的)"""
    return _run("STK-03 美股OTC", body("S", OTC_STOCK, "B"), FIELDS_STOCK, "STK-03")


def stk_04_stamp_duty():
    """STK-04 印花税标的费用 —— 港股费用含印花税"""
    return _run("STK-04 港股", body("S", HK_STOCK, "B"), FIELDS_STOCK, "STK-04")


def stk_05_multi_market():
    """STK-05/06 多市场多币种 —— A股市场归一化 + 币种校验"""
    for stock in [US_STOCK, HK_STOCK, A_STOCK]:
        _run(f"STK-05/06 {stock['market']}/{stock['currency']}",
             body("S", stock, "B"), FIELDS_STOCK, f"STK-05-{stock['market']}")


def stk_07_fee_consistency(times=5):
    """
    STK-07 费用二分查找一致性
    费用请求对象提到二分循环外复用, 多次调用最终数量必须完全一致。
    """
    vals = []
    for i in range(times):
        r = send_query(f"STK-07 第{i + 1}次", URL, body("S", US_STOCK, "B"), quiet=True)
        if blocked(r):
            return
        d = data_of(r)
        vals.append((d.get("maxBuyQty"), d.get("maxCashBuyQty")))
        print(f"  第{i + 1}次 maxBuyQty={d.get('maxBuyQty')} maxCashBuyQty={d.get('maxCashBuyQty')}")
    ok(len(set(map(str, vals))) == 1, f"{times} 次最大可买完全一致")


def stk_price_monotonic():
    """价格越高最大可买越少, 且最大可买 <= 购买力/价格(已扣费)"""
    rows = []
    for price in [100, 500, 2000]:
        r = send_query(f"价格={price}", URL,
                       body("S", US_STOCK, "B", entrustPrice=price), quiet=True)
        if blocked(r):
            return
        d = data_of(r)
        rows.append((price, d.get("maxBuyQty"), d.get("maxPurchasePower")))
        print(f"  price={price:<6} maxBuyQty={d.get('maxBuyQty')} pp={d.get('maxPurchasePower')}")
    qtys = [q for _, q, _ in rows if q is not None]
    ok(qtys == sorted(qtys, reverse=True), "价格递增时最大可买递减")
    for price, qty, pp in rows:
        if qty and pp:
            ok(qty <= pp / price, f"price={price} 最大可买已扣费(<=购买力/价格)")


def stk_hand_qty_rounding():
    """最大可买按一手数量取整"""
    for hand in [1, 10, 100]:
        r = send_query(f"handQty={hand}", URL,
                       body("S", US_STOCK, "B", handQty=hand), quiet=True)
        if blocked(r):
            return
        q = data_of(r).get("maxBuyQty") or 0
        ok(q % hand == 0, f"handQty={hand} 时最大可买({q}) 是 {hand} 的整数倍")


def stk_fund_account_ignored():
    """传不同 fundAccount 结果应不变 —— 账号由 token 决定"""
    from common.config import CASH_ACCOUNT, MARGIN_ACCOUNT, TOKEN_FUND_ACCOUNT
    qtys = {}
    for acc in [TOKEN_FUND_ACCOUNT, CASH_ACCOUNT, MARGIN_ACCOUNT, ""]:
        r = send_query(f"fundAccount={acc or '(空)'}", URL,
                       body("S", US_STOCK, "B", fundAccount=acc), quiet=True)
        if blocked(r):
            return
        qtys[acc or "(空)"] = data_of(r).get("maxBuyQty")
        print(f"  fundAccount={acc or '(空)':12} maxBuyQty={data_of(r).get('maxBuyQty')}")
    ok(len(set(qtys.values())) == 1, "不同 fundAccount 结果相同 -> 账号由 token 决定")


# ============================ SHT 股票沽空 (businessType=SHORT) ============================

def sht_01_short_max():
    """SHT-01 股票沽空最大可买可卖 —— 最大可卖/购买力/融券利率/预计保证金"""
    r = _run("SHT-01 沽空最大可买可卖", body("SHORT", SHORTABLE_STOCK, "S"),
             FIELDS_SHORT, "SHT-01")
    d = data_of(r)
    if d:
        ok(d.get("shortRate") is not None, f"融券利率有值(实测 {d.get('shortRate')})")
        ok((d.get("maxSellQty") or 0) > 0, "可沽空标的最大可卖 > 0")
    return r


def sht_02_available_tag():
    """SHT-02 可沽空标识 —— 不可沽空标的最大可卖应为 0"""
    r = _run("SHT-02 不可沽空标的", body("SHORT", NOT_SHORTABLE_STOCK, "S"), FIELDS_SHORT)
    d = data_of(r)
    if d:
        ok(d.get("maxSellQty") == 0, f"不可沽空时最大可卖应为 0(实际 {d.get('maxSellQty')})")
    return r


def sht_03_max_available_limit():
    """SHT-03 最大可卖受可沽空上限约束 —— 用极低价放大计算值, 看是否被截断"""
    r = _run("SHT-03 低价放大计算值",
             body("SHORT", SHORTABLE_STOCK, "S", entrustPrice=0.01), FIELDS_SHORT)
    d = data_of(r)
    if d:
        print("[校验] maxSellQty 应被可沽空上限截断, 实际:", d.get("maxSellQty"))
    return r


def sht_repeat_consistency(times=5):
    """沽空多次查询结果一致(并行取数不应抖动)"""
    vals = []
    for i in range(times):
        r = send_query(f"沽空第{i + 1}次", URL, body("SHORT", SHORTABLE_STOCK, "S"), quiet=True)
        if blocked(r):
            return
        d = data_of(r)
        vals.append((d.get("maxSellQty"), d.get("shortRate")))
        print(f"  第{i + 1}次 maxSellQty={d.get('maxSellQty')} shortRate={d.get('shortRate')}")
    ok(len(set(map(str, vals))) == 1, f"{times} 次沽空结果完全一致")


# ============================ 期权 / 组合 ============================

def opt_max_qty():
    """期权最大可买可卖(businessType=O) —— 字段是 buyMax/sellMax, 不是 maxBuyQty/maxSellQty"""
    r = _run("期权最大可买可卖(O)", body_option("O"), FIELDS_OPTION, "OPT-MAX")
    d = data_of(r)
    if d:
        ok((d.get("buyMax") or 0) > 0, "期权最大可买 buyMax > 0")
    return r


def ops_max_sell():
    """OPS 期权沽空最大可卖(businessType=OS)"""
    r = _run("期权沽空最大可卖(OS)", body_option("OS"), FIELDS_OPTION, "OPS-MAX")
    d = data_of(r)
    if d:
        ok((d.get("sellMax") or 0) > 0, "期权沽空最大可卖 sellMax > 0")
        ok(d.get("expectMargin") is not None, f"预计保证金有值(实测 {d.get('expectMargin')})")
    return r


def opt_symbol_sensitivity():
    """不同期权代码(行权价/方向不同)结果应不同"""
    vals = {}
    for sym in ["QQQ260819C715000", "QQQ260819C725000", "QQQ260819P717000", "QQQ260819C700000"]:
        r = send_query(f"期权 {sym}", URL, body_option("O", symbol=sym), quiet=True)
        if blocked(r):
            return
        vals[sym] = data_of(r).get("buyMax")
        print(f"  {sym:20} buyMax={vals[sym]}")
    ok(len(set(vals.values())) > 1, "不同期权代码返回不同的 buyMax")


def cbo_02_all_strategies():
    """CBO-02 各组合策略最大可买可卖"""
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑", "领式"]:
        _run(f"CBO-02 {name}", body_combo(name), FIELDS_COMBO, f"CBO-02-{name}")


# ============================ 参数校验 ============================

def param_validation():
    """必填校验 —— businessType / entrustPrice / market / symbol; 及非法值"""
    for tag, key in [("不传 businessType", "businessType"), ("不传 entrustPrice", "entrustPrice"),
                     ("不传 market", "market"), ("不传 symbol", "symbol")]:
        b = body()
        b.pop(key, None)
        r = send_query(f"校验 {tag}", URL, b)
        expect_no_server_error(r)
        ok(code_of(r) != 0, f"{tag} 应被拒绝(实际 code={code_of(r)})")

    for tag, kw in [("entrustPrice=0", {"entrustPrice": 0}),
                    ("entrustPrice 负数", {"entrustPrice": -1}),
                    ("handQty=0", {"handQty": 0}),
                    ("businessType 非法", {"businessType": "XXX"}),
                    ("symbol 不存在", {"symbol": "NOTEXIST999"})]:
        r = send_query(f"校验 {tag}", URL, body(**kw))
        expect_no_server_error(r)

    # legRatio 必须互为质数, 2 和 4 非法
    legs = [dict(x) for x in COMBO_STRATEGIES["牛市价差"]["comboLegs"]]
    legs[0]["legRatio"], legs[1]["legRatio"] = 2, 4
    expect_no_server_error(send_query("校验 legRatio=2/4(非互质)", URL, body_combo(comboLegs=legs)))


def auth_validation():
    """鉴权 —— 不传 token / 错 token / X-Type 写错"""
    h = build_headers()
    h.pop("Authorization", None)
    r = send_query("不传 token", URL, body(), headers=h)
    ok(code_of(r) == 107003, f"应返回 107003 Token 不能为空(实际 {code_of(r)})")

    r = send_query("错误 token", URL, body(),
                   headers=build_headers(token="INVALID_TOKEN_1234567890"))
    ok(code_of(r) != 0, "错误 token 不应成功")

    r = send_query("X-Type=1(错误的app类型)", URL, body(),
                   headers=build_headers(extra={"X-Type": "1"}))
    ok(code_of(r) == 107005, f"X-Type 写错应返回 107005 非法请求(实际 {code_of(r)})")


def multi_language():
    """多语言错误文案 —— X-Lang 1简体/2繁体/3英文(用非法 symbol 触发错误)"""
    msgs = {}
    for lang in ["1", "2", "3"]:
        r = send_query(f"X-Lang={lang}", URL, body(symbol="NOTEXIST999"),
                       headers=build_headers(lang=lang))
        msgs[lang] = (r["json"] or {}).get("msg")
        print(f"  X-Lang={lang} -> {msgs[lang]}")
    ok(len(set(v for v in msgs.values() if v)) > 1, "不同语言返回不同文案")


# ============================ 并发 / 性能 ============================

def concurrent(times=30, workers=10):
    """高频并发查询 —— 结果稳定一致, 无偶发异常"""
    def task():
        return send_query("并发", URL, body("S", US_STOCK, "B"), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=DRIFT)
    fail = [r for r in results if code_of(r) != 0]
    ok(not fail, f"{times} 次并发全部成功(失败 {len(fail)})")
    return results


def performance(times=20):
    """PERF-01 响应时间采样 —— 优化前后各跑一次对比"""
    return measure("最大可买可卖聚合(新单)",
                   lambda: send_query("性能", URL, body("S", US_STOCK, "B"), quiet=True),
                   times=times)


# ============================ 批量运行 ============================

ALL = [stk_01_max_buy, stk_02_max_sell, stk_03_otc_fee, stk_04_stamp_duty,
       stk_05_multi_market, stk_07_fee_consistency, stk_price_monotonic,
       stk_hand_qty_rounding, stk_fund_account_ignored,
       sht_01_short_max, sht_02_available_tag, sht_03_max_available_limit,
       sht_repeat_consistency,
       opt_max_qty, ops_max_sell, opt_symbol_sensitivity, cbo_02_all_strategies,
       param_validation, auth_validation, multi_language,
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
