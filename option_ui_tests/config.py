"""
UI 自动化测试公共配置
======================
集中管理 URL、资金账号、登录态文件路径等，方便统一修改。
"""
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# ---------------------------- 环境地址 ----------------------------
# 客户后台管理系统首页（SIT 环境）
BASE_URL = "https://admin-sit.yxzq.com"
# 客户首页地址（hash 路由）
CLIENT_FIRST_PAGE = f"{BASE_URL}/admin/index.html#/clientFirstPage"

# ---------------------------- 测试数据 ----------------------------
# 查询用资金账号
FUND_ACCOUNT = "77000851"

# ---------------------------- 登录态 ----------------------------
# save_login.py 手动登录一次后保存的浏览器状态（cookie + storage）
AUTH_STATE_FILE = BASE_DIR / "auth_state.json"

# ---------------------------- 运行参数 ----------------------------
# 是否使用有头浏览器运行测试（True 可肉眼观察，False 后台跑）
HEADLESS = False
# 单步操作后的等待/超时（毫秒）
DEFAULT_TIMEOUT = 30000
# 截图输出目录
SCREENSHOT_DIR = BASE_DIR / "screenshots"
