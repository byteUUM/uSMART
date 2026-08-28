"""
公共配置模块（最大可买可卖 / 购买力查询 接口测试）
====================================================
对应文档: find_tests/explain.md
环境    : UAT

配置分五层:
  1. 环境 & 鉴权   —— BASE_URL / AUTHORIZATION / 公共请求头
  2. 资金账号      —— 来自 find_tests/data.txt
  3. 测试标的      —— 美股 / 港股(印花税) / A股 / OTC / 期权 / 组合腿
  4. 接口路径      —— 7 个查询接口(来自 png 接口文档)
  5. Redis / MQ    —— 缓存与消息队列服务信息(3.5 / 3.6 章节使用)
"""
import os

# ============================ 1. 环境 & 鉴权 ============================
# UAT 环境地址
BASE_URL = "https://jy-uat.usmartsg.com"
# 登录 TOKEN(Authorization)。过期后在此处替换一次即可, 全部脚本生效。
AUTHORIZATION = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM1TURJME1UYzRPREE1T1EiLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiYzc1OTMxZWQzNTM2NGJlZDk1NmRiNjk4NmYxYTY3ZDciLCJleHRyYSI6IllJbWFlYXhCVlVRQmhydlN0QmJ1aWJzUFAwSFRZME0vanlGTmFqbnhvenR2Y3Z0czd2QlhYUjd3U0ZLR2JKdWZ0emhiQ1djakZNK2NmMEtyaDQwcG1TTnlBZmM1a05maXlYMHBqRVN0QVF0ZjhCYkVrczA1WCtqcy9EMlZGME5xaFEyYi96TzFuYlcwTVhRQ2oraFMwNFVDcU9GNzQ0TEdibnhZZVZkV1I1K2NPTVVFKzhYLzhZMzlXeHovcWJENUVmND0iLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjg5Njc4MTM3MTA1MzY3MDQwLCJjbGllbnRfaWQiOiI4MzczMTc0OSJ9.QC29hNcRToaWkTFX7SWSXryEL9_LMUsSxom8tSuPV6I"
)

# 公共请求头(所有接口共用)。X-Request-Id 会在发送时自动生成，不在这里写死。
COMMON_HEADERS = {
    "Authorization": AUTHORIZATION,
    "X-Channel": "1",       # 渠道: 1-中台, 2-app
    "X-Client-Id": "2",     # APP 用户 ID
    "X-Dt": "t1",           # 设备类型: 1-安卓, 2-ios, 3-其它
    "X-Lang": "1",          # 语言类型: 1-简体, 2-繁体, 3-英文
    "X-Type": "12",          # app 类型: 1-友信智投, 2-uSmart, 3-其它
    "Content-Type": "application/json",
}


# ============================ 2. 资金账号 ============================
# 来源: order_api_tests/sg_order_api_tests-uat/common/config.py
CASH_ACCOUNT = "80019812"        # 默认账号, 股票/期权/组合/碎股共用
MARGIN_ACCOUNT = ""              # 待补: 融资账户
PRO_ACCOUNT = ""                 # 待补: 专业/高级账户
FROZEN_ACCOUNT = ""              # 待补: 冻结账户
SHORT_ACCOUNT = "80019713"       # 股票沽空专用账号

# 当前 AUTHORIZATION 归属的资金账号
TOKEN_FUND_ACCOUNT = "80019812"

# 默认资金账号。取 token 归属账号, 避免 token 与账号不匹配。
DEFAULT_FUND_ACCOUNT = TOKEN_FUND_ACCOUNT

# 账户类型: 1-普通账户, 2-高级账户
ACCOUNT_TYPE = 1

# 账号来源说明:
#   /api/... 路由按 token 用户取资金账号, 请求体中的 fundAccount 不用于切换账号;
#   改单类接口的账号由 orderId 推导。
#   因此验证不同账户类型(现金/融资/专业/冻结)时, 必须使用该账号自身的 token 与订单,
#   仅替换 fundAccount 不会生效。这直接影响 RFS-01 / RFS-06 / CBO-08 的执行方式。
#   token 与 fundAccount 不属于同一用户时会返回 110002, 表示账号与 token 不匹配。

# 各账号对应的登录 token, 切换账号验证时使用
TOKENS = {
    PRO_ACCOUNT: AUTHORIZATION,
    CASH_ACCOUNT: "",            # 待补: 现金账户 token
    MARGIN_ACCOUNT: "",          # 待补: 融资账户 token
    FROZEN_ACCOUNT: "",          # 待补: 冻结账户 token
}

# 无期权沽空权限的账号, 用于 OPS-03(预期返回 400505 无对应交易权限)
NO_OPTION_SHORT_ACCOUNT = CASH_ACCOUNT
# 不存在的资金账号, 用于 OPS-04(预期返回 400092 资金账号不正确)
NOT_EXIST_FUND_ACCOUNT = "99999999"


# ============================ 3. 测试标的 ============================
# --- 股票 ---
US_STOCK = {"symbol": "AAPL", "market": "US", "currency": "USD", "handQty": 1}
HK_STOCK = {"symbol": "00700", "market": "HK", "currency": "HKD", "handQty": 100}   # 港股, 含印花税
A_STOCK = {"symbol": "600519", "market": "HGT", "currency": "CNY", "handQty": 100}  # 沪港通(A股子市场)
A_STOCK_SZ = {"symbol": "000001", "market": "SGT", "currency": "CNY", "handQty": 100}
# 待确认: 需替换为环境内真实 OTC / 粉单标的
OTC_STOCK = {"symbol": "OTCM", "market": "US", "currency": "USD", "handQty": 1}

# 可沽空 / 不可沽空标的(SHT-02 使用)
SHORTABLE_STOCK = US_STOCK
# 待确认: 需替换为 availableTag=2 的不可沽空标的
NOT_SHORTABLE_STOCK = {"symbol": "TSLA", "market": "US", "currency": "USD", "handQty": 1}

# --- 期权 ---
# 期权代码格式: 标的 + 到期日(YYMMDD) + C/P + 行权价×1000(6位)
# 例: QQQ 到期 2026-09-18, Call, 行权价 717 -> QQQ260918C717000
#
# 期权到期后代码失效, 会返回 400064「期权代码不存在」, 并导致组合类用例整体失败。
# 运行前请确认到期日晚于当前日期, 需要更换时可选用 QQQ260918 / QQQ261016 / QQQ261120。
OPTION_SYMBOL = "QQQ260918C717000"
OPTION_MARKET = "US"
OPTION_MULTIPLIER = 100               # 期权乘数

# --- 组合期权策略, 每个策略一组腿 ---
# comboStrategy 枚举:
#   VERTICAL_CALL   垂直策略(Call)  买低行权价Call + 卖高行权价Call
#   VERTICAL_PUT    垂直策略(Put)   买低行权价Put + 卖高行权价Put
#   STRADDLE        跨式           买Call + 买Put, 同行权价
#   STRANGLE        宽跨式         买Call + 买Put, 不同行权价
#   COLLAR          领式           买股票 + 买Put + 卖Call
#   COVERED_CALL    备兑           买股票 + 卖Call
# legRatio: 每份组合的腿数量比例, 需 >=1 且两腿比例互为质数
COMBO_STRATEGIES = {
    # 牛市价差(Bull Call Spread): 买低行权价 Call + 卖高行权价 Call
    "牛市价差": {
        "comboStrategy": "VERTICAL_CALL",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918C715000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918C725000"},
        ],
    },
    # 熊市价差(Bear Put Spread): 买高行权价 Put + 卖低行权价 Put
    "熊市价差": {
        "comboStrategy": "VERTICAL_PUT",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918P725000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918P715000"},
        ],
    },
    # 跨式(Straddle): 同行权价 买 Call + 买 Put
    "跨式": {
        "comboStrategy": "STRADDLE",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918C717000"},
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918P717000"},
        ],
    },
    # 宽跨式(Strangle): 不同行权价 买 Put + 买 Call
    "宽跨式": {
        "comboStrategy": "STRANGLE",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918P716000"},
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918C726000"},
        ],
    },
    # 备兑(Covered Call): 买股票 + 卖 Call
    "备兑": {
        "comboStrategy": "COVERED_CALL",
        "comboLegs": [
            {"businessType": "S", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918C717000"},
        ],
    },
    # 领式(Collar): 买股票 + 买 Put + 卖 Call
    "领式": {
        "comboStrategy": "COLLAR",
        "comboLegs": [
            {"businessType": "S", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ"},
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918P715000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918C725000"},
        ],
    },
}

# 多腿标的各不相同(QUO-01): QQQ + AAPL
COMBO_LEGS_DIFF_UNDERLYING = [
    {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918C715000"},
    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "AAPL260918C230000"},
]
# 多腿共享同一标的(QUO-02): 都是 QQQ
COMBO_LEGS_SAME_UNDERLYING = COMBO_STRATEGIES["牛市价差"]["comboLegs"]
# 行情缺失的腿(QUO-03): UTL 无行情(已到期/不存在的代码同样返回 400064)
COMBO_LEGS_NO_QUOTE = [
    {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260918C717000"},
    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "UTL260918C50000"},
]
# 多条 SHORT 腿(PRV-02)
COMBO_LEGS_MULTI_SHORT = [
    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918C715000"},
    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918C725000"},
    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260918P717000"},
]

# --- 改单类用例所需的在途订单 ID ---
# 改单接口的账号由 orderId 推导, 因此订单必须属于目标账号。
#
# 委托属性会影响用例结论:
#   市价单(ENTRUST_PROP=MKT, ENTRUST_PRICE=0)没有委托价, 最大可买按标的市价计算,
#   此时传入任何 entrustPrice 结果都不变, 属正常行为。
#   验证委托价敏感性需使用限价单(ENTRUST_PROP=LMT), 见 STOCK_LIMIT_ORDER_ID。
STOCK_LIMIT_ORDER_ID = 0                      # 待补: 股票限价在途单
STOCK_ORDER_ID = 1609761017595428864          # 股票在途单(AAPL 市价单)
OPTION_SHORT_ORDER_ID = 1609764032108822528   # 期权沽空在途单
COMBO_ORDER_ID = 0                            # 待补: 组合期权在途单
SHORT_ORDER_ID = 0                            # 待补: 账号 80019713 的股票沽空在途单


# ============================ 4. 接口路径 ============================
# 端点名以接口文档为准。
#
# 路由差异:
#   文档给出的 /order-center-sg/api/... 为 APP 网关路由, 在中台网关上访问返回 HTTP 404;
#   中台对应路由为 /order-center-sg/admin-api/..., 且不含 order/ 这一段, 例如
#     APP  /api/order/stock-order-replace-max/v1
#     中台 /admin-api/stock-order-replace-max/v1
#   中台路由需显式传 fundAccount, APP 路由才按 token 用户取资金账号,
#   因此 OPS-01「不传资金账号按当前用户」只能在 APP 网关验证。
#
# 返回 110003「您无权限,请申请」表示当前 token 无该接口调用权限, 属正常业务响应。
# 该码语义偏宽, 访问不存在的路径同样返回 110003 而非 404, 排查时先核对路径与文档一致。
PATHS = {
    "stock_replace_max": "/order-center-sg/admin-api/stock-order-replace-max/v1",
    "short_replace_max": "/order-center-sg/admin-api/short-order-replace-max/v1",
    "option_short_max": "/order-center-sg/admin-api/short-option-sell-max/v1",
    "option_short_replace_max": "/order-center-sg/admin-api/short-option-replace-sell-max/v1",

    # 下列三个接口的 APP 网关路径见 APP_PATHS, 此处为中台同名端点
    "consume_power": "/order-center-sg/admin-api/calculate-consumed-purchasing-power/v1",
    "order_max": "/order-center-sg/admin-api/stock-order-max-qty-get/v2",
    "order_replace_max": "/order-center-sg/admin-api/order-replace-max/v2",
    "short_max": "/order-center-sg/admin-api/short-order-max-qty-get/v1",

    # 接口文档未提供, 需按实际补充
    "combo_preview": "",        # 待补: 组合下单预览接口路径(3.8)
    "refresh_user_cache": "",   # 待补: 刷新用户信息缓存内部接口路径(RFS-03)
    "margin_upgrade": "",       # 待补: 现金升融资接口路径(RFS-01)
}

# ============================ APP 网关 ============================
# 三个购买力查询接口挂在 APP 网关, 不在中台网关上。
APP_BASE_URL = "https://jy-uat.usmartsg.com"

# APP 网关的登录 token(JWT), 与中台 token 不通用。
APP_AUTHORIZATION = AUTHORIZATION

# 下列接口固定走 APP 网关, 其余走中台 BASE_URL
APP_GATEWAY_KEYS = {"consume_power", "order_max", "order_replace_max"}

# 置 True 时所有接口强制走 APP 网关
USE_APP_GATEWAY = False
APP_PATHS = {
    "consume_power": "/order-center-sg/api/calculate-consumed-purchasing-power/v1",
    "order_max": "/order-center-sg/api/order/stock-order-max-qty-get/v2",
    "order_replace_max": "/order-center-sg/api/order/order-replace-max/v2",
    "short_max": "/order-center-sg/api/order/short-order-max-qty-get/v1",
    "short_replace_max": "/order-center-sg/api/order/short-order-replace-max/v1",
    "stock_replace_max": "/order-center-sg/api/order/stock-order-replace-max/v1",
    "option_short_max": "/order-center-sg/admin-api/short-option-sell-max/v1",
    "option_short_replace_max": "/order-center-sg/admin-api/short-option-replace-sell-max/v1",
}


def is_app_gateway(path_key: str) -> bool:
    """该接口是否走 APP 网关。"""
    return USE_APP_GATEWAY or path_key in APP_GATEWAY_KEYS


def url_for(path_key: str) -> str:
    """
    根据 key 拼出完整 URL。
    APP_GATEWAY_KEYS 里的接口走 APP 网关(APP_BASE_URL + APP_PATHS)，
    其余走中台(BASE_URL + PATHS)。
    """
    if is_app_gateway(path_key):
        if not APP_BASE_URL:
            raise ValueError(f"{path_key} 需走 APP 网关, 但 APP_BASE_URL 未配置")
        return APP_BASE_URL + APP_PATHS[path_key]
    path = PATHS[path_key]
    if not path:
        raise ValueError(f"接口路径未配置: {path_key}，请先在 config.PATHS 中补充")
    return BASE_URL + path


# ============================ 4.1 错误码 ============================
# 服务端返回 {"code": 数字, "msg": "中文文案"}, 与 explain.md 中的英文枚举名不同。
# 断言时使用下列数字 code 或中文文案。
ERROR_CODES = {
    # 接口无调用权限。该码语义偏宽, 访问不存在的路径同样返回它而非 404,
    # 排查时先核对路径与接口文档一致。
    "NO_API_PERMISSION": (110003, "您无权限,请申请"),

    # 无对应交易权限, 对应 explain.md 的 NO_CORRESPONDING_TRADE_PERMISSION(OPS-03)
    "NO_CORRESPONDING_TRADE_PERMISSION": (400505, "无对应交易权限"),

    # 登录状态失效。token 与 fundAccount 不属于同一用户时同样返回该码,
    # 需先确认账号与 token 是否匹配。
    "LOGIN_INVALID": (110002, "登录状态已失效"),

    # 资金账号不正确, 对应 OPTION_FUND_ACCOUNT_ERROR(OPS-04)
    "OPTION_FUND_ACCOUNT_ERROR": (400092, "资金账号不正确"),

    # 获取用户信息异常, 对应 FUND_ACCOUNT_INFO_NONE(CBO-05 / OPS-08)
    "FUND_ACCOUNT_INFO_NONE": (450004, "获取用户信息异常"),

    # 资金账号为空, 对应 BASE_CAPITAL_FUNDACCOUNT_ERROR(CBO-06)
    "FUNDACCOUNT_EMPTY": (None, "资金帐号不能为空"),

    # 参数校验失败
    "PARAM_INVALID": (450003, "不能为空"),

    # 期权代码不存在, 常见于期权已到期
    "OPTION_SYMBOL_NOT_EXIST": (400064, "期权代码不存在"),

    # 下游服务不可用
    "SERVICE_UNAVAILABLE": (100012, "服务繁忙"),

    # 订单信息找不到
    "ORDER_NOT_FOUND": (100080, "订单信息找不到"),

    # 行情服务失败, 对应 SERVICE_BUSY_ERROR(QUO-04), 数字 code 待补
    "SERVICE_BUSY_ERROR": (None, "服务繁忙"),

    # 真实交易链路中冻结或异常账户被拦截, 对应 BASE_COMMON_FUNDACCOUNT_ERROR(REG-01),
    # 数字 code 待补
    "BASE_COMMON_FUNDACCOUNT_ERROR": (None, "资金账号"),

    # Token 为空
    "TOKEN_EMPTY": (107003, "Token 不能为空"),
}


# ============================ 5. Redis / MQ 服务信息 ============================
# 下列地址与密码取自 SIT, UAT 为独立部署的另一套, 需替换后才能执行
# 缓存(CACHE-01~08)与缓存刷新(RFS-01~06)章节。
# Redis 集群, 用户信息缓存所在(3.5 / 3.6 章节使用)
REDIS_NODES = [
    ("10.60.6.164", 6383),
    ("10.60.6.165", 6384),
    ("10.60.6.166", 6384),
    ("10.60.6.165", 6383),
    ("10.60.6.166", 6383),
    ("10.60.6.164", 6384),
]
REDIS_PASSWORD = "xpMj4KymXLe5"
REDIS_DATABASE = 0
REDIS_TIMEOUT = 60

# 用户信息缓存 key 关键字, 用于模糊扫描, 实际前缀以服务端代码为准
CACHE_KEY_KEYWORDS = ["userInfo", "user_info", "fundAccount"]
CACHE_EXPECT_TTL_HOURS = 8   # 预期缓存时长 8 小时

# RabbitMQ, 开户与资金账号变更消息(RFS-02 使用)
MQ_ADDRESSES = [
    ("10.60.6.191", 5774),
    ("10.60.6.192", 5774),
    ("10.60.6.235", 5774),
]
MQ_USERNAME = "jy_sg_user"
MQ_PASSWORD = "jy_sg_user"
MQ_EXCHANGE = ""      # 待补: 开通资金账号消息的 exchange
MQ_ROUTING_KEY = ""   # 待补: 开通资金账号消息的 routing key


# ============================ 基线目录 ============================
# 取数一致性验证: 优化前的响应保存在此目录, 优化后逐字段比对
BASELINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "baseline")
