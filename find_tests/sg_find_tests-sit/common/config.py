"""
公共配置模块（最大可买可卖 / 购买力查询 接口测试）
====================================================
对应文档: find_tests/explain.md
环境    : SIT

配置分五层:
  1. 环境 & 鉴权   —— BASE_URL / AUTHORIZATION / 公共请求头
  2. 资金账号      —— 来自 find_tests/data.txt
  3. 测试标的      —— 美股 / 港股(印花税) / A股 / OTC / 期权 / 组合腿
  4. 接口路径      —— 7 个查询接口(来自 png 接口文档)
  5. Redis / MQ    —— 缓存与消息队列服务信息(3.5 / 3.6 章节使用)
"""
import os

# ============================ 1. 环境 & 鉴权 ============================
# SIT 测试环境地址
#BASE_URL = "https://usmartclient-sit.usmartsg.com"
BASE_URL = "https://jy-sit.usmartsg.com"
# 登录 TOKEN(Authorization)。过期后只需在这里替换一次，全部脚本生效。
AUTHORIZATION = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM0T1RZek56TTJOemcxTnciLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiMzI1MGMxNmIyYWFiNDNlNmJkNjI0NzMzYWQyM2E5ZWYiLCJleHRyYSI6IkYxWXZmTHNVeHUxZXVHZVluQWNLSjBza0tGdXpPV2FxWnF6UmFNK1ZzelVBcVFOWWkzQkhwa0pOWUIrK0FTSjhtRk5NaytxTVdRUUNNVnBuVzBUekc2NGt4V2tyVk9vMFBvNlluZXp2d0VPZUlvSVNGYWdvejZsM3VncUE2TGI0Wks4eWNTbkJTaGJGRFgwUU5hVUlCVjhCRDNSMGpOVUlTRWpOSUJLeEl0TGt0RzRSakF4MFBocm5yMkRpdE95eDdwVFYiLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjc5NTM1OTUxMjA1NDIxMDU2LCJjbGllbnRfaWQiOiI4ODcxMjE5OSJ9.ikXqE_mtUcgGNiP4iQPkxSeV0xls_UtbTXB0GbzqEFw"
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
# 来源: find_tests/data.txt
CASH_ACCOUNT = "10002178"        # 现金账户
MARGIN_ACCOUNT = "80125438"      # 融资账户
PRO_ACCOUNT = "80009415"         # 专业/高级账户
FROZEN_ACCOUNT = "90000037"      # 冻结账户

# 当前 AUTHORIZATION 这个 token 实际归属的资金账号(实测 code:0 且数据自洽)
TOKEN_FUND_ACCOUNT = "80125375"

# 默认资金账号(大部分用例使用)。用 token 归属账号，避免 token 与账号不匹配。
DEFAULT_FUND_ACCOUNT = TOKEN_FUND_ACCOUNT

# 账户类型: 1-普通账户, 2-高级账户
ACCOUNT_TYPE = 1

# ★实测重要结论(2026-08)：
# 1) 改单类接口(stock-order-replace-max / short-order-replace-max)**不读 body 里的
#    fundAccount** —— 把 fundAccount 换成 10002178/80125438/80009415/90000037 这 4 个完全
#    不同的账号，返回的 cashBalance / maxBuyQty 一模一样。账号是由 orderId + token 推出来的。
#    => 想验证不同账户类型(CASH/MARGIN/pro/冻结)，**必须用该账号自己的 token + 自己的订单ID**，
#       只改 fundAccount 是无效的(会得到假的"通过")。
#    => 这直接影响 RFS-01(升融资) / RFS-06(降级) / CBO-08(冻结账户) 的做法。
# 2) token 与 fundAccount 不属于同一用户时，可能返回 110002「登录状态已失效, 请重新登录」，
#    这不是 token 过期，而是账号与 token 不匹配。

# 各账号对应的登录 token。
# 说明: /api/... 接口按 token 用户取资金账号(不传 fundAccount)，
#      切换账号验证时必须换成对应账号的 token，否则查到的还是默认用户。
TOKENS = {
    PRO_ACCOUNT: AUTHORIZATION,
    CASH_ACCOUNT: "",            # TODO 填入现金账户 token
    MARGIN_ACCOUNT: "",          # TODO 填入融资账户 token
    FROZEN_ACCOUNT: "",          # TODO 填入冻结账户 token
}

# 无期权沽空权限(OPTION_SHORT)的账号，用于 OPS-03
# 已实测: 10002178(CASH) 与 80125438(MARGIN) 均返回 400505「无对应交易权限」
NO_OPTION_SHORT_ACCOUNT = CASH_ACCOUNT
# 不存在的资金账号，用于 OPS-04 (实测返回 400092「资金账号不正确！」)
NOT_EXIST_FUND_ACCOUNT = "99999999"


# ============================ 3. 测试标的 ============================
# --- 股票 ---
US_STOCK = {"symbol": "AAPL", "market": "US", "currency": "USD", "handQty": 1}
HK_STOCK = {"symbol": "00700", "market": "HK", "currency": "HKD", "handQty": 100}   # 港股, 含印花税
A_STOCK = {"symbol": "600519", "market": "HGT", "currency": "CNY", "handQty": 100}  # 沪港通(A股子市场)
A_STOCK_SZ = {"symbol": "000001", "market": "SGT", "currency": "CNY", "handQty": 100}
OTC_STOCK = {"symbol": "OTCM", "market": "US", "currency": "USD", "handQty": 1}     # TODO 换成环境内真实 OTC/粉单标的

# 可沽空 / 不可沽空标的(SHT-02 使用)
SHORTABLE_STOCK = US_STOCK
NOT_SHORTABLE_STOCK = {"symbol": "TSLA", "market": "US", "currency": "USD", "handQty": 1}  # TODO 换成 availableTag=2 的标的

# --- 期权 ---
# 期权代码格式: 标的 + 到期日(YYMMDD) + C/P + 行权价×1000(6位)
# 例: QQQ 到期 2026-09-18, Call, 行权价 717 -> QQQ260918C717000
# ★注意期权会到期: 原用的 QQQ260819 系列已于 2026-08-19 到期, 全部返回
#   400064「期权代码不存在」, 会让组合类用例整片失败(消耗购买力出现负数/波动)。
#   到期后换更远月份即可, 已验证可用: QQQ260918 / QQQ261016 / QQQ261120 各行权价。
OPTION_SYMBOL = "QQQ260918C717000"    # 单腿期权用例(已验证有行情)
OPTION_MARKET = "US"
OPTION_MULTIPLIER = 100               # 期权乘数

# --- 组合期权策略(每个策略一组腿, 已验证全部 code:0) ---
# comboStrategy 已确认的枚举值:
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

# --- 已存在的订单 ID(改单类用例需要, 跑之前先下单拿到) ---
# 注意: 改单接口的账号是由 orderId 推出来的, 所以订单ID 必须属于你想测的那个账号。
#
# ★★ 委托属性会直接影响用例结论 ★★
#   order_api_tests 的下单脚本默认 ENTRUST_PROP="MKT"(市价单, ENTRUST_PRICE="0")。
#   市价单没有委托价, 接口只能按标的市价算最大可买 —— 此时传任何 entrustPrice 结果都不变,
#   这是正确行为, 不能当成「入参不生效」的缺陷。
#   要验证「委托价影响最大可买」, 必须用 ENTRUST_PROP="LMT" 的限价单
#   (已用 APP 抓包的限价单 1610005879714152448 验证: 委托价 10.77 时
#    maxBuyQty=925688 = 融资购买力/委托价 - 费用, 委托价确实参与计算)。
STOCK_LIMIT_ORDER_ID = 1610005879714152448    # 股票限价单(LMT), 验证委托价敏感性用
STOCK_ORDER_ID = 0                            # TODO 原 1608223107248807936 已不在途(100080)
OPTION_SHORT_ORDER_ID = 1608213092622376961   # 期权沽空 已验证 code:0
COMBO_ORDER_ID = 1608200135293247489          # 组合期权(账号 80125375) 已验证 code:0
# 股票沽空: 下面这笔属于账号 80001404, 与当前 token 用户不符, 调用会返回
# 450004「客户信息认证失败」。需要换成当前 token 用户自己的沽空在途单。
SHORT_ORDER_ID = 0                            # TODO 1608217159184670721(账号80001404, 归属不符)


# ============================ 4. 接口路径 ============================
# 端点名一律以接口文档(png / png2)为准, 不要自行改名。
#
# 实测的两条规律:
#   1) 文档写的是 /order-center-sg/api/...  —— 这是 APP 网关路由,
#      在 usmartclient-sit(中台网关)上访问会 HTTP404。
#      本机要用中台路由 /order-center-sg/admin-api/... , 端点名保持与文档一致。
#   2) 中台路由不带 order/ 这一段:
#         文档 /api/order/stock-order-replace-max/v1
#         中台 /admin-api/stock-order-replace-max/v1     <- 少了 order/
#
# 关于 {"code":110003,"msg":"您无权限,请申请"}:
#   这是**无权限**的正常业务响应 —— 当前 token/账号没有该接口的调用权限, 不是路径错误。
#   (注意该码语义偏宽: 请一个不存在的路径也会返回 110003 而不是 404,
#    所以排查顺序是先核对路径与文档一致, 确认无误后即按无权限处理。)
#
#   3) 中台路由必须显式传 fundAccount; api 路由才会按 token 用户取资金账号。
#      => OPS-01「不传资金账号按当前用户」只能在 APP 网关上验证(见 APP_PATHS)。
PATHS = {
    # ---------- 已实测可用(返回 code:0) ----------
    # 股票改单最大可改--ok
    "stock_replace_max": "/order-center-sg/admin-api/stock-order-replace-max/v1",
    # 股票沽空改单最大可改
    "short_replace_max": "/order-center-sg/admin-api/short-order-replace-max/v1",
    # 期权沽空最大可卖
    "option_short_max": "/order-center-sg/admin-api/short-option-sell-max/v1",
    # 期权沽空改单最大可卖
    "option_short_replace_max": "/order-center-sg/admin-api/short-option-replace-sell-max/v1",

    # ---------- png2 三个接口(端点名与 png2 文档逐字一致) ----------
    # 文档原始路径见下方 APP_PATHS(/order-center-sg/api/...), 那是 APP 网关。
    # 这里用中台前缀 admin-api + 同名端点。
    # 当前该 token 对这三个接口返回 110003「您无权限,请申请」= 无权限, 属预期响应。
    # 要在 APP 网关上跑, 填 APP_BASE_URL 并把 USE_APP_GATEWAY 设为 True。
    "consume_power": "/order-center-sg/admin-api/calculate-consumed-purchasing-power/v1",
    "order_max": "/order-center-sg/admin-api/stock-order-max-qty-get/v2",       # 新单聚合(v2)
    "order_replace_max": "/order-center-sg/admin-api/order-replace-max/v2",     # 改单聚合(v2)
    "short_max": "/order-center-sg/admin-api/short-order-max-qty-get/v1",

    # ---------- 接口文档未提供, 需按实际补充 ----------
    "combo_preview": "",        # TODO 组合下单预览接口路径(3.8)
    "refresh_user_cache": "",   # TODO 刷新用户信息缓存内部接口路径(RFS-03)
    "margin_upgrade": "",       # TODO 现金升融资接口路径(RFS-01)
}

# ============================ APP 网关 ============================
# png2 那三个接口挂在 APP 网关(基础地址 + /order-center-sg/api/...)，
# 不在中台网关 usmartclient-sit 上。已实测这个地址三个接口都能走到服务
# (返回 107003 Token 不能为空, 说明路由正确, 只差 token)。
APP_BASE_URL = "https://jy-sit.usmartsg.com"

# APP 网关的登录 token(JWT)。与中台 token 不通用。
APP_AUTHORIZATION = AUTHORIZATION

# 这几个接口固定走 APP 网关(其余接口仍走中台 BASE_URL)
APP_GATEWAY_KEYS = {"consume_power", "order_max", "order_replace_max"}

# 置 True 则**所有**接口都强制走 APP 网关(一般不需要)
USE_APP_GATEWAY = False
APP_PATHS = {
    # png2 三个接口的文档原始路径(APP 网关)
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


# ============================ 4.1 实测错误码 ============================
# 说明: 服务端返回的是 {"code": 数字, "msg": "中文文案"}，不是 explain.md 里的英文枚举名。
#      断言时用下面的数字 code 或中文文案，不要用英文枚举名。
ERROR_CODES = {
    # 接口无调用权限 —— 当前 token/账号没有该接口权限, 属预期的环境状态。
    # 注: 该码语义偏宽, 请一个不存在的路径也会返回它(而不是 404),
    #     所以排查顺序是先核对路径与接口文档一致, 确认无误后按无权限处理。
    "NO_API_PERMISSION": (110003, "您无权限,请申请"),

    # 无对应交易权限 —— 对应 explain.md 的 NO_CORRESPONDING_TRADE_PERMISSION(OPS-03)
    # 实测 10002178 / 80125438 / 80125375 均返回此码, 证实错误码变更已生效。
    "NO_CORRESPONDING_TRADE_PERMISSION": (400505, "无对应交易权限"),

    # 登录状态失效。实测: token 与 fundAccount 不属于同一用户时也会返回这个码，
    # 不一定是 token 真过期, 先确认账号与 token 是否匹配。
    "LOGIN_INVALID": (110002, "登录状态已失效"),

    # 资金账号不正确 —— 对应 OPTION_FUND_ACCOUNT_ERROR(OPS-04)
    "OPTION_FUND_ACCOUNT_ERROR": (400092, "资金账号不正确"),

    # 获取用户信息异常 —— 对应 FUND_ACCOUNT_INFO_NONE(CBO-05 / OPS-08)
    "FUND_ACCOUNT_INFO_NONE": (450004, "获取用户信息异常"),

    # 资金账号为空 —— 对应 BASE_CAPITAL_FUNDACCOUNT_ERROR(CBO-06)
    "FUNDACCOUNT_EMPTY": (None, "资金帐号不能为空"),

    # 参数校验失败
    "PARAM_INVALID": (450003, "不能为空"),

    # 行情服务失败 —— 对应 SERVICE_BUSY_ERROR(QUO-04)
    # TODO 数字 code 未实测(需先制造行情服务失败), 命中中文文案即可
    "SERVICE_BUSY_ERROR": (None, "服务繁忙"),

    # 真实交易链路: 冻结/异常账户被拦截 —— 对应 BASE_COMMON_FUNDACCOUNT_ERROR(REG-01)
    # TODO 数字 code 未实测
    "BASE_COMMON_FUNDACCOUNT_ERROR": (None, "资金账号"),

    # Token 为空
    "TOKEN_EMPTY": (107003, "Token 不能为空"),
}


# ============================ 5. Redis / MQ 服务信息 ============================
# Redis 集群(用户信息缓存所在, 3.5 / 3.6 使用)
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

# 用户信息缓存 key 关键字(实际 key 前缀以代码为准，这里用于模糊扫描)
CACHE_KEY_KEYWORDS = ["userInfo", "user_info", "fundAccount"]  # TODO 按实际 key 前缀调整
CACHE_EXPECT_TTL_HOURS = 8   # 预期缓存时长 8 小时

# RabbitMQ(开户/资金账号变更消息, RFS-02 使用)
MQ_ADDRESSES = [
    ("10.60.6.191", 5774),
    ("10.60.6.192", 5774),
    ("10.60.6.235", 5774),
]
MQ_USERNAME = "jy_sg_user"
MQ_PASSWORD = "jy_sg_user"
MQ_EXCHANGE = ""      # TODO 开通资金账号消息的 exchange
MQ_ROUTING_KEY = ""   # TODO 开通资金账号消息的 routing key


# ============================ 基线目录 ============================
# 取数一致性验证: 优化前的响应保存在这里，优化后逐字段比对
BASELINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "baseline")
