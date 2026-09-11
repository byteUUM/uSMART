# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\code-3")
from db import query, use_env

for env in ("HK_SIT", "HK_UAT"):
    use_env(env)
    print("\n" + "=" * 60, env, "=" * 10)
    print("-- OS 单(沽空/买入平仓/强平), 取 order_qty>0 的最近几笔 --")
    for r in query("""
    select id, order_no, symbol, business_type, order_side, is_stop_out,
           order_qty, order_price, order_amount, internal_status, create_time
    from option_order_server.option_order
    where business_type='OS' and order_qty>0
    order by create_time desc limit 4"""):
        print("| id=%s no=%s %-18s side=%s stop=%s int=%s | qty=%s px=%s amt=%s | %s" % (
            r["id"], r["order_no"], r["symbol"], r["order_side"], r["is_stop_out"],
            r["internal_status"], r["order_qty"], r["order_price"], r["order_amount"],
            r["create_time"]))
    print("-- 对照用普通 O 单 --")
    for r in query("""
    select id, order_no, symbol, business_type, order_side, order_qty, order_price, order_amount
    from option_order_server.option_order
    where business_type='O' and order_qty>0 order by create_time desc limit 2"""):
        print("| id=%s no=%s %-18s side=%s | qty=%s px=%s amt=%s" % (
            r["id"], r["order_no"], r["symbol"], r["order_side"],
            r["order_qty"], r["order_price"], r["order_amount"]))
