"""
页面操作封装
============
把「打开首页 / 锁定客户 / 进入交易记录-期权 / 读取表格数据」等操作封装成方法，
供测试用例调用。选择器与交互流程均来自对 SIT 环境真实页面的探查。
"""
import re
import time

from playwright.sync_api import Page

import config


class ClientHomePage:
    """客户首页 -> 交易记录 -> 期权 页面对象。"""

    def __init__(self, page: Page):
        self.page = page

    # ---------------------------- 打开与登录态 ----------------------------
    def open(self):
        """打开客户首页。若登录态失效会被重定向到 CAS 登录页，这里做检测。"""
        self.page.goto(config.CLIENT_FIRST_PAGE, wait_until="domcontentloaded", timeout=config.DEFAULT_TIMEOUT)
        # 等待 SPA 首页渲染
        self.page.wait_for_timeout(6000)
        url = self.page.url or ""
        if "/login" in url or "service=" in url:
            raise RuntimeError(
                "登录态已失效（被重定向到统一认证登录页）。请重新运行 save_login.py 保存登录态后再试。"
            )

    # ---------------------------- 锁定客户 ----------------------------
    def lock_client_by_fund_account(self, fund_account: str):
        """
        通过资金账号锁定当前客户：
        顶部下拉切到「资金账号」-> 逐字输入账号触发自动补全 -> 点击第一条候选。
        """
        # 1) 顶部客户类型下拉
        self.page.locator("input[placeholder='请选择']").first.click()
        self.page.wait_for_timeout(500)
        self.page.locator(".el-select-dropdown__item", has_text="资金账号").first.click()
        self.page.wait_for_timeout(500)

        # 2) 逐字输入（fill 不会触发 el-autocomplete，必须用 type）
        inp = self.page.locator("input[placeholder='请输入']").first
        inp.click()
        inp.type(fund_account, delay=100)

        # 3) 等待自动补全候选出现、渲染稳定
        suggestion = self.page.locator(".el-autocomplete-suggestion__list li").first
        suggestion.wait_for(state="visible", timeout=config.DEFAULT_TIMEOUT)
        self.page.wait_for_timeout(1000)  # 等候选列表渲染稳定

        # 4) 选择候选并等待基本信息加载。el-autocomplete 的选中比较"挑"，
        #    这里用多种方式轮流尝试，直到客户姓名不再是占位 -- 为止。
        def is_loaded():
            name = self.get_client_name()
            return bool(name) and "--" not in name

        select_actions = [
            # 键盘：方向键高亮第一条 + 回车
            lambda: (inp.press("ArrowDown"), self.page.wait_for_timeout(300), inp.press("Enter")),
            # JS 直接触发第一条候选的点击
            lambda: self.page.evaluate(
                """() => { const li=document.querySelector('.el-autocomplete-suggestion__list li'); if(li){li.click();return true;} return false; }"""
            ),
            # 鼠标按坐标点候选中心
            lambda: self._click_first_suggestion_by_mouse(),
        ]

        loaded = False
        for action in select_actions:
            try:
                action()
            except Exception:
                pass
            # 每次动作后轮询等待最多约 6 秒
            for _ in range(8):
                self.page.wait_for_timeout(800)
                if is_loaded():
                    loaded = True
                    break
            if loaded:
                break
            # 未成功则确保候选还在（可能已被上一步动作关闭），重新触发
            if self.page.locator(".el-autocomplete-suggestion__list li").count() == 0:
                inp.click()
                inp.fill("")
                inp.type(fund_account, delay=100)
                try:
                    suggestion.wait_for(state="visible", timeout=8000)
                    self.page.wait_for_timeout(800)
                except Exception:
                    pass

        if not loaded:
            self.screenshot("debug_lock_failed.png")
            raise RuntimeError(
                f"点击候选后客户基本信息未加载（客户姓名读到: '{self.get_client_name()}'）"
            )

    def _click_first_suggestion_by_mouse(self):
        """按坐标点击第一条候选项中心。"""
        li = self.page.locator(".el-autocomplete-suggestion__list li").first
        box = li.bounding_box()
        if box:
            self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

    def _extract_field(self, label: str) -> str:
        """
        从页面文本中抠出「<label>：值」的值部分。
        用正则匹配 label 后到下一个换行/常见分隔为止的内容，避免抓到整页文本。
        """
        body = self.page.inner_text("body")
        # 匹配 label（含中英文冒号）后面、直到换行为止的一段
        m = re.search(label + r"\s*[:：]\s*([^\n\r]*)", body)
        return m.group(1).strip() if m else ""

    def get_client_name(self) -> str:
        """读取「客户姓名」的值，用于确认客户已锁定。"""
        return self._extract_field("客户姓名")

    def get_option_account(self) -> str:
        """读取「美股期权账户」的值，确认锁定的正是该资金账号对应客户。"""
        return self._extract_field("美股期权账户")

    # ---------------------------- 导航到期权 ----------------------------
    def go_to_trade_records(self):
        """点击顶部「交易记录」tab。"""
        self.page.get_by_text("交易记录", exact=True).first.click()
        self.page.wait_for_timeout(1500)

    def go_to_option(self):
        """点击「期权」子 tab。"""
        self.page.get_by_text("期权", exact=True).first.click()
        self.page.wait_for_timeout(2500)

    # 期权二级子 tab 的 Element UI tab id 映射（来自页面探查）
    OPTION_SUBTAB_IDS = {
        "今日成交": "tab-todayTrading",
        "今日委托": "tab-todayEntrust",
        "历史成交": "tab-historyTraded",
        "历史委托": "tab-historyEntrust",
        "智能订单": "tab-smartSheetOrder",
    }

    def switch_option_subtab(self, name: str):
        """
        切换期权下的二级子 tab。
        Element UI 的 tab 是 role=tab 的 div，Playwright 常判定其"不可见"导致点击超时，
        因此优先用 tab id 直接派发点击事件。
        """
        tab_id = self.OPTION_SUBTAB_IDS.get(name)
        clicked = False
        if tab_id:
            # 用 JS 找到该 tab 并触发点击，绕过可见性判定
            clicked = self.page.evaluate(
                """(id) => {
                    const el = document.getElementById(id);
                    if (el) { el.click(); return true; }
                    return false;
                }""",
                tab_id,
            )
        if not clicked:
            # 兜底：按文本用 force 点击
            self.page.get_by_text(name, exact=True).first.click(force=True)
        self.page.wait_for_timeout(2500)

    def is_option_subtab_active(self, name: str) -> bool:
        """判断指定期权子 tab 当前是否处于激活态（class 含 is-active）。"""
        tab_id = self.OPTION_SUBTAB_IDS.get(name)
        if not tab_id:
            return False
        return self.page.evaluate(
            """(id) => {
                const el = document.getElementById(id);
                return !!el && el.className.includes('is-active');
            }""",
            tab_id,
        )

    # ---------------------------- 读取表格/统计 ----------------------------
    def get_table_headers(self) -> list:
        """读取当前可见表格的表头列名。"""
        return self.page.evaluate(
            """() => [...document.querySelectorAll('.el-table__header th .cell')]
                .filter(e => e.offsetParent !== null)
                .map(e => e.innerText.trim())
                .filter(Boolean)"""
        )

    def get_visible_row_count(self) -> int:
        """读取当前页表格数据行数（排除「暂无数据」占位行）。"""
        return self.page.evaluate(
            """() => {
                const rows = [...document.querySelectorAll('.el-table__body tbody tr')]
                  .filter(tr => tr.offsetParent !== null);
                // 过滤掉「暂无数据」的空占位
                const real = rows.filter(tr => !/暂无数据/.test(tr.innerText || ''));
                return real.length;
            }"""
        )

    def get_stat_total(self) -> int:
        """读取「当前查询条件下有 N 笔」里的 N；取不到返回 -1。"""
        text = self.page.inner_text("body")
        m = re.search(r"当前查询条件下有\s*(\d+)\s*笔", text)
        return int(m.group(1)) if m else -1

    def get_pagination_total(self) -> int:
        """读取底部「共 N 条」里的 N；取不到返回 -1。"""
        text = self.page.inner_text("body")
        m = re.search(r"共\s*(\d+)\s*条", text)
        return int(m.group(1)) if m else -1

    def get_page_size(self) -> int:
        """读取分页「N条/页」；取不到返回 -1。"""
        text = self.page.inner_text("body")
        m = re.search(r"(\d+)\s*条/页", text)
        return int(m.group(1)) if m else -1

    def screenshot(self, name: str):
        """保存截图到 screenshots 目录。"""
        config.SCREENSHOT_DIR.mkdir(exist_ok=True)
        path = config.SCREENSHOT_DIR / name
        self.page.screenshot(path=str(path))
        return str(path)
