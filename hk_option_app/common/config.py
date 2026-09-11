"""
HK 期权 APP 端接口性能优化测试 —— 公共配置
=============================================
对应需求 ZTHK-17628：期权 APP 交易、期权 APP 改单等接口性能优化。
本次优化点(需要测的)：
  1. 期权下单时获取"期权基本信息"改用 redis 缓存；
  2. 期权下单(检查做空持仓 / 沽空校验与填充数据)场景，当订单来源为 app / openApi 时，
     获取"期权沽空账户用户信息"改用 redis 缓存；
  3. app 端改单一系列同步调用改为异步调用。

与中台(admin-api)脚本的区别：
  - 本目录测的是 APP 端接口，路径是 /option-order-server/api/xxx（不是 admin-api）。
  - 请求头 X-Channel=2(app)，下单来源 order_origin=1(app)。
  - app 下单请求体不带 capitalAccount，服务端按 token 用户 + businessType 定账户；
    沽空(OS)会自动落到该用户的沽空子账户(S 前缀)。

环境切换：
  - 默认 SIT。设环境变量 OPT_ENV=UAT 切到 UAT。
    PowerShell:  $env:OPT_ENV="UAT"; python xxx.py
  - 或在脚本里 import 前设置 os.environ["OPT_ENV"]="UAT"。
"""
import os

# ============================ 0. 环境选择 ============================
ENV = os.environ.get("OPT_ENV", "UAT").upper()
if ENV not in ("SIT", "UAT"):
    raise ValueError(f"OPT_ENV 只能是 SIT 或 UAT, 当前={ENV}")


# ============================ 1. 各环境参数 ============================
# 说明：
#   base_url    交易网关地址
#   authorization  APP 用户 token(X-Channel=2)。
#       ★★ 注意：这是会过期的登录 token，失效后需要重新抓一个填进来。
#       抓取方式见 README。下面预置的值来自会话中沿用的中台 token，
#       仅作占位，真跑 app 接口前务必替换成 app 端 token。
#   kibana      该环境的 Kibana 地址(查日志用)
#   es_index    option-order-server 日志索引
#   redis_startup_nodes  该环境 redis cluster 种子节点
#   default_account / short_account  普通 / 沽空资金账户(仅中台预估费用等需要显式传时用)
_ENVS = {
    "SIT": {
        "base_url": "https://admin-sit.yxzq.com",
        # APP 端 token（X-Channel=2）。占位：先沿用中台 token 探测，若鉴权失败请替换。
        "authorization": (
            "90A25FFBB05229F344673D99D401A27EABE8E68EDA0ADEF3E747914F897E9C0A08D62B6B9CEFB3A5"
            "E24F7D34FADD82345EEE52FE9BA60F068BB74F756449E395C5D24A727A989350F2EF66E60D4F629B"
            "1D1EB93976D66D0483402680097B85FB405E50E0BF1DE3D1BCE5DF353D584394FA1BC44E85CFBA14"
            "189196E3EF5EFC13"
        ),
        "kibana": "http://10.60.6.68:5601",
        "es_index": "option-order-server-sit*",
        # SIT redis cluster: 端口 6411/6412
        "redis_startup_nodes": [
            ("10.60.6.164", 6411),
            ("10.60.6.165", 6411),
            ("10.60.6.166", 6411),
            ("10.60.6.166", 6412),
        ],
        # SIT redis 密码(待确认, 若不同请更新; 先试 UAT 同款)
        "redis_password": "xpMj4KymXLe5",
        "redis_db": 0,
        "default_account": "77000851",
        "short_account": "S77000851",
    },
    "UAT": {
        # app 端交易网关(HK UAT)。admin-uat 只路由中台 admin-api，app 的 /api/ 走 jy-uat。
        "base_url": "https://jy-uat.yxzq.com",
        # APP 端登录 token(source=app, userType=0, uuid=1049392741460144128)
        "authorization": (
            "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM1TVRjd05UWXdPREV6TXciLCJsb2"
            "dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiNDY5NWI3ZmYyODBkNGU0NWEwODYyMDRkYzRmZGMyY2"
            "YiLCJleHRyYSI6IjYvTHJiV1JRVEsyTGdOUG9FVzlIQmtwRTk2ZzNJbzVWZmE5aVJpUEJaRVRMZXVuVF"
            "NPS1VadjVjZXRLUDM4Rmc3cHJ0VDZIOUVWekNEbCtHeisvZWNjYmF6bHJWLy85UGc3RTFzNUlnek11Y2"
            "pycUJpbERmN2NycjJGYVBKdm9oL1B5bEcwTFpwUDV3aUpKRnBzN0ZuNDlPUzFEazk4V3kiLCJzb3VyY2"
            "UiOiJhcHAiLCJ1c2VyVHlwZSI6MCwidXVpZCI6MTA0OTM5Mjc0MTQ2MDE0NDEyOH0.p0phIeNDQfD2Gy"
            "KtbLvHN2v3k_9NqYhKrjTvWorKUws"
        ),
        # app 用户信息(用于 redis 缓存校验的 uuid)
        "app_user_uuid": 1049392741460144128,
        "kibana": "http://10.60.6.69:5601",
        "es_index": "option-order-server-uat*",
        # UAT redis cluster: 端口 6419/6420 (来自 UAT application.properties)
        "redis_startup_nodes": [
            ("10.60.6.164", 6419),
            ("10.60.6.165", 6420),
            ("10.60.6.166", 6420),
            ("10.60.6.165", 6419),
            ("10.60.6.166", 6419),
            ("10.60.6.164", 6420),
        ],
        # UAT redis 密码(来自 UAT application.properties: spring.redis.password)
        "redis_password": "xpMj4KymXLe5",
        "redis_db": 0,
        "default_account": "77001164",
        "short_account": "S77001164",
    },
}

_C = _ENVS[ENV]

BASE_URL = _C["base_url"]
AUTHORIZATION = _C["authorization"]
KIBANA_BASE = _C["kibana"]
ES_INDEX = _C["es_index"]
REDIS_STARTUP_NODES = _C["redis_startup_nodes"]
REDIS_PASSWORD = _C.get("redis_password")
REDIS_DB = _C.get("redis_db", 0)
DEFAULT_ACCOUNT = _C["default_account"]
SHORT_ACCOUNT = _C["short_account"]
APP_USER_UUID = _C.get("app_user_uuid")


# ============================ 2. 请求头(APP 端) ============================
# X-Channel=2 表示 app 渠道；下单落库 order_origin=1(app)。
COMMON_HEADERS = {
    "Authorization": AUTHORIZATION,
    "X-Channel": "2",       # 渠道: 1-中台, 2-app  ← 本目录测 app, 固定 2
    "X-Client-Id": "2",
    "X-Dt": "2",            # 设备类型: 1-安卓, 2-ios, 3-其它
    "X-Lang": "1",          # 语言: 1-简体, 2-繁体, 3-英文
    "X-Type": "2",          # app 类型: 1-友信智投, 2-uSmart, 3-其它
    "Content-Type": "application/json",
}


# ============================ 3. APP 端接口路径 ============================
PATHS = {
    # 下单(APP)：OptionTradeRequest
    "option_trade":            "/option-order-server/api/option-trade/v1",
    # 改单(APP)：注意 body 用 orderNo(不是 orderId)
    "option_replace":          "/option-order-server/api/option-replace-order/v1",
    # 撤单(APP)
    "option_cancel":           "/option-order-server/api/option-cancel-order/v1",
    # 最大可买可卖-下单页(APP)
    "option_customer_range":   "/option-order-server/api/option-customer-range/v1",
    # 最大可买(简版, 下单页)
    "option_customer_buy_max": "/option-order-server/api/option-customer-buy-max/v1",
    # 改单最大可买可卖(APP)
    "option_replace_range":    "/option-order-server/api/option-customer-replace-range/v1",
    # 订单列表 / 详情(APP, 查下单结果用)
    "user_order_list":         "/option-order-server/api/user-all-option-order-list/v1",
    "user_order_detail":       "/option-order-server/api/user-option-order-detail/v1",
    # 预估费用：APP 下单页也会调，实际是 admin-api 路径
    "option_excepted_fee":     "/option-order-server/admin-api/option-excepted-fee/v1",
}


def url_for(path_key: str) -> str:
    path = PATHS[path_key]
    if not path:
        raise ValueError(f"PATHS['{path_key}'] 未配置")
    return BASE_URL + path


# ============================ 4. 业务枚举 ============================
# businessType 业务类型: O-期权, OS-期权沽空
BUSINESS_TYPE_OPTION = "O"
BUSINESS_TYPE_OPTION_SHORT = "OS"

# orderType: 1-市价, 2-限价(盘前只支持限价)
ORDER_TYPE_MARKET = 1
ORDER_TYPE_LIMIT = 2

# entrustType: 1-电话委托, 2-Internet 委托(app 用 2)
ENTRUST_TYPE_NORMAL = 1
ENTRUST_TYPE_INTERNET = 2

# side: 1-买入, 2-卖出
SIDE_BUY = 1
SIDE_SELL = 2

# sessionType 交易时段: 0-盘中, 1-仅盘前, 10-盘前+盘中
SESSION_TYPE_REGULAR = 0
SESSION_TYPE_PRE_MARKET = 1
SESSION_TYPE_PRE_AND_REGULAR = 10


# ============================ 5. redis 缓存 key 约定 ============================
# 期权相关缓存统一前缀：option-order-server:option:*
# 本次优化(ZTHK-17628)涉及的缓存 key(已在 UAT redis 实机确认)：
#   优化点1 期权基本信息缓存:        option-order-server:option:info:{symbol}
#   优化点2 期权沽空账户用户信息缓存: option-order-server:option:short:userinfo:{userUuid}
#   (另有普通用户信息缓存:           option-order-server:option:userinfo:{userUuid})
REDIS_KEY_PREFIX = "option-order-server:option:"
# 期权基本信息缓存 key 模板(symbol 为期权代码)
REDIS_KEY_OPTION_INFO = "option-order-server:option:info:{symbol}"
# 期权沽空账户用户信息缓存 key 模板(uuid 为客户 user_uuid 长号)
REDIS_KEY_SHORT_USERINFO = "option-order-server:option:short:userinfo:{uuid}"
# 普通期权用户信息缓存 key 模板
REDIS_KEY_USERINFO = "option-order-server:option:userinfo:{uuid}"


def env_summary() -> str:
    seed = ",".join(f"{h}:{p}" for h, p in REDIS_STARTUP_NODES)
    return (f"[环境={ENV}] base={BASE_URL} | kibana={KIBANA_BASE} | "
            f"es={ES_INDEX} | redis种子={seed}")
