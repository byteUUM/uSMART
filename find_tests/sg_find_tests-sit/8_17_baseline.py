"""
取数一致性基线对比: UAT(优化前) vs SIT(优化后)
================================================
对应 explain.md 核心验证目标 1「取数一致性」。

★ 对比方法说明(很重要):
  两个环境的**账户不同、资金不同**(UAT 购买力 9.6亿 / SIT 992万)，
  所以**绝对数值不可能相同**，直接逐字段比数值会得到一堆假差异。
  跨环境能有效对比的是"行为"而不是"数值":

    1. 字段集合   —— 响应字段有没有增加/减少/改名
    2. 错误码语义 —— 同样的非法入参，两边返回的 code/文案是否一致
    3. 计算规则   —— 价格单调性、一手取整、最大可买<=购买力/价格 是否都成立
    4. 特征行为   —— fundAccount 是否被忽略、handQty=0 是否除零 等

  同环境内的"数值一致性"由 8_17.py 的 c05(重复调用一致) 负责。

用法: python 8_17_baseline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from common.config import AUTHORIZATION as SIT_TOKEN

# ============================ 两个环境 ============================
UAT_TOKEN = (
    "90A25FFBB05229F344673D99D401A27E7C0824AE4EA786E529C4AF4BA6EC742809703A7DE2B4A59F"
    "622AB4937FF739F68EAF478ABD564B08FDF627E45D7B975838E9B44349D95C1CFD273127007826C3"
    "5D70793AAC277230682E0096017AE123405E50E0BF1DE3D1BCE5DF353D5843942F7B726CF2210480"
    "B688023D01550DD7"
)

ENVS = {
    "UAT(优化前)": {
        "base": "https://usmartclient-uat.usmartsg.com",
        "token": UAT_TOKEN,
        "fund": "80019435",
        "order_id": "1606819426467520512",
    },
    "SIT(优化后)": {
        "base": "https://usmartclient-sit.usmartsg.com",
        "token": SIT_TOKEN,
        "fund": "80125375",
        "order_id": "1605376494721105920",
    },
}

STOCK_REPLACE = "/order-center-sg/admin-api/stock-order-replace-max/v1"
SHORT_REPLACE = "/order-center-sg/admin-api/short-order-replace-max/v1"
OPTION_SELL_MAX = "/order-center-sg/admin-api/short-option-sell-max/v1"

RETRY = 3          # UAT 偶发超时/SSL 中断，失败重试
TIMEOUT = 40


def post(env, path, body):
    """带重试的请求。返回 (code, msg, data) ；失败返回 ('ERR', 原因, {})"""
    h = {
        "Authorization": env["token"], "Content-Type": "application/json",
        "X-Channel": "1", "X-Client-Id": "2", "X-Dt": "t1", "X-Lang": "1", "X-Type": "1",
    }
    last = ""
    for _ in range(RETRY):
        try:
            r = requests.post(env["base"] + path, headers=h, json=body, timeout=TIMEOUT)
            j = r.json()
            return j.get("code"), j.get("msg"), (j.get("data") or {}), j.get("error")
        except Exception as e:            # noqa: BLE001
            last = type(e).__name__
    return "ERR", last, {}, None


def compare(title, probe):
    """
    probe(env) -> 任意可比较的结果(通常是 dict/字符串)
    在两个环境各跑一次并对比，打印是否一致。
    """
    print("\n" + "-" * 78)
    print(f"▶ {title}")
    got = {}
    for name, env in ENVS.items():
        got[name] = probe(env)
        print(f"   {name:12} {got[name]}")
    vals = list(got.values())
    same = vals[0] == vals[1]
    print(f"   => {'一致 [PASS]' if same else '不一致 [DIFF]'}")
    return same, got


# ============================ 1. 字段集合 ============================

def t1_field_sets():
    """字段集合是否一致(有没有新增/删除/改名字段)"""
    def probe_stock(env):
        _, _, d, _ = post(env, STOCK_REPLACE,
                          {"entrustPrice": 100, "handQty": 1, "orderId": env["order_id"]})
        return sorted(d.keys())

    def probe_short(env):
        _, _, d, _ = post(env, SHORT_REPLACE,
                          {"entrustPrice": 100, "entrustQty": 1, "handQty": 1,
                           "orderId": env["order_id"]})
        return sorted(d.keys())

    def probe_option(env):
        _, _, d, _ = post(env, OPTION_SELL_MAX,
                          {"accountType": 1, "entrustPrice": 1.5, "entrustSide": "S",
                           "fundAccount": env["fund"], "symbol": "UTL260918C50000"})
        return sorted(d.keys())

    compare("股票改单最大可改 字段集合", probe_stock)
    compare("股票沽空改单最大可改 字段集合", probe_short)
    compare("期权沽空最大可卖 字段集合", probe_option)


# ============================ 2. 错误码语义 ============================

def t2_error_codes():
    """同样的非法入参，两边返回的 code / 文案是否一致"""
    cases = [
        ("不传 orderId", {"entrustPrice": 100, "handQty": 1}),
        ("orderId 不存在", {"entrustPrice": 100, "handQty": 1, "orderId": 1}),
        ("不传 entrustPrice", {"handQty": 1, "orderId": "__OID__"}),
        ("entrustPrice=0", {"entrustPrice": 0, "handQty": 1, "orderId": "__OID__"}),
        ("entrustPrice 负数", {"entrustPrice": -1, "handQty": 1, "orderId": "__OID__"}),
        ("handQty=0", {"entrustPrice": 100, "handQty": 0, "orderId": "__OID__"}),
    ]
    for tag, tpl in cases:
        def probe(env, tpl=tpl):
            b = {k: (env["order_id"] if v == "__OID__" else v) for k, v in tpl.items()}
            code, msg, _, err = post(env, STOCK_REPLACE, b)
            return f"code={code} msg={msg}" + (f" error={err}" if err else "")
        compare(f"错误码 - {tag}", probe)


# ============================ 3. 计算规则 ============================

def t3_calc_rules():
    """价格单调性 / 一手取整 / 最大可买<=购买力÷价格 —— 规则是否都成立"""
    # 注意: 只能比"规则结论"(布尔), 不能把样本数值放进比较字符串 ——
    #      两环境账户资金不同, 数值必然不同, 混进去会产生假 DIFF。
    def probe_monotonic(env):
        qtys = []
        for price in [100, 500, 2000]:
            _, _, d, _ = post(env, STOCK_REPLACE,
                              {"entrustPrice": price, "handQty": 1, "orderId": env["order_id"]})
            qtys.append(d.get("maxBuyQty"))
        print(f"      (样本 price=100/500/2000 -> {qtys})")
        return f"价格递增可买递减={qtys == sorted(qtys, reverse=True)}"

    def probe_rounding(env):
        res = []
        for hand in [1, 10, 100]:
            _, _, d, _ = post(env, STOCK_REPLACE,
                              {"entrustPrice": 100, "handQty": hand, "orderId": env["order_id"]})
            q = d.get("maxBuyQty") or 0
            res.append(q % hand == 0)
        return f"一手取整全部成立={all(res)} ({res})"

    def probe_fee(env):
        _, _, d, _ = post(env, STOCK_REPLACE,
                          {"entrustPrice": 100, "handQty": 1, "orderId": env["order_id"]})
        q, pp = d.get("maxBuyQty"), d.get("maxPurchasePower")
        if not q or not pp:
            return "无法计算"
        print(f"      (购买力={pp} 最大可买={q} 费用占用={pp / 100 - q:.0f}股)")
        return f"最大可买<=购买力/价格={q <= pp / 100}"

    compare("规则 - 价格越高最大可买越少", probe_monotonic)
    compare("规则 - 最大可买按一手取整", probe_rounding)
    compare("规则 - 最大可买已扣费(<=购买力/价格)", probe_fee)


# ============================ 4. 特征行为 ============================

def t4_behaviors():
    """本次实测发现的几个特征行为，在优化前是否已经如此"""
    def probe_fund_ignored(env):
        qtys = set()
        for acc in [env["fund"], "10002178", "80125438", "90000037"]:
            _, _, d, _ = post(env, STOCK_REPLACE,
                              {"entrustPrice": 100, "handQty": 1,
                               "orderId": env["order_id"], "fundAccount": acc})
            qtys.add(d.get("maxBuyQty"))
        return f"换4个账号结果相同(fundAccount被忽略)={len(qtys) == 1}"

    def probe_symbol_ignored(env):
        qtys = set()
        for sym, mkt, cur in [("QQQ", "US", "USD"), ("00700", "HK", "HKD"), ("600519", "HGT", "CNY")]:
            _, _, d, _ = post(env, STOCK_REPLACE,
                              {"entrustPrice": 100, "handQty": 1, "orderId": env["order_id"],
                               "symbol": sym, "market": mkt, "currency": cur})
            qtys.add(d.get("maxBuyQty"))
        return f"换标的结果相同(symbol/market被忽略)={len(qtys) == 1}"

    def probe_option_qty_side(env):
        b = {"accountType": 1, "entrustPrice": 1.5, "fundAccount": env["fund"],
             "symbol": "UTL260918C50000"}
        c_both, m_both, _, _ = post(env, OPTION_SELL_MAX, dict(b, entrustQty=1, entrustSide="S"))
        c_one, _, _, _ = post(env, OPTION_SELL_MAX, dict(b, entrustSide="S"))
        return f"同时传qty+side -> code={c_both}({m_both}) | 只传side -> code={c_one}"

    def probe_frozen(env):
        code, msg, _, _ = post(env, STOCK_REPLACE,
                               {"entrustPrice": 100, "handQty": 1,
                                "orderId": env["order_id"], "fundAccount": "90000037"})
        return f"传冻结账户 code={code} msg={msg}"

    compare("行为 - fundAccount 是否被忽略", probe_fund_ignored)
    compare("行为 - symbol/market 是否被忽略", probe_symbol_ignored)
    compare("行为 - 期权沽空 同时传 entrustQty+entrustSide", probe_option_qty_side)
    compare("行为 - 传冻结账户是否被拦", probe_frozen)


# ============================ 5. 性能对比 ============================

def t5_performance(times=10):
    """响应耗时对比(优化后应明显下降; 注意两环境机器配置/数据量可能不同)"""
    import statistics
    import time
    print("\n" + "-" * 78)
    print("▶ 性能 - 股票改单最大可改 响应耗时")
    for name, env in ENVS.items():
        costs = []
        for _ in range(times):
            t0 = time.time()
            post(env, STOCK_REPLACE,
                 {"entrustPrice": 100, "handQty": 1, "orderId": env["order_id"]})
            costs.append(time.time() - t0)
        print(f"   {name:12} 次数={len(costs)} 平均={statistics.mean(costs):.3f}s "
              f"p50={statistics.median(costs):.3f}s 最大={max(costs):.3f}s")
    print("   注: 两环境硬件/数据量可能不同, 只作参考; 严格性能对比需在同规格压测环境做")


def run_all():
    print("=" * 78)
    print("取数一致性基线对比: UAT(优化前) vs SIT(优化后)")
    print("=" * 78)
    print("UAT 账号", ENVS["UAT(优化前)"]["fund"], " 订单", ENVS["UAT(优化前)"]["order_id"])
    print("SIT 账号", ENVS["SIT(优化后)"]["fund"], " 订单", ENVS["SIT(优化后)"]["order_id"])
    print("\n★ 两环境账户资金不同, 绝对数值必然不同 —— 本脚本对比的是「行为」不是「数值」")
    t1_field_sets()
    t2_error_codes()
    t3_calc_rules()
    t4_behaviors()
    t5_performance()
    print("\n" + "=" * 78)
    print("解读: [PASS]=优化前后行为一致  [DIFF]=行为有变化, 需确认是否预期")
    print("=" * 78)


if __name__ == "__main__":
    run_all()
