"""
期权 今日成交/今日委托/历史成交/历史委托  数据与显示校验
========================================================
针对四个 tab，做三层校验（重点：字段显示↔DB、接口返回、查询功能）：

  A. 接口 <-> 页面渲染一致性
     接口返回每一行的字段值，翻译成"应显示文本"后，与表格实际渲染文本逐列比对。
     能测出：前端字段错位、该显示却空着、枚举翻译错误等显示 bug。

  B. 接口 <-> 数据库一致性
     用接口返回的 orderId 去 DB(实时表/历史归档表) 精确核对关键字段值。
     能测出：页面/接口显示的值与库里不符。

  C. 查询功能
     填证券代码 / 选买卖方向 等条件后搜索，校验：
       - 请求入参确实带上了筛选条件
       - 返回结果确实符合筛选（如证券代码全部匹配、买卖方向全部一致）

  D. 可交互元素
     导出按钮存在性、分页每页条数切换、下一页翻页是否生效。

差异若无法判定对错（如总数口径），记为 WARN 并截图留证，交人工确认，不直接判失败。

运行前置：先执行 save_login.py 生成 auth_state.json。
运行方式：python test_option_data_verify.py
"""
import sys

from playwright.sync_api import sync_playwright

import config
import db_verify
from field_mapping import (
    DEAL_COLUMN_TO_API,
    ENTRUST_COLUMN_TO_API,
    api_expected_text,
)
from pages import ClientHomePage


class Report:
    def __init__(self):
        self.items = []  # (level, name, ok, detail)  level: CHECK/WARN
        self.bug_shots = []

    def check(self, name, ok, detail=""):
        self.items.append(("CHECK", name, bool(ok), detail))
        print(f"[{'通过' if ok else '失败'}] {name}" + (f"  -> {detail}" if detail else ""))

    def warn(self, name, detail=""):
        self.items.append(("WARN", name, None, detail))
        print(f"[告警] {name}" + (f"  -> {detail}" if detail else ""))

    def add_bug_shot(self, path):
        self.bug_shots.append(path)

    def summary(self):
        checks = [i for i in self.items if i[0] == "CHECK"]
        passed = sum(1 for i in checks if i[2])
        warns = [i for i in self.items if i[0] == "WARN"]
        print("\n" + "=" * 66)
        print(f"校验完成：CHECK 通过 {passed}/{len(checks)}，告警 {len(warns)} 项")
        fails = [i for i in checks if not i[2]]
        if fails:
            print("\n-- 失败项(疑似BUG) --")
            for _, name, _, detail in fails:
                print(f"  × {name}  {detail}")
        if warns:
            print("\n-- 告警项(待人工确认) --")
            for _, name, _, detail in warns:
                print(f"  ! {name}  {detail}")
        if self.bug_shots:
            print("\n-- BUG 截图证据 --")
            for s in self.bug_shots:
                print(f"  {s}")
        print("=" * 66)
        return len(fails) == 0


def verify_render_vs_api(home, rpt, tab_name, mapping):
    """A. 接口返回 <-> 页面渲染 逐列比对。返回接口 list 供后续用。"""
    data = home.get_last_list_data()
    api_list = data.get("list", [])
    rows = home.get_row_dicts()

    if not api_list:
        rpt.warn(f"[{tab_name}] 接口无数据，跳过渲染比对", f"total={data.get('total')}")
        return api_list

    # 逐列统计不匹配
    n = min(len(api_list), len(rows))
    col_mismatch = {}  # 列 -> [(orderNo, api文本, 页面文本)]
    for i in range(n):
        api_row = api_list[i]
        page_row = rows[i]
        order_no = str(api_row.get("orderNo", ""))
        for col in mapping:
            expected = api_expected_text(col, api_row, mapping)
            if expected is None:
                continue
            actual = page_row.get(col, "")
            # 数值容错：0.10 vs 0.1
            if _num_eq(expected, actual):
                continue
            # 文本容错：中英文括号/全半角/空白统一后再比
            if _norm(expected) != _norm(actual):
                col_mismatch.setdefault(col, []).append((order_no, expected, actual))

    # 每列单独给结论
    for col in mapping:
        bad = col_mismatch.get(col, [])
        if not bad:
            rpt.check(f"[{tab_name}] 列「{col}」接口↔页面一致", True, f"{n}行全部一致")
        else:
            sample = bad[0]
            detail = f"{len(bad)}/{n}行不一致，例: 委托{sample[0]} 接口='{sample[1]}' 页面='{sample[2]}'"
            rpt.check(f"[{tab_name}] 列「{col}」接口↔页面一致", False, detail)
            shot = home.screenshot(f"bug_{tab_name}_{col}_mismatch.png")
            rpt.add_bug_shot(shot)
    return api_list


def verify_api_vs_db(home, rpt, tab_name, api_list, is_deal):
    """B. 接口返回 <-> DB 精确比对（抽查前若干条）。"""
    if not api_list:
        return
    sample = api_list[:5]
    mismatches = []
    checked = 0
    for row in sample:
        oid = row.get("orderId")
        db_row = db_verify.get_order(oid)
        if not db_row:
            mismatches.append(f"orderId={oid} 在DB订单表(实时+历史)均查不到")
            continue
        checked += 1
        # 核对关键字段：证券代码、委托数量、委托价格、买卖方向
        pairs = [
            ("optionCode", "symbol", row.get("optionCode"), db_row.get("symbol")),
            ("orderSide", "order_side", row.get("orderSide"), db_row.get("order_side")),
            ("orderQty", "order_qty", row.get("orderQty"), db_row.get("order_qty")),
            ("orderPrice", "order_price", row.get("orderPrice"), db_row.get("order_price")),
        ]
        for af, dbf, av, dv in pairs:
            if not _loose_eq(av, dv):
                mismatches.append(f"orderId={oid} {af}={av} vs DB.{dbf}={dv}")

        # 成交类额外核对成交量/价
        if is_deal:
            clinch = db_verify.get_clinch(oid)
            if clinch:
                # 接口该行 clinchQty/clinchAvgPrice 与 DB 成交流水核对（订单级汇总或单笔）
                total_qty = sum(float(c["clinch_qty"]) for c in clinch)
                if not _loose_eq(row.get("clinchQty"), total_qty) and \
                   not any(_loose_eq(row.get("clinchQty"), c["clinch_qty"]) for c in clinch):
                    mismatches.append(f"orderId={oid} clinchQty={row.get('clinchQty')} 与DB成交流水({[str(c['clinch_qty']) for c in clinch]})对不上")

    if not mismatches:
        rpt.check(f"[{tab_name}] 接口↔DB 抽查关键字段一致", True, f"抽查{checked}条订单")
    else:
        rpt.check(f"[{tab_name}] 接口↔DB 抽查关键字段一致", False, "; ".join(mismatches[:3]))
        shot = home.screenshot(f"bug_{tab_name}_db_mismatch.png")
        rpt.add_bug_shot(shot)


def verify_total_vs_db(home, rpt, tab_name, realtime, is_deal):
    """总数 页面 vs DB，作为告警（口径可能不同）。"""
    data = home.get_last_list_data()
    page_total = int(data.get("total") or 0)
    if is_deal:
        db_cnt = db_verify.count_clinch(realtime)
        src = "option_order_clinch" + ("" if realtime else "_history")
    else:
        db_cnt = db_verify.count_orders(realtime)
        src = "option_order" + ("" if realtime else "_history")
    if page_total == db_cnt:
        rpt.check(f"[{tab_name}] 总数 页面={page_total} 与 DB({src})={db_cnt} 一致", True)
    else:
        rpt.warn(f"[{tab_name}] 总数不一致(口径待确认)",
                 f"页面={page_total} vs DB {src}={db_cnt}")
        shot = home.screenshot(f"warn_{tab_name}_total_diff.png")
        rpt.add_bug_shot(shot)


def verify_query_by_code(home, rpt, tab_name):
    """C. 查询功能：用页面上已有的一个证券代码去搜，校验结果被正确过滤。"""
    rows = home.get_row_dicts()
    if not rows:
        rpt.warn(f"[{tab_name}] 无数据，跳过查询功能校验")
        return
    # 取第一行的证券代码作为查询值
    code = rows[0].get("证券代码", "").strip()
    if not code:
        rpt.warn(f"[{tab_name}] 首行无证券代码，跳过查询校验")
        return
    home.fill_search_input("证券代码", code)
    home.click_search()
    body = home.get_last_list_body()
    # 校验1：请求入参带上了 optionCode
    param_ok = code in (body or "")
    rpt.check(f"[{tab_name}] 查询-证券代码 入参已带上", param_ok, f"code={code}")
    # 校验2：返回结果证券代码全部匹配
    new_rows = home.get_row_dicts()
    all_match = all(r.get("证券代码", "").strip() == code for r in new_rows) if new_rows else False
    rpt.check(f"[{tab_name}] 查询-证券代码 结果全部匹配", all_match,
              f"返回{len(new_rows)}行" + ("" if all_match else "，存在不匹配行"))
    if not all_match and new_rows:
        shot = home.screenshot(f"bug_{tab_name}_query_code.png")
        rpt.add_bug_shot(shot)
    # 复位
    home.click_reset()
    home.click_search()


def verify_query_by_side(home, rpt, tab_name):
    """C2. 查询功能：用「买卖方向」下拉筛选，校验结果买卖方向全部一致。"""
    # 先看全量数据里是否同时存在买入/卖出，挑一个存在的方向来筛
    rows = home.get_row_dicts()
    if not rows:
        rpt.warn(f"[{tab_name}] 无数据，跳过买卖方向查询校验")
        return
    sides = [r.get("买卖方向", "").strip() for r in rows]
    target = None
    for s in ("买入", "卖出"):
        if s in sides:
            target = s
            break
    if not target:
        rpt.warn(f"[{tab_name}] 首页无可识别买卖方向，跳过", f"sides={set(sides)}")
        return

    ok = home.select_dropdown("买卖方向", target)
    home.click_search()
    new_rows = home.get_row_dicts()
    if not new_rows:
        rpt.warn(f"[{tab_name}] 买卖方向={target} 查询无结果，跳过一致性判断")
    else:
        all_match = all(r.get("买卖方向", "").strip() == target for r in new_rows)
        rpt.check(f"[{tab_name}] 查询-买卖方向={target} 结果全部一致", all_match,
                  f"返回{len(new_rows)}行" + ("" if all_match else "，存在不一致行"))
        if not all_match:
            shot = home.screenshot(f"bug_{tab_name}_query_side.png")
            rpt.add_bug_shot(shot)
    home.click_reset()
    home.click_search()


def verify_pagination(home, rpt, tab_name):
    """D2. 分页：切换每页条数、翻下一页，校验行数/页码/接口入参随之变化。"""
    data = home.get_last_list_data()
    total = int(data.get("total") or 0)
    if total <= 20:
        rpt.warn(f"[{tab_name}] 总数{total}≤20，分页样本不足，跳过分页校验")
        return

    # 该分页每页可选项为 20/30/50。切每页 30：本页行数应为 min(30, total)
    if home.set_page_size(30):
        rows30 = home.get_visible_row_count()
        expect30 = min(30, total)
        rpt.check(f"[{tab_name}] 每页条数=30 生效", rows30 == expect30,
                  f"本页{rows30}行, 期望{expect30}")
    else:
        rpt.warn(f"[{tab_name}] 切换每页30条未触发接口")

    # 复位每页 20，再翻下一页：页码应变为 2，且接口 pageNum=2
    home.set_page_size(20)
    if home.go_to_next_page():
        body = home.get_last_list_body() or ""
        page_num = home.get_current_page_num()
        param_ok = '"pageNum":2' in body.replace(" ", "")
        rpt.check(f"[{tab_name}] 翻页到第2页 生效", page_num == 2 and param_ok,
                  f"页码={page_num}, 接口pageNum=2:{param_ok}")
        home.set_page_size(20)


def _num_eq(a, b):
    try:
        return abs(float(str(a).replace(",", "")) - float(str(b).replace(",", ""))) < 1e-6
    except (ValueError, TypeError):
        return False


def _norm(s):
    """文本归一：统一中英文括号、全半角、去空白，用于宽松文本比对。"""
    s = str(s)
    trans = {"（": "(", "）": ")", "，": ",", "：": ":"}
    for k, v in trans.items():
        s = s.replace(k, v)
    return s.replace(" ", "").replace("\u3000", "").strip()


def _loose_eq(a, b):
    """宽松相等：数值按数值比，否则按去空白字符串比。"""
    if a is None and b is None:
        return True
    if _num_eq(a, b):
        return True
    return str(a).strip() == str(b).strip()


def run():
    rpt = Report()
    # tab -> (是否成交类, 映射, DB是否实时表)
    tabs = [
        ("今日成交", True, DEAL_COLUMN_TO_API, True),
        ("今日委托", False, ENTRUST_COLUMN_TO_API, True),
        ("历史成交", True, DEAL_COLUMN_TO_API, False),
        ("历史委托", False, ENTRUST_COLUMN_TO_API, False),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        context = browser.new_context(
            storage_state=str(config.AUTH_STATE_FILE),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        home = ClientHomePage(page)

        home.open()
        home.lock_client_by_fund_account(config.FUND_ACCOUNT)
        home.go_to_trade_records()
        home.go_to_option()
        page.wait_for_timeout(2000)

        for tab_name, is_deal, mapping, realtime in tabs:
            print("\n" + "#" * 66)
            print(f"# TAB: {tab_name}")
            print("#" * 66)
            home.clear_last_list()
            home.switch_option_subtab(tab_name)
            page.wait_for_timeout(1500)
            # 统一主动点一次搜索，确保拿到当前 tab 的列表接口数据（切到已激活 tab 不会自动发请求）
            home.click_search()
            page.wait_for_timeout(1000)
            if not home.get_last_list_data().get("list"):
                # 再等一次接口
                home._wait_list_response(6000)

            # A. 接口<->页面渲染
            api_list = verify_render_vs_api(home, rpt, tab_name, mapping)
            # B. 接口<->DB
            verify_api_vs_db(home, rpt, tab_name, api_list, is_deal)
            # 总数 vs DB（告警）
            verify_total_vs_db(home, rpt, tab_name, realtime, is_deal)
            # D. 导出按钮
            rpt.check(f"[{tab_name}] 存在导出按钮", home.has_export_button())
            # D2. 分页（切每页条数 + 翻页）
            verify_pagination(home, rpt, tab_name)
            # C. 查询功能：证券代码
            verify_query_by_code(home, rpt, tab_name)
            # C2. 查询功能：买卖方向
            verify_query_by_side(home, rpt, tab_name)

        browser.close()

    return rpt.summary()


if __name__ == "__main__":
    if not config.AUTH_STATE_FILE.exists():
        print("未找到登录态 auth_state.json，请先运行：python save_login.py")
        sys.exit(1)
    ok = run()
    sys.exit(0 if ok else 1)
