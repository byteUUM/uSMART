# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\code-3")
from db import query, use_env
use_env("HK_SIT")

OID = 1149380432019238912
ST = {100:"等待冻结",105:"冻结中",150:"待提交上手",155:"提交上手中",160:"上手报单中",
      300:"等待成交",350:"部成等待",450:"等待撤单",451:"等待上手撤单",480:"成交中",
      800:"部成已撤",810:"全成",820:"废单",825:"下单失败",830:"撤单",840:"日末撤单",
      850:"上手撤单"}

r = query("""
select id, order_no, symbol, session_type, business_type, order_side,
       order_qty, order_price, internal_status, before_operation_status,
       clinch_qty, clinch_amount, forced_cancel, frozen_amount, excepted_fee,
       fee, rej_reason, rej_txt, fail_reason, capital_account, transaction_passage,
       trade_date, settle_date, create_time, update_time
from option_order_server.option_order where id = %s""", (OID,))
if not r:
    print("主表无此单, 查历史表/gtd")
    for t, c in (("option_order_history","origin_order_id"),("gtd_order","id")):
        try:
            x = query("select * from option_order_server.%s where %s=%%s" % (t,c),(OID,))
            print(t, len(x), x[:1])
        except Exception as e:
            print(t, "ERR", str(e)[:80])
else:
    o = r[0]
    print("订单号     :", o["id"])
    print("标的       :", o["symbol"], "| session_type=", o["session_type"],
          "| business_type=", o["business_type"], "| side=", o["order_side"])
    print("委托       : %s 张 @ %s" % (o["order_qty"], o["order_price"]))
    print("状态       : %s (%s)  before=%s" % (
        o["internal_status"], ST.get(o["internal_status"],"?"), o["before_operation_status"]))
    print("成交       : qty=%s amount=%s" % (o["clinch_qty"], o["clinch_amount"]))
    print("冻结/费用  : frozen=%s 预估费=%s 实收=%s" % (o["frozen_amount"], o["excepted_fee"], o["fee"]))
    print("强制撤单   :", o["forced_cancel"])
    print("拒绝/失败  : rej_reason=%s rej_txt=%s fail=%s" % (
        o["rej_reason"], o["rej_txt"], o["fail_reason"]))
    print("账号/通道  : %s / passage=%s" % (o["capital_account"], o["transaction_passage"]))
    print("交易日     : trade_date=%s settle_date=%s" % (o["trade_date"], o["settle_date"]))
    print("时间       : 建 %s  更 %s" % (o["create_time"], o["update_time"]))

    print("\n--- 操作流水 option_order_operation ---")
    for x in query("""
    select id, type, business_type, status, original_status, target_qty, target_price,
           target_frozen_amount, create_time from option_order_server.option_order_operation
    where order_id=%s order by id""", (OID,)):
        print("   type=%s %s status=%s origStatus=%s targetQty=%s targetPx=%s frozen=%s | %s" % (
            x["type"], x["business_type"], x["status"], x["original_status"],
            x["target_qty"], x["target_price"], x["target_frozen_amount"], x["create_time"]))

    print("\n--- 成交流水 option_order_clinch ---")
    cl = query("select id, clinch_qty, clinch_price, clinch_amount, status, create_time "
               "from option_order_server.option_order_clinch where order_id=%s order by id", (OID,))
    print("   %d 条" % len(cl))
    for x in cl:
        print("   qty=%s price=%s amount=%s status=%s | %s" % (
            x["clinch_qty"], x["clinch_price"], x["clinch_amount"], x["status"], x["create_time"]))
