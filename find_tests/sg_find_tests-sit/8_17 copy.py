"""
股票改单最大可改 —— 完整测试
接口: POST /order-center-sg/admin-api/stock-order-replace-max/v1
对应 explain.md: 3.3 股票最大可买可卖(改单部分) + 取数一致性 / 并发 / 性能 / 上下文

────────────────────────────────────────────────────────────────────
实测到的接口行为(写用例前先摸清, 避免写出"假通过"的测试):

  1. 文档必填只有 entrustPrice / handQty / orderId 三项, 只传这三个就能成功。
     accountType / entrustQty / entrustWay / currency 都是多余的。

  2. ★ fundAccount 被完全忽略。换成 4 个完全不同的账号, 返回的
     cashBalance / maxBuyQty 一模一样 —— 账号是由 orderId + token 推出来的。
     => 想测不同账户类型, 必须换 token + 换该账号自己的 orderId。

  3. ★ symbol / market / currency 也被完全忽略。标的由 orderId 决定。
     => explain.md 里的 STK-03(OTC费用) / STK-04(印花税) / STK-05(A股归一化)
        / STK-06(多币种) **无法用这个接口验证**, 需要换成对应标的的在途订单,
        或改用"最大可买可卖"新单接口。本文件不写这几个假用例。

  4. entrustPrice 生效: 价格越高最大可买越少(实测 100->101051, 724->13969, 2000->5057)。
  5. handQty 生效: handQty=100 时最大可买按手取整(13969 -> 13900)。
  6. maxPurchasePower / cashBalance 会随账户实际资金**随时间漂移**,
     所以基线比对默认忽略这两个金额字段, 只严格比数量类字段。
────────────────────────────────────────────────────────────────────
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
    measure,
    run_concurrent,
    save_baseline,
    send_query,
    show_fields,
)
from common.config import (
    CASH_ACCOUNT,
    FROZEN_ACCOUNT,
    MARGIN_ACCOUNT,
    PRO_ACCOUNT,
    STOCK_ORDER_ID,
    TOKEN_FUND_ACCOUNT,
    url_for,
)

URL = url_for("stock_replace_max")

# ============================ 业务字段 ============================
ORDER_ID = STOCK_ORDER_ID       # 股票在途订单ID(账号由它决定)
ENTRUST_PRICE = 724.03          # 委托价格
HAND_QTY = 1                    # 一手数量

# 响应 data 的真实字段名(实测)
FIELDS = [
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

# 金额类字段会随账户资金漂移, 基线比对时忽略
DRIFT_FIELDS = ("msg", "error", "cashBalance", "maxPurchasePower")


def body(price=ENTRUST_PRICE, hand=HAND_QTY, order_id=None, **override):
    """请求体。只有 entrustPrice / handQty / orderId 是必填。"""
    b = {
        "entrustPrice": price,
        "handQty": hand,
        "orderId": order_id if order_id is not None else ORDER_ID,
    }
    b.update(override)
    return b


def data_of(result):
    return (result.get("json") or {}).get("data") or {}


def ok(cond, msg):
    print(f"[校验] {msg} {'[PASS]' if cond else '[FAIL]'}")
    return bool(cond)


# ============================ 01 基础功能 ============================

def c01_basic():
    """01 正常改单最大可改 —— 字段齐全、值合理"""
    r = send_query("01 正常改单最大可改", URL, body())
    d = show_fields(r, FIELDS)

    ok(r["json"].get("code") == 0, "返回 code=0")
    missing = [f for f in FIELDS if f not in d]
    ok(not missing, f"字段齐全(缺失: {missing or '无'})")
    ok(d.get("maxBuyQty", 0) > 0, "最大可买 > 0")
    ok(d.get("maxSellQty") is not None, "最大可卖有值")
    return r


# ============================ 02 只传必填字段 ============================

def c02_only_required():
    """02 只传文档必填三项(entrustPrice/handQty/orderId) —— 应与全量入参结果一致"""
    full = send_query("02 全量入参", URL, body(
        accountType=1, entrustQty=1, entrustWay="NET",
        fundAccount=TOKEN_FUND_ACCOUNT, market="US", symbol="QQQ", currency="USD"))
    mini = send_query("02 只传必填三项", URL, body())

    a, b_ = data_of(full), data_of(mini)
    same = all(a.get(k) == b_.get(k) for k in ("maxBuyQty", "maxCashBuyQty", "maxSellQty"))
    ok(same, "数量类字段一致(多余入参不影响结果)")
    return full, mini


# ============================ 03 委托价格影响最大可买 ============================

def c03_price_affects_max_buy():
    """
    03 委托价格生效 —— 价格越高最大可买越少, 且 maxBuyQty 约等于 购买力/价格
    这条同时覆盖 explain.md STK-01「最大可买(含费用二分查找)」
    """
    rows = []
    for price in [100, 724.03, 2000]:
        d = data_of(send_query(f"03 price={price}", URL, body(price=price)))
        rows.append((price, d.get("maxBuyQty"), d.get("maxPurchasePower")))
        print(f"  price={price:<9} maxBuyQty={d.get('maxBuyQty')}  pp={d.get('maxPurchasePower')}")

    qtys = [q for _, q, _ in rows]
    ok(qtys == sorted(qtys, reverse=True), "价格递增时最大可买递减")

    for price, qty, pp in rows:
        if qty and pp:
            theory = pp / price
            ok(qty <= theory, f"price={price} 最大可买({qty}) <= 购买力/价格({theory:.0f}) [扣费后应更小]")
    return rows


# ============================ 04 一手数量取整 ============================

def c04_hand_qty_rounding():
    """04 handQty 生效 —— 最大可买应为一手数量的整数倍"""
    for hand in [1, 10, 100]:
        d = data_of(send_query(f"04 handQty={hand}", URL, body(hand=hand)))
        qty = d.get("maxBuyQty") or 0
        ok(qty % hand == 0, f"handQty={hand} 时最大可买({qty}) 是 {hand} 的整数倍")


# ============================ 05 取数一致性(重复调用) ============================

def c05_repeat_consistency(times=5):
    """
    05 同入参重复调用结果一致
    对应 explain.md STK-07「费用二分查找一致性」——
    费用请求对象提到二分循环外复用, 不能造成累积污染。
    """
    values = []
    for i in range(times):
        d = data_of(send_query(f"05 第{i + 1}次", URL, body(), quiet=True))
        values.append((d.get("maxBuyQty"), d.get("maxCashBuyQty"), d.get("maxSellQty")))
        print(f"  第{i + 1}次 maxBuyQty={d.get('maxBuyQty')} maxCashBuyQty={d.get('maxCashBuyQty')}")

    ok(len(set(values)) == 1, f"{times} 次数量类结果完全一致")
    return values


# ============================ 06 fundAccount 是否被忽略 ============================

def c06_fund_account_ignored():
    """
    06 ★ fundAccount 被忽略(实测行为固化)
    换 4 个完全不同的账号, 结果应完全相同 —— 说明账号由 orderId+token 决定。
    这条不是"期望的正确行为", 而是把已知行为固化下来:
    一旦哪天后端改成真的按 fundAccount 取账号, 这个用例会失败并提醒你。
    """
    results = {}
    for tag, acc in [("token归属", TOKEN_FUND_ACCOUNT), ("CASH", CASH_ACCOUNT),
                     ("MARGIN", MARGIN_ACCOUNT), ("PRO", PRO_ACCOUNT),
                     ("冻结", FROZEN_ACCOUNT)]:
        d = data_of(send_query(f"06 fundAccount={tag}", URL, body(fundAccount=acc), quiet=True))
        results[tag] = d.get("maxBuyQty")
        print(f"  {tag:10}{acc}  maxBuyQty={d.get('maxBuyQty')}")

    ok(len(set(results.values())) == 1,
       "5 个不同账号返回相同结果 -> fundAccount 确实被忽略")
    print("[提示] 想验证不同账户类型, 必须换该账号的 token + 该账号自己的 orderId")
    return results


# ============================ 07 symbol/market 是否被忽略 ============================

def c07_symbol_market_ignored():
    """
    07 ★ symbol / market / currency 被忽略(实测行为固化)
    标的由 orderId 决定, 所以 OTC / 印花税 / A股 这些费用场景
    无法通过改这几个字段来验证。
    """
    results = {}
    for tag, kw in [
        ("原样 QQQ/US", {"symbol": "QQQ", "market": "US", "currency": "USD"}),
        ("港股 00700/HK", {"symbol": "00700", "market": "HK", "currency": "HKD"}),
        ("A股 600519/HGT", {"symbol": "600519", "market": "HGT", "currency": "CNY"}),
        ("美股 AAPL", {"symbol": "AAPL", "market": "US", "currency": "USD"}),
    ]:
        d = data_of(send_query(f"07 {tag}", URL, body(**kw), quiet=True))
        results[tag] = d.get("maxBuyQty")
        print(f"  {tag:18} maxBuyQty={d.get('maxBuyQty')}")

    ok(len(set(results.values())) == 1,
       "改 symbol/market/currency 结果不变 -> 确实被忽略(标的由 orderId 决定)")
    print("[提示] STK-03(OTC)/STK-04(印花税)/STK-05(A股)/STK-06(多币种) 需换对应标的的在途订单")
    return results


# ============================ 08 参数校验 ============================

def c08_param_validation():
    """08 异常入参 —— 应返回业务错误, 不出现 500/NPE"""
    cases = [
        ("不传 orderId", {"entrustPrice": ENTRUST_PRICE, "handQty": HAND_QTY}, "ID不能为空"),
        ("orderId 不存在", body(order_id=1), "订单信息找不到"),
        ("orderId 为字符串0", body(order_id="0"), None),
        ("不传 entrustPrice", {"handQty": HAND_QTY, "orderId": ORDER_ID}, None),
        ("entrustPrice=0", body(price=0), None),
        ("entrustPrice 负数", body(price=-1), None),
        ("handQty=0", body(hand=0), None),
    ]
    for tag, b, expect_text in cases:
        r = send_query(f"08 {tag}", URL, b)
        expect_no_server_error(r)
        if expect_text:
            ok(expect_text in (r.get("text") or ""), f"命中预期提示「{expect_text}」")


# ============================ 09 鉴权 ============================

def c09_auth():
    """09 鉴权异常 —— 不传/传错 token"""
    h = build_headers()
    h.pop("Authorization", None)
    r1 = send_query("09 不传 token", URL, body(), headers=h)
    expect_code(r1, "TOKEN_EMPTY")

    r2 = send_query("09 错误 token", URL, body(),
                    headers=build_headers(token="INVALID_TOKEN_1234567890"))
    expect_no_server_error(r2)
    ok((r2["json"] or {}).get("code") != 0, "错误 token 不应返回成功")
    return r1, r2


# ============================ 10 并发一致性 ============================

def c10_concurrent(times=30, workers=10):
    """10 高频并发查询 —— 结果稳定一致, 无偶发异常(对应 CBO-09)"""
    def task():
        return send_query("10 并发", URL, body(), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=DRIFT_FIELDS)

    fail = [r for r in results if not r or (r["json"] or {}).get("code") != 0]
    ok(not fail, f"{times} 次并发全部成功(失败 {len(fail)} 次)")
    return results


# ============================ 11 多语言 ============================

def c11_multi_language():
    """11 多语言错误文案 —— X-Lang 1简体/2繁体/3英文 应返回对应语言(对应 REG-05 / CTX-02)"""
    msgs = {}
    for lang in ["1", "2", "3"]:
        r = send_query(f"11 X-Lang={lang} 用不存在的orderId触发错误", URL,
                       body(order_id=1), headers=build_headers(lang=lang))
        msgs[lang] = (r["json"] or {}).get("msg")
        print(f"  X-Lang={lang} -> {msgs[lang]}")

    ok(len(set(v for v in msgs.values() if v)) > 1,
       "不同语言返回不同文案(语言上下文已透传)")
    return msgs


# ============================ 12 traceId ============================

def c12_trace_id():
    """12 traceId 连续性 —— 用固定 X-Request-Id 请求, 便于到服务端日志核对并行子任务(CTX-01)"""
    rid = "8-17-stock-replace-max-trace"
    r = send_query("12 固定 requestId", URL, body(),
                   headers=build_headers(fixed_request_id=rid))
    print("=" * 60)
    print("请到服务端日志按此 ID 检索, 确认并行子任务日志能关联同一 traceId:")
    print("   X-Request-Id =", rid)
    print("=" * 60)
    return r


# ============================ 13 性能 ============================

def c13_performance(times=20):
    """13 响应时间采样(对应 PERF-01) —— 优化前后各跑一次做对比"""
    return measure("股票改单最大可改", lambda: send_query("13 性能", URL, body(), quiet=True),
                   times=times)


# ============================ 14 基线 ============================

def c14_save_baseline():
    """14 存基线 —— 在优化前(master)环境执行一次"""
    save_baseline("8_17_stock_replace_max", send_query("14 存基线", URL, body()))


def c14_check_baseline():
    """14 对基线 —— 在优化后环境执行, 逐字段比对(金额类字段会漂移, 已忽略)"""
    r = send_query("14 对基线", URL, body())
    check_baseline("8_17_stock_replace_max", r, ignore_keys=DRIFT_FIELDS)
    return r


# ============================ 全部运行 ============================

ALL = [c01_basic, c02_only_required, c03_price_affects_max_buy, c04_hand_qty_rounding,
       c05_repeat_consistency, c06_fund_account_ignored, c07_symbol_market_ignored,
       c08_param_validation, c09_auth, c10_concurrent, c11_multi_language,
       c12_trace_id, c13_performance]


def run_all():
    if not ORDER_ID:
        print("[中止] 请先在 config.STOCK_ORDER_ID 填入股票在途订单ID")
        return
    for fn in ALL:
        print("\n" + "#" * 72)
        print("#", fn.__doc__.strip().splitlines()[0])
        print("#" * 72)
        try:
            fn()
        except Exception as e:
            print(f"[异常] {fn.__name__}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    run_all()
    # c14_save_baseline()     # 优化前环境执行
    # c14_check_baseline()    # 优化后环境执行
