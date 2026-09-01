"""
AVS 期权盘前 - 数据处理 自动化测试编排
========================================
串起三个环节, 覆盖脑图"订单管理 -> 数据处理"的 买入/卖出/沽空/买入平仓:
  1. 下单        调用 option_orders 里的下单函数, 拿 orderId
  2. mock 成交   调 mock 平台 triggerMock 把订单改成全部成交
  3. 勾稽校验    查库核对 订单表/成交流水/资金流水/持仓流水 是否自洽

用法:
  python run_data_test.py buy         # 买入方向 全流程
  python run_data_test.py check <id>  # 只对已有订单号做勾稽校验
"""
import os
import sys
import time
import json
from decimal import Decimal

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.db import query
from unified_orders.option_orders import (
    create_option_buy, create_option_sell, create_option_short, order_id_of,
)

MOCK_URL = "http://10.60.6.93:8020/deal_mock/"


# ============================ mock 成交 ============================

def mock_fill(order_id, position="long", mock_type="3"):
    """调 mock 平台把订单改成指定状态(默认3=全成)。position: long买入方向/short卖出方向。"""
    base = {
        "orderId": str(order_id), "accountType": "option", "environment": "UAT",
        "market": "HK", "orderType": "com", "position": position,
    }
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": MOCK_URL})
    # 查可用类型, 取目标 mockType 的 price/qty
    q = s.post(MOCK_URL, data=dict(base, operationType="queryMockTypes"), timeout=20)
    info = None
    try:
        data = json.loads(q.text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and str(item.get("mockType")) == str(mock_type):
                    info = item
                    break
    except ValueError:
        pass
    if not info:
        # 返回不是数组(通常是错误 msg), 原样打印
        print("  [mock] queryMockTypes 未返回 mockType=%s, 响应: %s" % (mock_type, q.text[:200]))
        return False
    form = dict(base, operationType="triggerMock", mockType=mock_type,
                mockPrice=info.get("price", ""), dealAmount=info.get("qty", ""), phone="")
    r = s.post(MOCK_URL, data=form, timeout=20)
    msg = ""
    try:
        msg = r.json().get("msg", "")
    except ValueError:
        msg = r.text
    print("  [mock] triggerMock mockType=%s price=%s qty=%s -> %s"
          % (mock_type, info.get("price"), info.get("qty"), msg))
    return r.status_code == 200 and ("成功" in msg) and ("失败" not in msg)


# ============================ 查库 ============================

def get_order(oid):
    r = query("select * from option_order_server.option_order where id=%(o)s", {"o": oid})
    return r[0] if r else None

def get_clinch(oid):
    return query("select * from option_order_server.option_order_clinch where order_id=%(o)s", {"o": oid})

def get_capital_bill(oid):
    return query("select operation_type, amount, trade_action, modify_before, modify_after "
                 "from asset_center.capital_account_bill_business where business_id=%(o)s "
                 "order by created_time", {"o": oid})

def get_hold_bill(oid):
    return query("select operation_type, num, field_type, modify_before, modify_after "
                 "from asset_center.option_hold_bill_business where business_id=%(o)s "
                 "order by created_time", {"o": oid})


# ============================ 勾稽校验 ============================

def reconcile(oid, direction):
    """对订单做跨表勾稽, 打印结果并返回疑点列表。direction 用于场景化判断。"""
    print("\n" + "-" * 80)
    print("勾稽校验 订单 %s  [%s]" % (oid, direction))
    o = get_order(oid)
    if not o:
        print("  订单不存在")
        return ["订单不存在"]
    side, biz = o["order_side"], o["business_type"]
    oq, op, cq, ca = o["order_qty"], o["order_price"], o["clinch_qty"], o["clinch_amount"]
    mult = o["contract_multiplier"]
    st = o["internal_status"]
    print("  状态=%s 方向=%s(1买2卖) 业务=%s 委托%s@%s 成交%s 金额=%s 乘数=%s"
          % (st, side, biz, oq, op, cq, ca, mult))

    issues = []
    cl = get_clinch(oid)
    cb = get_capital_bill(oid)
    hb = get_hold_bill(oid)
    print("  成交流水 %d 条 | 资金流水 %d 条 %s | 持仓流水 %d 条 %s"
          % (len(cl), len(cb), [(x["operation_type"], str(x["amount"])) for x in cb],
             len(hb), [(x["operation_type"], str(x["num"])) for x in hb]))

    # 1) 成交金额勾稽: 价*量*乘数=金额, 流水合计=订单成交
    if cq and cq > 0:
        sq = sum([c["clinch_qty"] for c in cl], Decimal(0))
        sa = sum([c["clinch_amount"] for c in cl], Decimal(0))
        if sq != cq:
            issues.append("成交流水数量合计%s≠订单clinch_qty%s" % (sq, cq))
        if sa != ca:
            issues.append("成交流水金额合计%s≠订单clinch_amount%s" % (sa, ca))
        for c in cl:
            exp = c["clinch_price"] * c["clinch_qty"] * mult
            if exp != c["clinch_amount"]:
                issues.append("成交流水价*量*乘数%s≠金额%s" % (exp, c["clinch_amount"]))

    # 2) 全成后应有的流水
    if st == 810 and cq and cq > 0:
        ops_c = [x["operation_type"] for x in cb]
        ops_h = [x["operation_type"] for x in hb]
        if side == 1:  # 买入/买入平仓: 资金扣款 + 持仓入账
            if not cb: issues.append("买入全成但无资金流水")
            if 40 not in ops_h: issues.append("买入全成持仓流水无入账(op=40)")
        elif side == 2:  # 卖出/沽空: 持仓交割 + 资金入账
            if not hb: issues.append("卖出全成但无持仓流水")

    if issues:
        print("  >>> 疑点:")
        for x in issues:
            print("      - " + x)
    else:
        print("  >>> 勾稽一致")
    return issues


# ============================ 各方向全流程 ============================

def flow_buy():
    print("\n########## 买入方向 ##########")
    print("[1] 下单")
    oid = order_id_of(create_option_buy())
    if not oid:
        print(">>> 下单未成功, 终止"); return None
    print("orderId =", oid)
    print("[2] 下单后查库(未成交, 应有冻结)")
    reconcile(oid, "买入-下单后")
    print("[3] mock 全部成交")
    if not mock_fill(oid, position="long"):
        print(">>> mock 未成功"); return oid
    time.sleep(3)
    print("[4] 成交后勾稽")
    reconcile(oid, "买入-成交后")
    return oid


def flow_sell():
    print("\n########## 卖出方向 (需该标的有持仓) ##########")
    print("[1] 下单")
    oid = order_id_of(create_option_sell())
    if not oid:
        print(">>> 下单未成功(可能无持仓), 终止"); return None
    print("orderId =", oid)
    print("[2] 下单后查库(应有持仓冻结)")
    reconcile(oid, "卖出-下单后")
    print("[3] mock 全部成交")
    # 普通期权卖出是平多头, 持仓方向仍为 long(short 仅用于沽空 OS)
    if not mock_fill(oid, position="long"):
        print(">>> mock 未成功"); return oid
    time.sleep(3)
    print("[4] 成交后勾稽")
    reconcile(oid, "卖出-成交后")
    return oid


def flow_short():
    print("\n########## 沽空方向 (businessType=OS, 需沽空权限) ##########")
    print("[1] 下单")
    oid = order_id_of(create_option_short())
    if not oid:
        print(">>> 下单未成功(可能无沽空权限), 终止"); return None
    print("orderId =", oid)
    print("[2] 下单后查库")
    reconcile(oid, "沽空-下单后")
    print("[3] mock 全部成交")
    if not mock_fill(oid, position="short"):
        print(">>> mock 未成功"); return oid
    time.sleep(3)
    print("[4] 成交后勾稽")
    reconcile(oid, "沽空-成交后")
    return oid


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "buy"
    if arg == "check" and len(sys.argv) > 2:
        reconcile(int(sys.argv[2]), "手工校验")
    elif arg == "buy":
        flow_buy()
    elif arg == "sell":
        flow_sell()
    elif arg == "short":
        flow_short()
    else:
        print("用法: python run_data_test.py buy|sell|short | check <orderId>")
