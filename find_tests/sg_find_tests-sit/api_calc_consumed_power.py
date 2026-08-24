"""
接口1: 计算消耗购买力
=====================
POST /order-center-sg/api/calculate-consumed-purchasing-power/v1     (APP 网关 jy-sit)
入参 schema: PurchasePowerReqVO
出参 schema: ComboPurchasePowerResp
    consumePurchasingPower  消耗购买力
    holdQty                 持仓可卖/可平仓数量
    openClose               开仓/平仓 (O-开仓 C-平仓)
    purchasePower           期权购买力

注意:
  1. 请求头 X-Type 必须是 12, 写 1 会返回 107005「非法请求」。
  2. 单腿请求(businessType=S / SHORT / O)返回全 0,
     只有组合多腿(comboLegs)才走真实计算 —— 出参 schema 名也说明它是给组合用的。
  3. 账号由 token 决定, body 里的 fundAccount 不能用来切换账号。

对应 explain.md:
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

# 出参字段(接口文档 ComboPurchasePowerResp, 已与实测一致)
FIELDS = ["consumePurchasingPower", "holdQty", "openClose", "purchasePower"]


# ============================ 入参构造 ============================

def body_stock(stock=US_STOCK, side="B", **override):
    """股票 businessType=S"""
    b = {
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
    b.update(override)
    return b


def body_option(business_type="O", **override):
    """期权 O / 期权沽空 OS —— price 必传"""
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
    """组合期权 —— comboLegs + comboStrategy 必传(唯一会走真实计算的入口)"""
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
    """环境/数据类阻塞: 打印原因并返回 True。"""
    c, m = code_of(r), (r.get("json") or {}).get("msg")
    known = {
        107005: "X-Type 不是 12 或 token 无效",
        110002: "token 已失效, 需重新获取",
        450004: "该码被复用(客户信息认证失败/服务器处理异常等), 看 error 字段定位",
        800025: "行情最新价获取失败 —— 期权代码是占位值, 需换成真实代码",
    }
    if c in known:
        err = (result.get("json") or {}).get("error")
        print(f"[阻塞] code={c} {m}" + (f" error={err}" if err else "") + f" => {known[c]}")
        return True
    return False


def _run(name, b, case=None, expect_nonzero=False):
    r = send_query(name, URL, b)
    if blocked(r):
        return r
    d = data_of(r)
    print("[关注字段]", {k: d.get(k) for k in FIELDS})
    ok(code_of(r) == 0, "返回 code=0")
    missing = [f for f in FIELDS if f not in d]
    ok(not missing, f"字段齐全(缺失: {missing or '无'})")
    if expect_nonzero:
        ok(d.get("consumePurchasingPower") not in (None, 0),
           f"消耗购买力应非 0(实际 {d.get('consumePurchasingPower')})")
        ok(d.get("openClose") in ("O", "C"),
           f"openClose 应为 O/C(实际 {d.get('openClose')!r})")
    if case:
        check_baseline(case, r, ignore_keys=("msg", "error", "purchasePower"))
    return r


# ============================ 单腿(只验证可用性, 数值恒为 0) ============================

def single_leg_stock():
    """单腿股票 —— 只校验 code=0 与字段齐全(数值恒为 0, 见文件头说明)"""
    for tag, stock in [("普通美股", US_STOCK), ("港股", HK_STOCK), ("美股OTC", OTC_STOCK)]:
        _run(f"单腿股票-{tag}", body_stock(stock), f"POWER-STK-{tag}")


def single_leg_short():
    """单腿股票沽空 —— 同样返回全 0, 只验证可用性"""
    _run("单腿沽空(SHORT)", body_stock(US_STOCK, "S", businessType="SHORT"), "POWER-SHORT")


def single_leg_option():
    """单腿期权 / 期权沽空"""
    _run("单腿期权(O)", body_option("O"), "POWER-OPT")
    _run("单腿期权沽空(OS)", body_option("OS"), "POWER-OPS")


# ============================ CBO 组合期权(真正的验证入口) ============================

def cbo_01_multi_leg():
    """CBO-01 多腿组合正常购买力 —— 消耗购买力/购买力/开平方向/可用持仓 应有真实值"""
    return _run("CBO-01 多腿组合购买力", body_combo("牛市价差"), "CBO-01", expect_nonzero=True)


def cbo_02_all_strategies():
    """CBO-02 各组合策略覆盖 —— 牛市/熊市价差、跨式/宽跨式、备兑"""
    for name in ["牛市价差", "熊市价差", "跨式", "宽跨式", "备兑", "领式"]:
        _run(f"CBO-02 {name}", body_combo(name), f"CBO-02-{name}")


def cbo_03_stock_or_short_leg():
    """CBO-03 含股票腿/沽空腿的组合 —— 抵押比率/沽空比率取值正确"""
    for name in ["备兑", "领式"]:
        _run(f"CBO-03 {name}", body_combo(name), f"CBO-03-{name}")


def cbo_05_user_info_none():
    """CBO-05 用户信息为空 —— 应抛业务异常, 不出现 500/NPE"""
    r = send_query("CBO-05 不存在的资金账号", URL,
                   body_combo(fundAccount=NOT_EXIST_FUND_ACCOUNT))
    expect_no_server_error(r)
    print(f"       code={code_of(r)} msg={(r['json'] or {}).get('msg')}")
    return r


def cbo_08_frozen_account():
    """CBO-08 冻结账户查询 —— 查询阶段不拦截, 应能返回数字"""
    r = send_query("CBO-08 冻结账户", URL, body_combo(fundAccount=FROZEN_ACCOUNT))
    expect_no_server_error(r)
    print(f"       code={code_of(r)} msg={(r['json'] or {}).get('msg')}")
    return r


def cbo_09_concurrent(times=30, workers=10):
    """CBO-09 高频并发查询 —— 结果稳定一致, 无偶发异常、无数据错乱"""
    def task():
        return send_query("CBO-09 并发", URL, body_combo(), quiet=True)

    results = run_concurrent(task, times=times, max_workers=workers)
    assert_same_results(results, ignore_keys=("msg", "error", "purchasePower"))
    return results


def repeat_consistency(times=5):
    """同入参重复调用结果一致 —— 并行化不应带来结果抖动"""
    vals = []
    for i in range(times):
        r = send_query(f"重复第{i + 1}次", URL, body_combo(), quiet=True)
        if blocked(r):
            return
        d = data_of(r)
        vals.append(tuple(d.get(k) for k in FIELDS))
        print(f"  第{i + 1}次 {[d.get(k) for k in FIELDS]}")
    ok(len(set(map(str, vals))) == 1, f"{times} 次结果完全一致")


# ============================ QUO 组合腿行情 ============================

def quo_01_diff_underlying():
    """QUO-01 多腿不同标的批量取价 —— 各腿期权价与对应标的正股价正确"""
    _run("QUO-01 多腿不同标的", body_combo(comboLegs=COMBO_LEGS_DIFF_UNDERLYING), "QUO-01")


def quo_02_same_underlying():
    """QUO-02 多腿共享同一标的 —— 标的行情只查一次(需配合服务端日志确认去重)"""
    _run("QUO-02 多腿同标的", body_combo(comboLegs=COMBO_LEGS_SAME_UNDERLYING), "QUO-02")
    print("\n[辅助观测] 同标的 vs 不同标的 耗时:")
    measure("同标的", lambda: send_query("QUO-02", URL,
            body_combo(comboLegs=COMBO_LEGS_SAME_UNDERLYING), quiet=True), times=5)
    measure("不同标的", lambda: send_query("QUO-02", URL,
            body_combo(comboLegs=COMBO_LEGS_DIFF_UNDERLYING), quiet=True), times=5)
    print("[校验] 请到服务端日志确认同标的只查 1 次行情")


def quo_03_quote_missing():
    """QUO-03 某腿期权行情缺失 —— 不报 500, 该腿价格为空"""
    r = send_query("QUO-03 某腿行情缺失", URL, body_combo(comboLegs=COMBO_LEGS_NO_QUOTE))
    expect_no_server_error(r)
    print(f"       code={code_of(r)} msg={(r['json'] or {}).get('msg')}")
    return r


# ============================ PRV 下单预览 ============================

def prv_02_multi_short_legs():
    """PRV-02 多 SHORT 腿 —— 用户信息应在多腿间复用(耗时不随腿数线性增长)"""
    two, three = COMBO_LEGS_MULTI_SHORT[:2], COMBO_LEGS_MULTI_SHORT
    _run("PRV-02 3条SHORT腿", body_combo(comboLegs=three, entrustSide="S"), "PRV-02")
    s2 = measure("2条SHORT腿", lambda: send_query("PRV-02", URL,
                 body_combo(comboLegs=two, entrustSide="S"), quiet=True), times=5)
    s3 = measure("3条SHORT腿", lambda: send_query("PRV-02", URL,
                 body_combo(comboLegs=three, entrustSide="S"), quiet=True), times=5)
    if s2 and s3:
        print("[校验] 耗时增幅 %.1f%% (复用用户信息时应远小于腿数增幅)"
              % ((s3["平均"] / s2["平均"] - 1) * 100))


# ============================ 参数校验 / 鉴权 ============================

def param_validation():
    """必填校验 —— businessType / entrustPrice / market / symbol; 期权 price; legRatio 互质"""
    for tag, key in [("不传 businessType", "businessType"), ("不传 entrustPrice", "entrustPrice"),
                     ("不传 market", "market"), ("不传 symbol", "symbol")]:
        b = body_stock()
        b.pop(key, None)
        r = send_query(f"校验 {tag}", URL, b)
        expect_no_server_error(r)
        ok(code_of(r) != 0, f"{tag} 应被拒绝(实际 code={code_of(r)})")

    for tag, kw in [("entrustPrice=0", {"entrustPrice": 0}),
                    ("entrustPrice 负数", {"entrustPrice": -1}),
                    ("handQty=0", {"handQty": 0}),
                    ("businessType 非法", {"businessType": "XXX"})]:
        expect_no_server_error(send_query(f"校验 {tag}", URL, body_stock(**kw)))

    # 期权不传 price(文档: 期权时必传)
    b = body_option("O")
    b.pop("price", None)
    expect_no_server_error(send_query("校验 期权不传 price", URL, b))

    # 组合缺 comboStrategy
    b = body_combo()
    b.pop("comboStrategy", None)
    expect_no_server_error(send_query("校验 组合缺 comboStrategy", URL, b))

    # legRatio 必须互为质数, 2 和 4 非法
    legs = [dict(x) for x in COMBO_STRATEGIES["牛市价差"]["comboLegs"]]
    legs[0]["legRatio"], legs[1]["legRatio"] = 2, 4
    expect_no_server_error(send_query("校验 legRatio=2/4(非互质)", URL, body_combo(comboLegs=legs)))


def auth_validation():
    """鉴权 —— 不传 token / 错 token / X-Type 写错"""
    h = build_headers()
    h.pop("Authorization", None)
    r = send_query("不传 token", URL, body_stock(), headers=h)
    ok(code_of(r) == 107003, f"应返回 107003 Token 不能为空(实际 {code_of(r)})")

    r = send_query("错误 token", URL, body_stock(),
                   headers=build_headers(token="INVALID_TOKEN_1234567890"))
    ok(code_of(r) != 0, "错误 token 不应成功")

    r = send_query("X-Type=1(错误的app类型)", URL, body_stock(),
                   headers=build_headers(extra={"X-Type": "1"}))
    ok(code_of(r) == 107005, f"X-Type 写错应返回 107005 非法请求(实际 {code_of(r)})")


def multi_language():
    """CTX-02 多语言上下文透传 —— X-Lang 1简体/2繁体/3英文"""
    msgs = {}
    for lang in ["1", "2", "3"]:
        b = body_stock()
        b.pop("symbol", None)          # 触发必填校验错误
        r = send_query(f"X-Lang={lang}", URL, b, headers=build_headers(lang=lang))
        msgs[lang] = (r["json"] or {}).get("msg")
        print(f"  X-Lang={lang} -> {msgs[lang]}")
    ok(len(set(v for v in msgs.values() if v)) > 1, "不同语言返回不同文案(语言已透传)")


def trace_id():
    """CTX-01 traceId 连续性 —— 固定 X-Request-Id, 便于日志核对并行子任务"""
    rid = "api-calc-power-trace"
    send_query("固定 requestId", URL, body_combo(),
               headers=build_headers(fixed_request_id=rid))
    print("=" * 60)
    print("请到服务端日志按此 ID 检索, 确认并行子任务日志关联同一 traceId:")
    print("   X-Request-Id =", rid)
    print("=" * 60)


def performance(times=20):
    """PERF-01 响应时间采样 —— 优化前后各跑一次对比"""
    return measure("计算消耗购买力",
                   lambda: send_query("性能", URL, body_combo(), quiet=True), times=times)


# ============================ 批量运行 ============================

ALL = [single_leg_stock, single_leg_short, single_leg_option,
       cbo_01_multi_leg, cbo_02_all_strategies, cbo_03_stock_or_short_leg,
       repeat_consistency, cbo_05_user_info_none, cbo_08_frozen_account,
       quo_01_diff_underlying, quo_03_quote_missing,
       param_validation, auth_validation, multi_language, trace_id,
       cbo_09_concurrent, performance]


def run_all():
    print("接口:", URL)
    for fn in ALL:
        print("\n" + "#" * 72)
        print("#", fn.__doc__.strip().splitlines()[0])
        print("#" * 72)
        safe(fn)


if __name__ == "__main__":
    run_all()
    # quo_02_same_underlying()      # 需看服务端日志确认行情去重
    # prv_02_multi_short_legs()
