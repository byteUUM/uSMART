"""
客户首页 -> 交易记录 -> 期权  前端显示 UI 自动化测试
====================================================
校验内容（前端显示正确性）：
  1. 登录态有效，客户首页正常打开（未被踢回登录页）
  2. 用资金账号 77000851 能锁定客户，基本信息正确显示（客户姓名、美股期权账户）
  3. 能进入「交易记录 -> 期权」，默认「今日成交」子 tab 正常显示
  4. 期权成交表格表头列完整（17 列）
  5. 统计文本「当前查询条件下有 N 笔」与底部「共 N 条」一致
  6. 首页表格实际行数与统计数字 / 分页大小逻辑一致
  7. 期权下各二级子 tab（今日成交/今日委托/历史成交/历史委托/智能订单）均可切换且正常渲染

运行前置：先执行 save_login.py 生成 auth_state.json。
运行方式：python test_option_trade_records.py
"""
import sys

from playwright.sync_api import sync_playwright

import config
from pages import ClientHomePage

# 期权成交表格期望的表头列（来自真实页面探查）
EXPECTED_HEADERS = [
    "委托ID", "成交时间", "下单时间", "市场", "币种", "交易时段",
    "证券名称", "证券代码", "业务类型", "买卖方向", "委托方式",
    "委托属性", "成交数量", "成交价格", "成交金额", "交易通道", "强制平仓",
]

# 期权下需要逐个切换校验的二级子 tab
OPTION_SUBTABS = ["今日成交", "今日委托", "历史成交", "历史委托", "智能订单"]


class Report:
    """简单的用例结果收集器。"""

    def __init__(self):
        self.items = []  # (name, ok, detail)

    def check(self, name, ok, detail=""):
        self.items.append((name, bool(ok), detail))
        flag = "通过" if ok else "失败"
        print(f"[{flag}] {name}" + (f"  -> {detail}" if detail else ""))

    def summary(self):
        passed = sum(1 for _, ok, _ in self.items if ok)
        total = len(self.items)
        print("\n" + "=" * 60)
        print(f"校验完成：通过 {passed}/{total}")
        if passed != total:
            print("失败项：")
            for name, ok, detail in self.items:
                if not ok:
                    print(f"  - {name}  {detail}")
        print("=" * 60)
        return passed == total


def run():
    rpt = Report()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.HEADLESS)
        context = browser.new_context(
            storage_state=str(config.AUTH_STATE_FILE),
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()
        home = ClientHomePage(page)

        # --- 1. 打开首页 & 登录态 ---
        try:
            home.open()
            rpt.check("1. 客户首页正常打开（登录态有效）", True, page.url)
        except Exception as e:
            rpt.check("1. 客户首页正常打开（登录态有效）", False, str(e))
            browser.close()
            return rpt.summary()

        # --- 2. 锁定客户 ---
        try:
            home.lock_client_by_fund_account(config.FUND_ACCOUNT)
            client_name = home.get_client_name()
            option_acc = home.get_option_account()
            # 客户姓名非空且不再是占位 --
            name_ok = bool(client_name) and "--" not in client_name
            rpt.check(f"2.1 资金账号 {config.FUND_ACCOUNT} 锁定客户，客户姓名显示正确",
                      name_ok, client_name)
            # 美股期权账户应包含所填资金账号
            acc_ok = config.FUND_ACCOUNT in option_acc
            rpt.check("2.2 基本信息中美股期权账户与资金账号一致",
                      acc_ok, option_acc)
            home.screenshot("01_client_locked.png")
        except Exception as e:
            rpt.check("2. 锁定客户", False, str(e))
            browser.close()
            return rpt.summary()

        # --- 3. 进入 交易记录 -> 期权 ---
        try:
            home.go_to_trade_records()
            home.go_to_option()
            headers = home.get_table_headers()
            rpt.check("3. 进入交易记录-期权，表格正常渲染", len(headers) > 0,
                      f"读到 {len(headers)} 个表头列")
            home.screenshot("02_option_today_deal.png")
        except Exception as e:
            rpt.check("3. 进入交易记录-期权", False, str(e))
            browser.close()
            return rpt.summary()

        # --- 4. 表头列完整性 ---
        missing = [h for h in EXPECTED_HEADERS if h not in headers]
        rpt.check("4. 期权成交表头列完整（17列）", len(missing) == 0,
                  f"表头={headers}" if missing else f"共{len(headers)}列全部存在")

        # --- 5. 统计文本 与 分页总数 一致 ---
        stat_total = home.get_stat_total()
        page_total = home.get_pagination_total()
        page_size = home.get_page_size()
        rpt.check("5.1 能读到统计「当前查询条件下有 N 笔」", stat_total >= 0,
                  f"N={stat_total}")
        rpt.check("5.2 能读到分页「共 N 条」", page_total >= 0, f"N={page_total}")
        if stat_total >= 0 and page_total >= 0:
            rpt.check("5.3 统计笔数与分页总数一致", stat_total == page_total,
                      f"统计={stat_total} 分页={page_total}")

        # --- 6. 首页行数 与 统计/分页逻辑一致 ---
        row_count = home.get_visible_row_count()
        if page_total >= 0 and page_size > 0:
            expected_first_page = min(page_total, page_size)
            rpt.check("6. 首页表格行数与总数/分页大小一致",
                      row_count == expected_first_page,
                      f"实际首页行数={row_count} 期望={expected_first_page}"
                      f"（总数={page_total} 每页={page_size}）")
        else:
            rpt.check("6. 首页表格行数", row_count >= 0, f"行数={row_count}")

        # --- 7. 逐个切换期权二级子 tab ---
        # 判定标准：子 tab 能被成功切换（进入激活态）。
        # 表头列数 / 共 N 条 作为附加信息展示——「智能订单」本身无列表结构属正常。
        for tab in OPTION_SUBTABS:
            try:
                home.switch_option_subtab(tab)
                active = home.is_option_subtab_active(tab)
                headers_t = home.get_table_headers()
                total_t = home.get_pagination_total()
                detail = f"激活={active} 表头列数={len(headers_t)} 共{total_t}条"
                rpt.check(f"7. 期权子tab「{tab}」可切换并正常显示", active, detail)
                home.screenshot(f"03_option_{tab}.png")
            except Exception as e:
                rpt.check(f"7. 期权子tab「{tab}」可切换并正常显示", False, str(e))

        browser.close()

    return rpt.summary()


if __name__ == "__main__":
    if not config.AUTH_STATE_FILE.exists():
        print("未找到登录态文件 auth_state.json，请先运行：python save_login.py")
        sys.exit(1)
    ok = run()
    sys.exit(0 if ok else 1)
