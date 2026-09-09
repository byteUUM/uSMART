# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\code-3")
from db import query, use_env
use_env("HK_SIT")

OID = 1150144597180882944
print("=== 订单 %s ===" % OID)
for r in query("""
select id, order_no, symbol, session_type, business_type, order_side, is_stop_out,
       entrust_type, order_qty, order_price, internal_status, before_operation_status,
       order_origin, transaction_passage, channel, capital_account,
       trade_date, create_time, update_time
from option_order_server.option_order where id = %s""", (OID,)):
    for k, v in r.items():
        print("  %-24s %s" % (k, v))

print("\n=== 该单下单时刻前后的盘前开关状态 ===")
print("下单时间见上; 看开关记录里离它最近的一次 action")
for r in query("""
select id, apply_id, action, operate_type, cancel_order_flag,
       operator_user_name, create_time, update_time
from option_order_server.option_premarket_switch_record
order by id desc limit 12"""):
    print("| id=%s applyId=%s action=%s(1开2关) operateType=%s(1提交2审核) cancelFlag=%s | %s | %s" % (
        r["id"], r["apply_id"], r["action"], r["operate_type"],
        r["cancel_order_flag"], r["operator_user_name"], r["create_time"]))

print("\n=== 找盘前开关'当前状态'存哪 (可能有独立的开关状态表/配置) ===")
for r in query("""
select TABLE_SCHEMA s, TABLE_NAME t from information_schema.tables
where TABLE_NAME like '%%premarket%%' order by 1,2"""):
    print("  %s.%s" % (r["s"], r["t"]))
