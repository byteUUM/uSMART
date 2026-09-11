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
        # 缓存最近一次列表接口(today/history)的返回 data，用于接口<->页面<->DB 比对
        self._last_list_data = None
        self._last_list_body = None
        self._install_response_listener()

    # ---------------------------- 接口抓取 ----------------------------
    def _install_response_listener(self):
        def on_response(resp):
            try:
                url = resp.url
                if "list-homepage-today-order" in url or "list-homepage-history-order" in url:
                    self._last_list_data = resp.json().get("data", {})
                    self._last_list_body = resp.request.post_data
            except Exception:
                pass
        self.page.on("response", on_response)

    def get_last_list_data(self) -> dict:
        """返回最近一次列表接口的 data（含 total/pageNum/pageSize/list）。"""
        return self._last_list_data or {}

    def get_last_list_body(self) -> str:
        """返回最近一次列表接口的请求体 JSON 字符串（用于校验查询入参）。"""
        return self._last_list_body or ""

    def clear_last_list(self):
        """清空缓存，便于确认某次操作确实触发了新接口。"""
        self._last_list_data = None
        self._last_list_body = None

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
        """读取当前页表格数据行数（去重 + 排除占位行），复用 get_table_matrix。"""
        return len(self.get_table_matrix())

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

    def get_table_matrix(self) -> list:
        """
        读取当前表格所有行、所有列的渲染文本，返回 list[list[str]]（行 x 列）。
        处理两个坑：
          1. Element UI 每条数据可能渲染成 2 个 tr（展开行机制），用 el-table row-key 去重；
             这里改为只取 body-wrapper 内、且是「主行」(含数据 td) 的 tr，并按行内容去重。
          2. 部分表首列是展开图标空 cell，导致 cell 数比表头多 1，交给 get_row_dicts 处理。
        """
        return self.page.evaluate(
            """() => {
                // 只取主体 body-wrapper（排除 fixed 副本），可见且非空占位
                const wrap = [...document.querySelectorAll('.el-table__body-wrapper')]
                    .filter(w => w.offsetParent !== null)[0];
                if (!wrap) return [];
                const trs = [...wrap.querySelectorAll('tbody > tr')]
                    .filter(tr => !/暂无数据/.test(tr.innerText || ''));
                // 去重：Element 展开行会产生重复 tr，按整行文本去重
                const seen = new Set();
                const out = [];
                for (const tr of trs) {
                    const cells = [...tr.querySelectorAll('td .cell')].map(c => c.innerText.trim());
                    if (cells.length === 0) continue;
                    const key = cells.join('||');
                    if (seen.has(key)) continue;
                    seen.add(key);
                    out.push(cells);
                }
                return out;
            }"""
        )

    def get_row_dicts(self) -> list:
        """
        把当前表格读成 list[dict]（列名 -> 值）。
        若某行 cell 数比表头多 1 且首格为空（展开图标列），去掉该前导空格再对齐。
        """
        headers = self.get_table_headers()
        matrix = self.get_table_matrix()
        result = []
        for row in matrix:
            cells = row
            # 处理前导展开图标空 cell 造成的错位
            if len(cells) == len(headers) + 1 and cells and cells[0] == "":
                cells = cells[1:]
            d = {}
            for i, h in enumerate(headers):
                d[h] = cells[i] if i < len(cells) else ""
            result.append(d)
        return result

    # ---------------------------- 查询操作 ----------------------------
    def fill_search_input(self, label: str, value: str):
        """
        在搜索区某个「文本输入」条件里填值。
        经实测：期权搜索区可见的 placeholder='请输入' 文本框有两个，
        顺序为 [底层证券代码, 证券代码]，用下面的索引映射精确定位。
        用 Playwright fill 触发正确的输入事件（保证被 Vue v-model 捕获）。
        返回是否成功填入。
        """
        index_map = {
            "底层证券代码": 0,
            "证券代码": 1,
        }
        idx = index_map.get(label)
        boxes = self.page.locator("input[placeholder='请输入']:visible")
        if idx is None or idx >= boxes.count():
            return False
        target = boxes.nth(idx)
        target.fill(value)
        self.page.wait_for_timeout(300)
        return True

    def select_dropdown(self, label: str, option_text: str):
        """
        在搜索区某个 el-select 下拉里选择指定文本的选项。label 如「买卖方向」。
        """
        # 点开该 label 对应的 select
        opened = self.page.evaluate(
            """(label) => {
                const items = [...document.querySelectorAll('.el-form-item')];
                for (const it of items) {
                    const lab = it.querySelector('.el-form-item__label');
                    if (lab && lab.innerText.includes(label)) {
                        const inp = it.querySelector('.el-select input, input');
                        if (inp) { inp.click(); return true; }
                    }
                }
                return false;
            }""",
            label,
        )
        self.page.wait_for_timeout(600)
        # 从弹出的下拉里点选项（取可见的最后一个下拉面板）
        opt = self.page.locator(".el-select-dropdown:visible .el-select-dropdown__item", has_text=option_text)
        if opt.count() > 0:
            opt.first.click()
        self.page.wait_for_timeout(300)
        return opened

    def click_search(self):
        """点击搜索区的搜索按钮并等待列表接口刷新。"""
        self.clear_last_list()
        # 加 :visible 只命中当前激活 tab 里那个按钮（DOM 中存在多套隐藏表单）
        self.page.locator("button.el-button--small:has-text('搜索'):visible").first.click()
        self._wait_list_response()

    def click_reset(self):
        """点击搜索区的重置按钮（只点当前激活 tab 里可见的那个）。"""
        self.clear_last_list()
        self.page.locator("button.el-button--small:has-text('重置'):visible").first.click()
        self.page.wait_for_timeout(2000)

    def _wait_list_response(self, timeout_ms=8000):
        """轮询等待列表接口返回被缓存。"""
        waited = 0
        step = 400
        while waited < timeout_ms:
            self.page.wait_for_timeout(step)
            waited += step
            if self._last_list_data is not None:
                return True
        return False

    def set_page_size(self, size: int):
        """切换每页条数（10/20/50/100）。返回是否触发了接口。"""
        self.clear_last_list()
        self.page.locator(".el-pagination:visible .el-select input").first.click()
        self.page.wait_for_timeout(500)
        self.page.locator(".el-select-dropdown:visible .el-select-dropdown__item",
                          has_text=f"{size}条/页").first.click()
        return self._wait_list_response()

    def go_to_next_page(self):
        """点击分页下一页。返回是否触发了接口。"""
        self.clear_last_list()
        self.page.locator(".el-pagination:visible .btn-next").first.click()
        return self._wait_list_response()

    def get_current_page_num(self) -> int:
        """读取分页当前激活页码。"""
        return self.page.evaluate(
            """() => {
                const pgs = [...document.querySelectorAll('.el-pagination')].filter(p => p.offsetParent !== null);
                for (const p of pgs) {
                    const active = p.querySelector('.el-pager .number.active');
                    if (active) return parseInt(active.innerText);
                }
                return -1;
            }"""
        )

    def has_export_button(self) -> bool:
        """当前激活 tab 是否存在可见的「导出」按钮。"""
        return self.page.locator("button.el-button--small:has-text('导出'):visible").count() > 0

    def screenshot(self, name: str):
        """保存截图到 screenshots 目录。"""
        config.SCREENSHOT_DIR.mkdir(exist_ok=True)
        path = config.SCREENSHOT_DIR / name
        self.page.screenshot(path=str(path))
        return str(path)
