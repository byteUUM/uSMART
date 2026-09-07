"""
期权持仓 冻结 / 解冻 测试 —— HK_SIT
=====================================
测的是中台运营手工冻结持仓的功能(不是资金冻结, 也不是下单时的业务冻结)。

接口:
  冻结  POST /stock-entrust-server/admin-api/admin-stock-stockFrozen-create
        body: {customerName, exchangeType, fundAccount, operateAmount,
               plannedUnfreezeTime, reason, stockCode, stockName, symbol}
  解冻  POST /stock-entrust-server/admin-api/admin-stock-stockFrozen-unfreeze
        body: {id}          <- id 是 stock_frozen 表的主键, 不是订单号

落库位置:
  冻结流水  stock_order_center.stock_frozen
            operate_type 冻结/解冻, status, freeze_time, unfreeze_time,
            planned_unfreeze_time, operate_amount
  持仓      asset_center.option_hold_info.frozen_num   <- 冻结数量应加到这里

覆盖场景:
  1. 做多持仓(hold_type=11, 账号 77000851)  冻结 -> 校验 -> 解冻 -> 校验
  2. 做空持仓(hold_type=12, 账号 S77000851) 冻结 -> 校验 -> 解冻 -> 校验
  3. 异常场景: 冻结数量超过持仓 / 重复解冻 / 解冻不存在的 id

用法:
  python frozen_test.py            # 全跑(做多 + 做空 + 异常)
  python frozen_test.py long
  python frozen_test.py short
  python frozen_test.py edge       # 只跑异常场景
  python frozen_test.py check      # 只看当前持仓和冻结流水
"""
import os
import sys
import time
import uuid
from decimal import Decimal

CUR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CUR)
sys.path.insert(0, r"d:\code-3")

import requests                                        # noqa: E402
from common.config import BASE_URL, COMMON_HEADERS     # noqa: E402
from db import query, use_env                          # noqa: E402

use_env("HK_SIT")

USER_UUID = 876169404924960768
CUSTOMER_NAME = "toothache"
PLANNED_UNFREEZE = "2026-09-08"

# exchange_type 按多空分开(从 stock_frozen 实际数据看出来的):
#   13 = 美股期权 普通账号(做多)      账号 77000851
#   14 = 美股期权 沽空账号(做空)      账号 S77000851
EX_TYPE_LONG = 13
EX_TYPE_SHORT = 14

FREEZE_URL = BASE_URL + "/stock-entrust-server/admin-api/admin-stock-stockFrozen-create"
UNFREEZE_URL = BASE_URL + "/stock-entrust-server/admin-api/admin-stock-stockFrozen-unfreeze"

# 挑 frozen_num 干净(=0)的持仓来测, 免得被历史残留干扰
LONG_ACCOUNT, LONG_CODE, LONG_EX = "77000851", "NVDA260918C15000", EX_TYPE_LONG
SHORT_ACCOUNT, SHORT_CODE, SHORT_EX = "S77000851", "NVDA260918P35000", EX_TYPE_SHORT


# ============================ 接口调用 ============================

def _headers():
    h = dict(COMMON_HEADERS)
    h["X-Request-Id"] = str(uuid.uuid4())
    h["Desensitization"] = "1"
    return h


def call(name, url, body):
    print("\n----- %s -----" % name)
    print("URL : %s" % url)
    print("body: %s" % body)
    try:
        r = requests.post(url, headers=_headers(), json=body, timeout=30)
    except requests.RequestException as e:
        print("请求异常:", e)
        return None
    print("HTTP: %s" % r.status_code)
    txt = r.content.decode("utf-8", "replace")
    print("resp: %s" % txt[:600])
    try:
        return r.json()
    except ValueError:
        return None


def freeze(fund_account, stock_code, amount, exchange_type=EX_TYPE_LONG,
           reason="自动化-冻结解冻测试"):
    body = {
        "customerName": CUSTOMER_NAME,
        "exchangeType": exchange_type,
        "fundAccount": fund_account,
        "operateAmount": str(amount),
        "plannedUnfreezeTime": PLANNED_UNFREEZE,
        "reason": reason,
        "stockCode": stock_code,
        "stockName": "",
        "symbol": "",
    }
    return call("冻结 %s %s x%s (exType=%s)" % (fund_account, stock_code, amount,
                                              exchange_type), FREEZE_URL, body)


def unfreeze(frozen_id):
    return call("解冻 id=%s" % frozen_id, UNFREEZE_URL, {"id": str(frozen_id)})


# ============================ 查库 ============================

def hold(code, fund_account):
    r = query("""
    select id, code, hold_type, fund_account, current_num, frozen_num,
           frozen_num_business, uncome_buy_num, uncome_sell_num,
           cost_price, hold_status, updated_time
    from asset_center.option_hold_info
    where user_id = %s and code = %s and fund_account = %s
    """, (USER_UUID, code, fund_account))
    return r[0] if r else None


def show_hold(code, fund_account, tag):
    h = hold(code, fund_account)
    print("   [持仓] %s  %s" % (tag, code))
    if not h:
        print("      (无持仓记录)")
        return None
    avail = (h["current_num"] or 0) - (h["frozen_num"] or 0) - (h["frozen_num_business"] or 0)
    print("      holdId=%s acct=%s type=%s | 持仓=%s 冻结=%s 业务冻结=%s 可用=%s | 更新 %s"
          % (h["id"], h["fund_account"], h["hold_type"], h["current_num"],
             h["frozen_num"], h["frozen_num_business"], avail, h["updated_time"]))
    return h


def frozen_rows(fund_account, stock_code, limit=10):
    return query("""
    select id, fund_account, fund_account_type, customer_name, operate_type,
           exchange_type, stock_code, operate_amount, reason, channel_name, seat_no,
           freeze_time, planned_unfreeze_time, unfreeze_time, status,
           create_time, update_time, create_user, update_user
    from stock_order_center.stock_frozen
    where fund_account = %s and stock_code = %s
    order by id desc limit %s
    """, (fund_account, stock_code, limit))


def show_frozen(fund_account, stock_code, tag, limit=5):
    print("   [stock_frozen] %s" % tag)
    rows = frozen_rows(fund_account, stock_code, limit)
    if not rows:
        print("      (无记录)")
    for r in rows:
        print("      | id=%s acct=%-10s %s x%-8s status=%s | 冻结时间=%s 计划解冻=%s 实际解冻=%s | %s/%s"
              % (r["id"], r["fund_account"], r["operate_type"], r["operate_amount"],
                 r["status"], r["freeze_time"], r["planned_unfreeze_time"],
                 r["unfreeze_time"], r["create_user"], r["update_user"]))
    return rows


def latest_frozen_id(fund_account, stock_code):
    rows = frozen_rows(fund_account, stock_code, 1)
    return rows[0]["id"] if rows else None


def check(label, expect, real, tol=Decimal("0.000001")):
    e, r = Decimal(str(expect)), Decimal(str(real))
    ok = abs(e - r) <= tol
    print("      [%s] %-22s 预期 %-16s 实际 %-16s" % ("OK" if ok else "!!", label, e, r))
    return ok


# ============================ 主流程 ============================

def run_one(tag, fund_account, code, exchange_type, amount=1):
    """一个方向的完整冻结->校验->解冻->校验"""
    print("\n" + "#" * 100)
    print("%s   账号=%s  标的=%s  exType=%s  冻结数量=%s"
          % (tag, fund_account, code, exchange_type, amount))
    print("#" * 100)

    print("\n[1] 冻结前基线")
    h0 = show_hold(code, fund_account, "冻结前")
    n0 = len(frozen_rows(fund_account, code, 50))
    show_frozen(fund_account, code, "冻结前的历史记录(共 %d 条)" % n0, 3)
    if not h0:
        print(">>> 没有持仓, 这个方向跳过")
        return None
    base_frozen = Decimal(str(h0["frozen_num"] or 0))
    is_short = h0["hold_type"] == 12

    print("\n[2] 调冻结接口")
    resp = freeze(fund_account, code, amount, exchange_type=exchange_type)
    ok = bool(resp) and resp.get("code") == 0
    if not ok:
        print(">>> 冻结接口未成功, 后续跳过")
        return None
    time.sleep(3)

    print("\n[3] 冻结后校验")
    h1 = show_hold(code, fund_account, "冻结后")
    rows = show_frozen(fund_account, code, "冻结后的流水", 3)
    n1 = len(frozen_rows(fund_account, code, 50))
    fid = rows[0]["id"] if rows else None
    print("   校验:")
    check("持仓 frozen_num", base_frozen + Decimal(str(amount)), h1["frozen_num"])
    check("持仓 current_num 不变", h0["current_num"], h1["current_num"])
    check("流水新增条数", n0 + 1, n1)
    if is_short:
        print("      [ ] 空头符号: current_num=%s  frozen_num=%s  "
              "(冻结量是正数, 持仓是负数, 口径要跟开发确认)"
              % (h1["current_num"], h1["frozen_num"]))
    if rows:
        r0 = rows[0]
        check("流水 operate_amount", amount, r0["operate_amount"])
        print("      [%s] %-22s %s" % (
            "OK" if r0["operate_type"] == "冻结" else "!!",
            "流水 operate_type", r0["operate_type"]))
        print("      [%s] %-22s status=%s unfreeze_time=%s" % (
            "OK" if r0["unfreeze_time"] is None else "!!",
            "冻结态未填解冻时间", r0["status"], r0["unfreeze_time"]))

    print("\n[4] 调解冻接口  id=%s" % fid)
    resp2 = unfreeze(fid)
    ok2 = bool(resp2) and resp2.get("code") == 0
    time.sleep(3)

    print("\n[5] 解冻后校验")
    h2 = show_hold(code, fund_account, "解冻后")
    rows2 = show_frozen(fund_account, code, "解冻后的流水", 4)
    n2 = len(frozen_rows(fund_account, code, 50))
    print("   校验:")
    check("持仓 frozen_num 回退", base_frozen, h2["frozen_num"])
    check("持仓 current_num 不变", h0["current_num"], h2["current_num"])
    print("      [ ] 流水条数: 冻结前 %d -> 冻结后 %d -> 解冻后 %d "
          "(解冻是原地改还是新增一条, 看这个)" % (n0, n1, n2))
    same = [x for x in rows2 if x["id"] == fid]
    if same:
        r1 = same[0]
        print("      [%s] %-22s %s" % (
            "OK" if r1["operate_type"] == "解冻" else "!!",
            "流水 operate_type 改为解冻", r1["operate_type"]))
        print("      [%s] %-22s %s" % (
            "OK" if r1["unfreeze_time"] else "!!",
            "回填 unfreeze_time", r1["unfreeze_time"]))
        print("      [ ] %-22s %s" % ("status", r1["status"]))
    return {"frozen_id": fid, "freeze_ok": ok, "unfreeze_ok": ok2,
            "hold_before": h0, "hold_frozen": h1, "hold_after": h2,
            "rows": (n0, n1, n2)}


def run_edge():
    """异常场景"""
    print("\n" + "#" * 100)
    print("异常场景")
    print("#" * 100)

    h = hold(LONG_CODE, LONG_ACCOUNT)
    cur = abs(Decimal(str(h["current_num"]))) if h else Decimal(0)

    print("\n[E1] 冻结数量超过持仓 (持仓 %s 张, 尝试冻 %s 张) —— 期望被拦" % (cur, cur + 100))
    freeze(LONG_ACCOUNT, LONG_CODE, int(cur + 100), exchange_type=LONG_EX,
           reason="边界-超量冻结")
    time.sleep(2)
    show_hold(LONG_CODE, LONG_ACCOUNT, "超量冻结尝试后(不该变)")

    print("\n[E2] 解冻一个不存在的 id —— 期望被拦")
    unfreeze("1111111111111111111")

    print("\n[E3] 冻结不存在持仓的标的 —— 期望被拦")
    freeze(LONG_ACCOUNT, "AAPL991231C999000", 1, exchange_type=LONG_EX,
           reason="边界-无持仓标的")

    print("\n[E4] 冻结 0 张 —— 期望被拦")
    freeze(LONG_ACCOUNT, LONG_CODE, 0, exchange_type=LONG_EX, reason="边界-零数量")

    print("\n[E6] 沽空账号用做多的 exType=13 冻结 —— 看是否校验账号与 exType 的匹配")
    freeze(SHORT_ACCOUNT, SHORT_CODE, 1, exchange_type=EX_TYPE_LONG,
           reason="边界-exType与账号不匹配")
    time.sleep(2)
    show_hold(SHORT_CODE, SHORT_ACCOUNT, "exType 不匹配尝试后(不该变)")

    # 累计超量: 分多次冻, 每次都不超持仓, 但累加起来超。
    # 这个场景怀疑是 NVDA261016C190000 出现 frozen_num 残留的成因。
    code = "NVDA261218C4000"      # 挑个 frozen_num=0 的多头, 别污染前面的用例
    print("\n[E7] 累计超量冻结: %s 分 3 次各冻满, 累计 3 倍持仓 —— 期望第 2 次起被拦" % code)
    h = hold(code, LONG_ACCOUNT)
    if not h:
        print("   无持仓, 跳过")
    else:
        qty = int(abs(Decimal(str(h["current_num"]))))
        show_hold(code, LONG_ACCOUNT, "累计冻结前")
        fids = []
        for i in range(1, 4):
            print("\n   --- 第 %d 次冻结 %s 张 ---" % (i, qty))
            r = freeze(LONG_ACCOUNT, code, qty, exchange_type=LONG_EX,
                       reason="边界-累计超量第%d次" % i)
            time.sleep(3)
            hh = show_hold(code, LONG_ACCOUNT, "第 %d 次冻结后" % i)
            if r and r.get("code") == 0:
                fid = latest_frozen_id(LONG_ACCOUNT, code)
                if fid not in fids:
                    fids.append(fid)
                print("      >>> 接口返回成功, frozen_num=%s (持仓只有 %s)"
                      % (hh["frozen_num"], hh["current_num"]))
            else:
                print("      >>> 被拦下了")
                break

        print("\n   累计冻结结果: frozen_num=%s, 持仓=%s, 产生 %d 条冻结记录 %s"
              % (hh["frozen_num"], hh["current_num"], len(fids), fids))
        if Decimal(str(hh["frozen_num"] or 0)) > abs(Decimal(str(hh["current_num"]))):
            print("   [!!] 冻结量已超过持仓量, 累计冻结没有上限校验")
        else:
            print("   [OK] 冻结量未超持仓")

        print("\n   --- 收尾: 把这几条都解冻 ---")
        for fid in fids:
            unfreeze(fid)
            time.sleep(2)
        show_hold(code, LONG_ACCOUNT, "全部解冻后(frozen_num 应回 0)")
        # 还有残留的话把该标的所有未解冻记录都列出来
        left = [r for r in frozen_rows(LONG_ACCOUNT, code, 20)
                if r["operate_type"] == "冻结"]
        if left:
            print("   仍是'冻结'状态的记录(可能解冻不到):")
            for r in left:
                print("      | id=%s x%s status=%s create=%s update=%s"
                      % (r["id"], r["operate_amount"], r["status"],
                         r["create_time"], r["update_time"]))

    print("\n[E5] 重复解冻同一条已解冻记录 —— 期望被拦")
    rows = [r for r in frozen_rows(LONG_ACCOUNT, LONG_CODE, 10)
            if r["operate_type"] == "解冻"]
    if rows:
        unfreeze(rows[0]["id"])
    else:
        print("   没有已解冻的记录, 跳过")


def run_effect():
    """
    冻结是否真的生效: 把持仓全部冻住, 再去卖出/平仓, 期望被"持仓不足"拦下。
    这是判断 frozen_num 只是记个数、还是真参与可用量校验的关键。
    多头: 冻满后 普通卖出(O/side=2)   期望被拦
    空头: 冻满后 买入平仓(OS/side=1)  期望被拦
    """
    from unified_orders.option_orders import build_option_body
    from common.client import send_order
    from common.config import (BUSINESS_TYPE_OPTION, BUSINESS_TYPE_OPTION_SHORT,
                               ORDER_TYPE_LIMIT, SESSION_TYPE_REGULAR,
                               SIDE_BUY, SIDE_SELL, url_for)

    print("\n" + "#" * 100)
    print("冻结生效性验证: 冻满持仓后再下平仓单, 期望被拦")
    print("#" * 100)

    cases = [
        ("多头 冻满后普通卖出", LONG_ACCOUNT, LONG_CODE, LONG_EX, 11,
         dict(side=SIDE_SELL, business_type=BUSINESS_TYPE_OPTION), 12.00),
        ("空头 冻满后买入平仓", SHORT_ACCOUNT, SHORT_CODE, SHORT_EX, 12,
         dict(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION_SHORT), 23.00),
    ]

    for tag, acct, code, ex, htype, order_kw, px in cases:
        print("\n" + "=" * 100)
        print(tag)
        print("=" * 100)
        h = hold(code, acct)
        if not h:
            print("   无持仓, 跳过")
            continue
        qty = abs(Decimal(str(h["current_num"])))
        already = Decimal(str(h["frozen_num"] or 0))
        need = qty - already
        print("   持仓 %s 张, 已冻 %s, 本次再冻 %s 张(冻满)" % (qty, already, need))

        fid = None
        if need > 0:
            r = freeze(acct, code, int(need), exchange_type=ex, reason="生效性验证-冻满")
            if not (r and r.get("code") == 0):
                print("   冻结失败, 跳过")
                continue
            time.sleep(3)
            fid = latest_frozen_id(acct, code)
        show_hold(code, acct, "冻满后")

        print("\n   [下单] 冻满状态下尝试平仓 1 张 —— 期望被拦")
        body = build_option_body(symbol=code, price=px, qty=1,
                                 order_type=ORDER_TYPE_LIMIT,
                                 session_type=SESSION_TYPE_REGULAR, **order_kw)
        resp = send_order("冻满后平仓 " + code, url_for("option_create"), body)
        blocked = True
        oid = None
        try:
            j = resp.json() if resp is not None else {}
        except ValueError:
            j = {}
        if j.get("code") == 0 and j.get("data"):
            blocked = False
            oid = int(j["data"])
        print("\n   结论: %s" % (
            "[OK] 被拦下了, 冻结参与了可用量校验" if blocked
            else "[!!] 没拦住! 下单成功 orderId=%s, 说明 frozen_num 没参与可用量校验" % oid))

        if oid:
            print("   >>> 把这笔意外下出去的单撤掉, 免得留脏数据")
            from unified_orders.option_orders import cancel_option
            cancel_option(oid, is_force_cancel=True)
            time.sleep(2)

        if fid:
            print("\n   [收尾] 解冻 id=%s" % fid)
            unfreeze(fid)
            time.sleep(3)
            show_hold(code, acct, "解冻后")


def run_check():
    print("=" * 100)
    print("当前持仓与冻结流水")
    print("=" * 100)
    for acct, code in ((LONG_ACCOUNT, LONG_CODE), (SHORT_ACCOUNT, SHORT_CODE)):
        show_hold(code, acct, "当前")
        show_frozen(acct, code, "历史冻结流水", 8)
        print()

    print("=" * 100)
    print("stock_frozen 表最近 12 条(全账号)")
    print("=" * 100)
    for r in query("""
    select id, fund_account, stock_code, operate_type, operate_amount, status,
           exchange_type, freeze_time, unfreeze_time, create_user
    from stock_order_center.stock_frozen order by id desc limit 12"""):
        print("| id=%s acct=%-10s %-18s %s x%-8s status=%s exType=%s | 冻=%s 解=%s | %s"
              % (r["id"], r["fund_account"], r["stock_code"], r["operate_type"],
                 r["operate_amount"], r["status"], r["exchange_type"],
                 r["freeze_time"], r["unfreeze_time"], r["create_user"]))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "check":
        run_check()
        sys.exit(0)

    results = {}
    if mode in ("all", "long"):
        results["做多"] = run_one("做多持仓 冻结/解冻", LONG_ACCOUNT, LONG_CODE,
                                LONG_EX, 1)
    if mode in ("all", "short"):
        results["做空"] = run_one("做空持仓 冻结/解冻", SHORT_ACCOUNT, SHORT_CODE,
                                SHORT_EX, 1)
    if mode in ("all", "effect"):
        run_effect()
    if mode in ("all", "edge"):
        run_edge()

    print("\n" + "=" * 100)
    print("小结")
    print("=" * 100)
    for k, v in results.items():
        if not v:
            print("  %s: 未完成(看上面日志)" % k)
        else:
            print("  %s: frozenId=%s 冻结接口=%s 解冻接口=%s"
                  % (k, v["frozen_id"],
                     "OK" if v["freeze_ok"] else "FAIL",
                     "OK" if v["unfreeze_ok"] else "FAIL"))
