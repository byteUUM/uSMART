"""
HK_SIT 期权批量下单 + Mock 成交 + 落库校验
============================================
一次跑完各类期权单, 每笔单下完立刻 mock 成交, 再查库核对状态。

覆盖的单类型:
  1. 普通买入      businessType=O,  side=1, sessionType=0
  2. 普通卖出/平仓  businessType=O,  side=2, sessionType=0   (需该标的有多头持仓)
  3. 沽空开仓      businessType=OS, side=2, sessionType=0    (用沽空账号)
  4. 买入平仓      businessType=OS, side=1, sessionType=0    (需有空头持仓)
  5. 仅盘前买入    sessionType=1,  transactionPassage=AVS    (只能在盘前时段下)
  6. 盘前+盘中买入  sessionType=10, transactionPassage=AVS    (只能在盘前时段下)

前置条件:
  - common/config.py 里的 AUTHORIZATION 必须是有效的 admin-sit token,
    过期时下单返回 {"code":110002,"msg":"登录失效,请重新登录"}。
  - 盘前单只能在盘前时段下: 美东 04:00-09:30 = 北京 16:00-21:30(夏令时),
    且当天得是美股交易日。非盘前时段送 sessionType=1/10 会被 801116 拦。
  - mock 平台会忽略传入的 orderId, 只认"当前最新一笔可 mock 的单",
    所以下单和 mock 必须紧挨着做, 脚本里已用 expect_order_id 做了保护,
    对不上就跳过 mock, 不会误操作别人的单。

用法:
  python batch_orders.py            # 跑盘中那 4 类(1/2/3/4)
  python batch_orders.py pre        # 只跑盘前那 2 类(5/6), 需在盘前时段
  python batch_orders.py all        # 全跑
"""
import os
import sys
import time

CUR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR)
sys.path.insert(0, r"d:\code-3")          # 为了 import db

from unified_orders.option_orders import (          # noqa: E402
    build_option_body, order_id_of,
)
from common.client import send_order                # noqa: E402
from common.config import (                         # noqa: E402
    BUSINESS_TYPE_OPTION, BUSINESS_TYPE_OPTION_SHORT,
    ORDER_TYPE_LIMIT, SESSION_TYPE_REGULAR,
    SESSION_TYPE_PRE_MARKET, SESSION_TYPE_PRE_AND_REGULAR,
    SIDE_BUY, SIDE_SELL, url_for,
)
import mock_deal                                    # noqa: E402
from db import query, use_env                       # noqa: E402

use_env("HK_SIT")

# ============================ 标的与数量 ============================
# 挑标的的原则: 未到期 + 近期在 SIT 下单成功过。跑之前建议用 pick_symbol() 复核。
SYM_LONG = "TSLA260918C5000"      # 做多用: 09-18 到期, 行权价 5.0, SIT 上大量全成记录
PRICE_LONG = 0.10
SYM_SHORT = "NVDA281215C190000"   # 沽空用: 之前实测支持裸卖看涨
PRICE_SHORT = 1.00
QTY = 1


def wait_status(order_id, tries=12, gap=2):
    """轮询库里的订单状态, 返回最后一次查到的行。"""
    row = None
    for _ in range(tries):
        r = query("""
        select id, symbol, session_type, business_type, order_side, order_qty,
               order_price, internal_status, clinch_qty, clinch_amount,
               capital_account, trade_date, rej_txt, create_time, update_time
        from option_order_server.option_order where id = %s
        """, (order_id,))
        if r:
            row = r[0]
            if row["internal_status"] in (810, 350, 800, 820, 825, 830):
                break
        time.sleep(gap)
    return row


def show(row):
    if not row:
        print("   库里查不到这笔单")
        return
    print("   落库: %s | %s | sess=%s %s side=%s | %s@%s | int=%s clinch=%s/%s | td=%s%s"
          % (row["id"], row["symbol"], row["session_type"], row["business_type"],
             row["order_side"], row["order_qty"], row["order_price"],
             row["internal_status"], row["clinch_qty"], row["clinch_amount"],
             row["trade_date"], "  rej=" + str(row["rej_txt"]) if row["rej_txt"] else ""))


def place(name, body, position="long", do_mock=True, deal_qty=None,
          deal_price=None):
    """下单 -> 立刻 mock 成交 -> 查库。返回 orderId 或 None。
    deal_price 不传则按委托价成交; 传了可造"成交价 != 委托价"的场景。"""
    print("\n" + "=" * 78)
    print("### " + name)
    resp = send_order(name, url_for("option_create"), body)
    oid = order_id_of(resp)
    if oid is None:
        print(">>> 下单未成功, 跳过 mock")
        return None
    print(">>> orderId =", oid)

    show(wait_status(oid, tries=3, gap=1))

    if do_mock:
        print("\n--- mock 成交 ---")
        time.sleep(2)
        mock_deal.mock_to("3", order_id=oid, position=position,
                          deal_qty=deal_qty, deal_price=deal_price,
                          expect_order_id=oid)
        time.sleep(3)
        print("--- mock 后复查 ---")
        show(wait_status(oid))
    return oid


# ============================ 各类单 ============================

def run_regular():
    """盘中的 4 类单"""
    ids = {}

    ids["普通买入"] = place(
        "1) 普通买入 O/side=1/盘中",
        build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                          symbol=SYM_LONG, price=PRICE_LONG, qty=QTY,
                          order_type=ORDER_TYPE_LIMIT,
                          session_type=SESSION_TYPE_REGULAR),
        position="long")

    # 卖出需要多头持仓, 上一步买入成交后就有了
    ids["普通卖出"] = place(
        "2) 普通卖出/平仓 O/side=2/盘中",
        build_option_body(side=SIDE_SELL, business_type=BUSINESS_TYPE_OPTION,
                          symbol=SYM_LONG, price=PRICE_LONG, qty=QTY,
                          order_type=ORDER_TYPE_LIMIT,
                          session_type=SESSION_TYPE_REGULAR),
        position="long")

    ids["沽空开仓"] = place(
        "3) 沽空开仓 OS/side=2/盘中",
        build_option_body(side=SIDE_SELL, business_type=BUSINESS_TYPE_OPTION_SHORT,
                          symbol=SYM_SHORT, price=PRICE_SHORT, qty=QTY,
                          order_type=ORDER_TYPE_LIMIT,
                          session_type=SESSION_TYPE_REGULAR),
        position="short")

    ids["买入平仓"] = place(
        "4) 买入平仓 OS/side=1/盘中",
        build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION_SHORT,
                          symbol=SYM_SHORT, price=PRICE_SHORT, qty=QTY,
                          order_type=ORDER_TYPE_LIMIT,
                          session_type=SESSION_TYPE_REGULAR),
        position="short")

    return ids


def run_pre_market():
    """盘前的 2 类单(需在盘前时段: 北京 16:00-21:30 的美股交易日)"""
    ids = {}

    ids["仅盘前买入"] = place(
        "5) 仅盘前买入 sessionType=1/AVS",
        build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                          symbol=SYM_LONG, price=PRICE_LONG, qty=QTY,
                          order_type=ORDER_TYPE_LIMIT,
                          session_type=SESSION_TYPE_PRE_MARKET,
                          transaction_passage="AVS"),
        position="long")

    ids["盘前+盘中买入"] = place(
        "6) 盘前+盘中买入 sessionType=10/AVS",
        build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                          symbol=SYM_LONG, price=PRICE_LONG, qty=QTY,
                          order_type=ORDER_TYPE_LIMIT,
                          session_type=SESSION_TYPE_PRE_AND_REGULAR,
                          transaction_passage="AVS"),
        position="long")

    return ids


def pick_symbol(days=7, limit=15):
    """辅助: 列出近期在 SIT 下单成功(全成)且未到期的标的, 用来挑 SYM_LONG。"""
    print("=== 近%d天全成过、且未到期的标的 ===" % days)
    for r in query("""
    select symbol, max(order_price) px, count(*) c, max(create_time) latest
    from option_order_server.option_order
    where internal_status = 810
      and create_time >= date_sub(now(), interval %s day)
      and maturity_date > curdate()
    group by symbol order by latest desc limit %s
    """, (days, limit)):
        print("| %-20s 参考价=%-8s 全成%s笔 最近 %s"
              % (r["symbol"], r["px"], r["c"], r["latest"]))


def env_check():
    """跑之前先看清当前处在哪个时段, 免得盘前单白下。"""
    from datetime import timedelta
    now = query("select now() n")[0]["n"]
    et = now - timedelta(hours=12)          # 北京 -> 美东(夏令时)
    h = et.hour + et.minute / 60
    seg = ("未开盘 [00:00,04:00)" if h < 4 else
           "盘前交易 [04:00,09:30)" if h < 9.5 else
           "交易中 [09:30,16:00)" if h < 16 else "已收盘 [16:00,24:00)")
    print("北京 %s  ->  美东 %s  ->  %s" % (now, et, seg))
    hol = query("""
    select trade_date, day_type, remark from config_manager.cm_calendar_holiday
    where calendar_time_type = 'US_OPTION'
      and trade_date between date_sub(%s, interval 2 day) and date_add(%s, interval 4 day)
    order by trade_date
    """, (et.date(), et.date()))
    if hol:
        print("附近的美股期权休市日:", [(str(x["trade_date"]), x["remark"]) for x in hol])
    can_pre = (4 <= h < 9.5) and et.weekday() < 5 and \
              not any(x["trade_date"] == et.date() for x in hol)
    print("当前能否下盘前单:", "可以" if can_pre else "不行(会被 801116 拦)")
    return can_pre


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "regular"
    print("#" * 78)
    can_pre = env_check()
    print("#" * 78)
    pick_symbol()

    if mode in ("regular", "all"):
        r = run_regular()
        print("\n盘中类结果:", r)
    if mode in ("pre", "all"):
        if not can_pre:
            print("\n>>> 当前不在盘前时段, 盘前单会被拦, 仍要试就手动改这里的判断")
        r = run_pre_market()
        print("\n盘前类结果:", r)
