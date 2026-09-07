"""
HK_SIT 造期权持仓 —— 做多 5 个 + 做空 5 个
=============================================
做多持仓: 普通买入 O/side=1  -> mock 全成 -> option_hold_info.hold_type=11 (多头)
做空持仓: 沽空开仓 OS/side=2 -> mock 全成 -> option_hold_info.hold_type=12 (空头)

注意事项(都是踩过的坑):
  1. 同一标的不能同时有多头和空头。有空头再普通买入报 830018,
     有多头再沽空报 830019。所以做多、做空必须用互不相同的标的。
  2. 沽空不是所有标的都行: 部分标的不支持裸卖看涨(801113
     "支持备兑看涨(Covered Call), 但不支持裸卖看涨期权开仓"),
     裸卖看跌(Put)一般都放得开, 所以做空优先挑 P 的标的。
  3. 沽空要占保证金, 行权价越高占用越大, 额度不够会被拦。
     脚本里做空标的按保证金从小到大排, 前面的先成。
  4. mock 平台只认"当前最新一笔可 mock 的单", 所以必须下一单就立刻 mock,
     脚本里用 expect_order_id 做了保护, 对不上就跳过, 不会动别人的单。
  5. 造完的持仓不要再平仓, 否则 current_num 回 0 就白造了。

用法:
  python build_positions.py            # 做多 5 个 + 做空 5 个
  python build_positions.py long       # 只造做多
  python build_positions.py short      # 只造做空
  python build_positions.py check      # 只查当前持仓, 不下单
"""
import os
import sys
import time

CUR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR)
sys.path.insert(0, r"d:\code-3")

from unified_orders.option_orders import build_option_body      # noqa: E402
from common.config import (                                     # noqa: E402
    BUSINESS_TYPE_OPTION, BUSINESS_TYPE_OPTION_SHORT,
    ORDER_TYPE_LIMIT, SESSION_TYPE_REGULAR, SIDE_BUY, SIDE_SELL,
    CAPITAL_ACCOUNT, SHORT_CAPITAL_ACCOUNT,
)
import batch_orders as B                                        # noqa: E402
from db import query, use_env                                   # noqa: E402

use_env("HK_SIT")

USER_UUID = 876169404924960768      # 77000851 / S77000851 对应的 user_uuid

# ============================ 做多标的 (5 个) ============================
# 都是 SIT 上近期 810 全成过、且未到期的标的; qty 给 2 张便于后续做部分平仓
# 注: AMZN260914C245000 会被 405519 "该正股美股期权暂不支持交易" 拒掉, 已换掉。
LONG_TARGETS = [
    ("TSLA260918C5000",   0.10, 2),
    ("NVDA260918C15000", 12.00, 2),
    ("NVDA261016C190000", 33.15, 2),
    ("NVDA261218C4000",  23.00, 2),
    ("NVDA261016C240000", 8.55, 2),
]

# ============================ 做空标的 (5 个) ============================
# 按保证金占用从小到大排。NVDA281215C190000 是已实测能裸卖看涨的;
# 其余挑 Put, 行权价低的排前面, 保证金占用小、更容易成。
SHORT_TARGETS = [
    ("NVDA281215C190000",  1.00, 1),   # 已验证支持裸卖看涨
    ("NVDA260918P35000",  23.00, 1),   # Put 行权价 35
    ("NVDA261120P100000", 12.00, 1),   # Put 行权价 100
    ("NVDA261016P225000", 24.50, 1),   # Put 行权价 225
    ("AAPL260925P365000", 53.00, 1),   # Put 行权价 365, 保证金最大
]


def show_holds(title="当前持仓"):
    print("\n" + "=" * 96)
    print(title)
    print("=" * 96)
    rows = query("""
    select code, name, hold_type, fund_account, current_num, frozen_num,
           frozen_num_business, uncome_buy_num, uncome_sell_num,
           cost_price, cost_balance, end_date, exercise_price, hold_status, updated_time
    from asset_center.option_hold_info
    where user_id = %s
    order by hold_type, code
    """, (USER_UUID,))
    longs = [r for r in rows if r["hold_type"] == 11]
    shorts = [r for r in rows if r["hold_type"] == 12]

    def dump(tag, lst):
        print("\n--- %s (%d 条) ---" % (tag, len(lst)))
        if not lst:
            print("   (无)")
        for r in lst:
            print("| %-18s acct=%-10s 持仓=%-6s 冻结=%s/%s 在途买/卖=%s/%s "
                  "成本价=%-8s 到期=%s 行权价=%-8s status=%s"
                  % (r["code"], r["fund_account"], r["current_num"],
                     r["frozen_num"], r["frozen_num_business"],
                     r["uncome_buy_num"], r["uncome_sell_num"], r["cost_price"],
                     r["end_date"], r["exercise_price"], r["hold_status"]))

    dump("多头 hold_type=11", longs)
    dump("空头 hold_type=12", shorts)
    print("\n汇总: 多头 %d 个, 空头 %d 个 (current_num<>0 的分别 %d / %d)"
          % (len(longs), len(shorts),
             len([r for r in longs if r["current_num"]]),
             len([r for r in shorts if r["current_num"]])))
    return longs, shorts


def existing_codes(hold_type):
    """已经有持仓(current_num<>0)的标的集合, 用来跳过, 让脚本可以反复重跑只补缺的。"""
    return {r["code"] for r in query("""
    select code from asset_center.option_hold_info
    where user_id = %s and hold_type = %s and current_num <> 0
    """, (USER_UUID, hold_type))}


def build_long():
    """造做多持仓: 普通买入 + mock 全成。已有持仓的标的自动跳过。"""
    have = existing_codes(11)
    result = {}
    for i, (sym, px, qty) in enumerate(LONG_TARGETS, 1):
        if sym in have:
            print("\n### 做多 %d/%d  %s  已有持仓, 跳过" % (i, len(LONG_TARGETS), sym))
            result[sym] = "已有持仓"
            continue
        oid = B.place(
            "做多 %d/%d  %s  买入 %s@%s" % (i, len(LONG_TARGETS), sym, qty, px),
            build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                              symbol=sym, price=px, qty=qty,
                              order_type=ORDER_TYPE_LIMIT,
                              session_type=SESSION_TYPE_REGULAR),
            position="long")
        result[sym] = oid
        time.sleep(1)
    return result


def build_short():
    """造做空持仓: 沽空开仓 + mock 全成。已有持仓的标的自动跳过。"""
    have = existing_codes(12)
    result = {}
    for i, (sym, px, qty) in enumerate(SHORT_TARGETS, 1):
        if sym in have:
            print("\n### 做空 %d/%d  %s  已有持仓, 跳过" % (i, len(SHORT_TARGETS), sym))
            result[sym] = "已有持仓"
            continue
        oid = B.place(
            "做空 %d/%d  %s  沽空 %s@%s" % (i, len(SHORT_TARGETS), sym, qty, px),
            build_option_body(side=SIDE_SELL,
                              business_type=BUSINESS_TYPE_OPTION_SHORT,
                              symbol=sym, price=px, qty=qty,
                              order_type=ORDER_TYPE_LIMIT,
                              session_type=SESSION_TYPE_REGULAR),
            position="short")
        result[sym] = oid
        time.sleep(1)
    return result


def report(tag, res):
    ok = {k: v for k, v in res.items() if v}
    bad = [k for k, v in res.items() if not v]
    print("\n%s: 成功 %d/%d" % (tag, len(ok), len(res)))
    for k, v in ok.items():
        print("   OK   %-18s orderId=%s" % (k, v))
    for k in bad:
        print("   FAIL %-18s (看上面的响应, 常见是保证金不足/不支持裸卖)" % k)
    return ok


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    print("账号: 做多用 %s, 做空用 %s" % (CAPITAL_ACCOUNT, SHORT_CAPITAL_ACCOUNT))
    show_holds("下单前的持仓")

    if mode == "check":
        sys.exit(0)

    long_res, short_res = {}, {}
    if mode in ("all", "long"):
        long_res = build_long()
    if mode in ("all", "short"):
        short_res = build_short()

    print("\n" + "#" * 96)
    if long_res:
        report("做多持仓", long_res)
    if short_res:
        report("做空持仓", short_res)

    time.sleep(5)
    show_holds("下单后的持仓")
