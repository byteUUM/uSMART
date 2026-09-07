"""
同一期权代码、不同价格 多笔买入/沽空并成交 —— HK_SIT
========================================================
目的: 同标的分多笔不同价格成交, 验证持仓成本价是不是按加权平均算的。

  做多: TSLA260918C5000    普通买入 O/side=1, 三个价格各 2 张
  做空: NVDA281215C190000  沽空开仓 OS/side=2, 三个价格各 1 张

校验口径:
  多头 cost_price = sum(每笔成交额) / sum(每笔成交量)
       cost_balance = sum(成交额)                (正数)
  空头 cost_price 同上取绝对值
       cost_balance = -sum(成交额)               (负数)
  成交额 = 成交量 x 成交价 x contract_multiplier(100)

注意:
  1. 脚本会把下单前的持仓当基线, 把新增几笔算进去后再跟库里的实际值对比,
     所以已有持仓不影响校验。
  2. mock 平台只认最新一笔可 mock 的单, 所以下一单就立刻 mock,
     用 expect_order_id 保护, 对不上就跳过。
  3. 交收确认(current_num 落库)是定时任务, 观察到约每 10 分钟一轮,
     脚本末尾会轮询等待, 最多等 12 分钟。
  4. 沽空占保证金, 价格越高、张数越多占用越大, 额度不够会被拦。

用法:
  python same_symbol_prices.py               # 做多 + 做空, 都成交
  python same_symbol_prices.py long
  python same_symbol_prices.py short
  python same_symbol_prices.py short nofill  # 做空只下单不成交, 留着挂单
  python same_symbol_prices.py check         # 只查当前这两个标的的持仓与成交明细
"""
import os
import sys
import time
from decimal import Decimal

CUR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR)
sys.path.insert(0, r"d:\code-3")

from unified_orders.option_orders import build_option_body      # noqa: E402
from common.config import (                                     # noqa: E402
    BUSINESS_TYPE_OPTION, BUSINESS_TYPE_OPTION_SHORT,
    ORDER_TYPE_LIMIT, SESSION_TYPE_REGULAR, SIDE_BUY, SIDE_SELL,
)
import batch_orders as B                                        # noqa: E402
from db import query, use_env                                   # noqa: E402

use_env("HK_SIT")

USER_UUID = 876169404924960768
MULTIPLIER = Decimal("100")

# ============================ 要跑的批次 ============================
# (期权代码, [(委托价, 张数), ...])
LONG_SYMBOL = "TSLA260918C5000"
LONG_BATCH = [(0.20, 2), (0.35, 2), (0.50, 2)]

SHORT_SYMBOL = "NVDA281215C190000"
SHORT_BATCH = [(2.00, 1), (3.50, 1), (5.00, 1)]


def hold_of(code, hold_type):
    r = query("""
    select id, code, hold_type, fund_account, current_num, frozen_num,
           frozen_num_business, cost_price, cost_balance, total_profit,
           today_delta, updated_time
    from asset_center.option_hold_info
    where user_id = %s and code = %s and hold_type = %s
    """, (USER_UUID, code, hold_type))
    return r[0] if r else None


def clinch_detail(code, side, business_type, order_ids=None):
    """
    该标的已成交的单(按时间)。
    order_ids 传了就只统计这些单(本轮新增)。
    注意别用"时间 > now()"来筛本轮新增: 库里 now() 精度到秒, 下单可能落在同一秒,
    会把第一笔漏掉(踩过)。按订单号筛最稳。
    """
    sql = """
    select o.id, o.order_price, o.clinch_qty, o.clinch_amount, o.internal_status,
           o.create_time
    from option_order_server.option_order o
    where o.user_uuid = %s and o.symbol = %s and o.order_side = %s
      and o.business_type = %s and o.clinch_qty > 0
    """
    args = [USER_UUID, code, side, business_type]
    if order_ids:
        sql += " and o.id in (%s)" % ",".join(["%s"] * len(order_ids))
        args.extend(order_ids)
    return query(sql + " order by o.create_time", tuple(args))


def show_hold(code, hold_type, tag):
    h = hold_of(code, hold_type)
    print("\n--- %s  %s (hold_type=%s) ---" % (tag, code, hold_type))
    if not h:
        print("   (无持仓记录)")
        return None
    print("   holdId=%s acct=%s 持仓=%s 冻结=%s/%s" % (
        h["id"], h["fund_account"], h["current_num"],
        h["frozen_num"], h["frozen_num_business"]))
    print("   成本价=%s  成本额=%s  累计盈亏=%s  更新 %s" % (
        h["cost_price"], h["cost_balance"], h["total_profit"], h["updated_time"]))
    return h


def verify(code, hold_type, side, business_type, base=None, order_ids=None):
    """
    校验加权平均成本价。
    base      : 下单前的持仓快照(dict), 有就按 "基线 + 本轮新增" 算预期。
    order_ids : 本轮新增的订单号列表; 不传则统计该标的全部成交单。
    """
    print("\n" + "=" * 100)
    print("成本价校验  %s  (%s)" % (code, "多头" if hold_type == 11 else "空头"))
    print("=" * 100)

    sign = Decimal(1) if hold_type == 11 else Decimal(-1)

    base_qty = base_amt = Decimal(0)
    if base:
        base_qty = abs(Decimal(str(base["current_num"])))
        base_amt = abs(Decimal(str(base["cost_balance"])))
        print("基线(下单前): 持仓 %s 张, 成本额 %s, 成本价 %s" % (
            base["current_num"], base["cost_balance"], base["cost_price"]))

    rows = clinch_detail(code, side, business_type, order_ids=order_ids)
    add_qty = add_amt = Decimal(0)
    print("\n本轮新增成交明细:" if order_ids else "全部成交明细:")
    if not rows:
        print("   (无)")
    for r in rows:
        q = Decimal(str(r["clinch_qty"]))
        a = Decimal(str(r["clinch_amount"]))
        add_qty += q
        add_amt += a
        px = (a / q / MULTIPLIER) if q else Decimal(0)
        print("   | %s 委托价=%-8s 成交 %s 张 成交额=%-12s 折算成交价=%-8s | %s" % (
            r["id"], r["order_price"], q, a, px, r["create_time"]))
    print("   新增合计: %s 张, 成交额 %s" % (add_qty, add_amt))

    tot_qty = base_qty + add_qty
    tot_amt = base_amt + add_amt
    if not tot_qty:
        print("   张数为 0, 跳过校验")
        return
    expect_px = tot_amt / tot_qty / MULTIPLIER
    print("\n   预期: 张数 = %s + %s = %s" % (base_qty, add_qty, tot_qty))
    print("         成本额 = %s + %s = %s" % (base_amt, add_amt, tot_amt))
    print("         加权平均成本价 = %s / %s / 100 = %s" % (tot_amt, tot_qty, expect_px))

    h = hold_of(code, hold_type)
    if not h:
        print("   库里没有持仓记录, 无法对比")
        return
    real_px = Decimal(str(h["cost_price"]))
    real_bal = Decimal(str(h["cost_balance"]))
    real_num = Decimal(str(h["current_num"]))

    def cmp(name, exp, real, tol=Decimal("0.01")):
        ok = abs(exp - real) <= tol
        print("   [%s] %-8s 预期 %-20s 实际 %-20s" % (
            "OK" if ok else "!!", name, exp, real))
        return ok

    print("\n   对比(空头的张数与成本额为负):")
    cmp("张数", tot_qty * sign, real_num)
    cmp("成本额", tot_amt * sign, real_bal)
    cmp("成本价", expect_px, real_px)


def wait_confirm(codes, minutes=12):
    """等交收确认任务把 current_num / cost_price 刷新。"""
    print("\n等交收确认任务刷新持仓(约每 10 分钟一轮)...")
    base = {c: (hold_of(c, t)["updated_time"] if hold_of(c, t) else None)
            for c, t in codes}
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        done = 0
        for c, t in codes:
            h = hold_of(c, t)
            if h and h["updated_time"] != base[c]:
                done += 1
        now = query("select now() n")[0]["n"]
        print("   %s  已刷新 %d/%d" % (now, done, len(codes)))
        if done >= len(codes):
            return True
        time.sleep(20)
    print("   等待超时, 先按当前数据看")
    return False


def run_long():
    print("\n" + "#" * 100)
    print("做多: %s  不同价格买入" % LONG_SYMBOL)
    print("#" * 100)
    globals()["LONG_BASE"] = show_hold(LONG_SYMBOL, 11, "下单前")
    ids = []
    for i, (px, qty) in enumerate(LONG_BATCH, 1):
        oid = B.place(
            "做多 %d/%d  %s  买入 %s张@%s" % (i, len(LONG_BATCH), LONG_SYMBOL, qty, px),
            build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                              symbol=LONG_SYMBOL, price=px, qty=qty,
                              order_type=ORDER_TYPE_LIMIT,
                              session_type=SESSION_TYPE_REGULAR),
            position="long")
        ids.append((px, qty, oid))
        time.sleep(1)
    globals()["LONG_IDS"] = [o for _, _, o in ids if o]
    return ids


def run_short(do_mock=True):
    """
    同标的不同价格沽空。
    do_mock=False 时只下单不 mock 成交, 单子会停在未成交状态(150/155/300),
    适合留着测改单/撤单, 或者观察冻结与保证金占用。
    """
    print("\n" + "#" * 100)
    print("做空: %s  不同价格沽空%s" % (SHORT_SYMBOL, "" if do_mock else "  (不成交)"))
    print("#" * 100)
    globals()["SHORT_BASE"] = show_hold(SHORT_SYMBOL, 12, "下单前")
    ids = []
    for i, (px, qty) in enumerate(SHORT_BATCH, 1):
        oid = B.place(
            "做空 %d/%d  %s  沽空 %s张@%s%s" % (
                i, len(SHORT_BATCH), SHORT_SYMBOL, qty, px,
                "" if do_mock else "  [不成交]"),
            build_option_body(side=SIDE_SELL,
                              business_type=BUSINESS_TYPE_OPTION_SHORT,
                              symbol=SHORT_SYMBOL, price=px, qty=qty,
                              order_type=ORDER_TYPE_LIMIT,
                              session_type=SESSION_TYPE_REGULAR),
            position="short", do_mock=do_mock)
        ids.append((px, qty, oid))
        time.sleep(1)
    globals()["SHORT_IDS"] = [o for _, _, o in ids if o]
    return ids


def show_open_orders(order_ids, tag="挂单现状"):
    """未成交的单看这个: 状态 / 冻结 / 保证金占用"""
    if not order_ids:
        return
    print("\n" + "=" * 100)
    print(tag)
    print("=" * 100)
    for r in query("""
    select id, symbol, business_type, order_side, order_qty, order_price,
           order_amount, order_total_amount, frozen_amount, excepted_fee,
           internal_status, clinch_qty, capital_account, trade_date,
           create_time, update_time
    from option_order_server.option_order where id in (%s) order by create_time
    """ % ",".join(str(x) for x in order_ids)):
        print("| %s | %-18s %s side=%s | 委托 %s张@%-7s 金额=%-12s | int=%-3s 成交=%s | 冻结=%-10s 预估费=%-7s | %s"
              % (r["id"], r["symbol"], r["business_type"], r["order_side"],
                 r["order_qty"], r["order_price"], r["order_amount"],
                 r["internal_status"], r["clinch_qty"], r["frozen_amount"],
                 r["excepted_fee"], r["update_time"]))

    print("\n--- 这些单的操作流水(冻结/保证金) ---")
    for r in query("""
    select order_id, type, business_type, status, target_qty, target_price,
           target_frozen_amount, target_expect_fee, create_time
    from option_order_server.option_order_operation
    where order_id in (%s) order by order_id, id
    """ % ",".join(str(x) for x in order_ids)):
        print("| order=%s type=%s %s status=%s | 目标 %s张@%s 冻结=%s 预估费=%s | %s"
              % (r["order_id"], r["type"], r["business_type"], r["status"],
                 r["target_qty"], r["target_price"], r["target_frozen_amount"],
                 r["target_expect_fee"], r["create_time"]))

    print("\n--- 这些单的资金流水 ---")
    rows = query("""
    select business_id, trade_type, amount, operation_type, req_url, created_time
    from asset_center.capital_account_bill_business
    where business_id in (%s) order by business_id, id
    """ % ",".join(str(x) for x in order_ids))
    if not rows:
        print("   (无)")
    for r in rows:
        print("| business=%s trade_type=%s amount=%-12s op=%s | %s | %s"
              % (r["business_id"], r["trade_type"], r["amount"],
                 r["operation_type"], r["req_url"], r["created_time"]))

    print("\n--- 沽空账号资金与保证金 ---")
    for r in query("""
    select hs_account, current_balance, frozen_balance_business, fee_balance_business,
           process_margin_balance, process_entrust_balance, updated_time
    from asset_center.capital_account_sub_info
    where user_id = %s and hs_account = 'S77000851'""", (USER_UUID,)):
        print("| %-10s 余额=%-14s 业务冻结=%-12s 费用冻结=%-10s 保证金占用=%-12s 委托占用=%s | %s"
              % (r["hs_account"], r["current_balance"], r["frozen_balance_business"],
                 r["fee_balance_business"], r["process_margin_balance"],
                 r["process_entrust_balance"], r["updated_time"]))


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    mode = args[0] if args else "all"
    nofill = "nofill" in args        # 只下单不成交

    if mode == "check":
        show_hold(LONG_SYMBOL, 11, "当前")
        show_hold(SHORT_SYMBOL, 12, "当前")
        verify(LONG_SYMBOL, 11, 1, BUSINESS_TYPE_OPTION)
        verify(SHORT_SYMBOL, 12, 2, BUSINESS_TYPE_OPTION_SHORT)
        sys.exit(0)

    todo = []
    if mode in ("all", "long"):
        r = run_long()
        print("\n做多下单结果:", [(str(p), q, o) for p, q, o in r])
        todo.append((LONG_SYMBOL, 11))
    if mode in ("all", "short"):
        r = run_short(do_mock=not nofill)
        print("\n做空下单结果:", [(str(p), q, o) for p, q, o in r])
        if not nofill:
            todo.append((SHORT_SYMBOL, 12))

    if todo:
        wait_confirm(todo)

    if mode in ("all", "long"):
        show_hold(LONG_SYMBOL, 11, "下单后")
        verify(LONG_SYMBOL, 11, 1, BUSINESS_TYPE_OPTION,
               base=globals().get("LONG_BASE"), order_ids=globals().get("LONG_IDS"))
    if mode in ("all", "short"):
        if nofill:
            # 不成交: 持仓不该变, 重点看挂单状态与冻结
            show_open_orders(globals().get("SHORT_IDS"), "做空挂单现状(未成交)")
            show_hold(SHORT_SYMBOL, 12, "下单后(持仓应与下单前一致)")
        else:
            show_hold(SHORT_SYMBOL, 12, "下单后")
            verify(SHORT_SYMBOL, 12, 2, BUSINESS_TYPE_OPTION_SHORT,
                   base=globals().get("SHORT_BASE"),
                   order_ids=globals().get("SHORT_IDS"))
