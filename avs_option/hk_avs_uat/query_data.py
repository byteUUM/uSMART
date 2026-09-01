"""
AVS 期权盘前 - 数据处理查询
============================
按订单号一次性查出 数据处理 涉及的 8 张表, 打印到控制台核对。
来源: AVS 期权盘前交易.xmind -> 订单管理 -> 数据处理

用法:
  1. 改下面的 ORDER_ID 为要查的订单号
  2. 运行: python query_data.py
     只看某几张表: python query_data.py order clinch capital
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.db import query

# ============================ 统一配置: 改这里 ============================
ORDER_ID = 1146772338964967424


# ============================ 查询定义 ============================
# key: 命令行可选的简写; (标题, SQL)
QUERIES = {
    # 一、订单表(主表): 下单新增, 成交后更新 clinch_* / internal_status
    "order": (
        "订单表 option_order",
        "select * from option_order_server.option_order where id = %(oid)s",
    ),
    # 二、成交流水: clinch_price / clinch_qty / clinch_amount
    "clinch": (
        "成交流水 option_order_clinch",
        "select * from option_order_server.option_order_clinch where order_id = %(oid)s",
    ),
    # 三、操作流水: 下单/改单/撤单每次操作一条; 改单看 target_* vs original_*
    "operation": (
        "操作流水 option_order_operation",
        "select * from option_order_server.option_order_operation where order_id = %(oid)s",
    ),
    # 四、持仓备份表(脑图"持仓表"): origin_order_id 指向 option_order.id
    "backup": (
        "持仓备份 option_order_backup",
        "select * from option_order_server.option_order_backup where origin_order_id = %(oid)s",
    ),
    # 五、资金表: 按 user_id(从订单表取). 关注 frozen_balance_business/fee_balance_business/
    #     real_buy_balance/real_sell_balance/process_margin_balance(沽空保证金)
    "capital": (
        "资金表 capital_account_sub_info",
        # 该表 user_id 存 user_uuid(长号); 一个客户有多个子账户, 用订单的 capital_account
        # 精确定位到本单使用的那个账户(hs_account = 订单表 capital_account)
        "select * from asset_center.capital_account_sub_info "
        "where user_id = (select user_uuid from option_order_server.option_order where id = %(oid)s) "
        "and hs_account = (select capital_account from option_order_server.option_order where id = %(oid)s)",
    ),
    # 六、资金流水: business_id = 订单号
    "capital_bill": (
        "资金流水 capital_account_bill_business",
        "select * from asset_center.capital_account_bill_business "
        "where business_id = %(oid)s order by created_time",
    ),
    # 七、资产持仓: 按 user_id + stock_code. 关注 current_num/frozen_num_business/
    #     real_buy_num/real_sell_num
    "hold": (
        "资产持仓 option_hold_info",
        # 注意: 该表 user_id 存的是订单表的 user_uuid(长号); code 存期权合约代码(=订单表 symbol)
        "select * from asset_center.option_hold_info "
        "where user_id = (select user_uuid from option_order_server.option_order where id = %(oid)s) "
        "and code = (select symbol from option_order_server.option_order where id = %(oid)s)",
    ),
    # 八、持仓流水: business_id = 订单号 (如无结果可改用 option_hold_id = 订单表 hold_id)
    "hold_bill": (
        "持仓流水 option_hold_bill_business",
        "select * from asset_center.option_hold_bill_business "
        "where business_id = %(oid)s order by created_time",
    ),
}


def print_rows(title, rows):
    print("\n" + "=" * 70)
    print("【%s】  命中 %d 条" % (title, len(rows)))
    print("=" * 70)
    if not rows:
        print("  (无数据)")
        return
    for i, row in enumerate(rows, 1):
        print("--- 第 %d 条 ---" % i)
        for k, v in row.items():
            if v is None or v == "":
                continue  # 空字段不打印, 输出更干净
            print("  %-26s %s" % (k, v))


def main():
    keys = sys.argv[1:] or list(QUERIES.keys())
    print("订单号:", ORDER_ID)
    for key in keys:
        if key not in QUERIES:
            print("未知查询:", key, " 可选:", ", ".join(QUERIES))
            continue
        title, sql = QUERIES[key]
        try:
            rows = query(sql, {"oid": ORDER_ID})
            print_rows(title, rows)
        except Exception as e:
            print("\n【%s】查询出错: %s: %s" % (title, type(e).__name__, e))


if __name__ == "__main__":
    main()
