"""
公共配置模块
================
所有可以"统一配置"的字段都集中放在这里，各业务脚本(股票/期权/组合/碎股/CFD)
直接引用即可。如果某个业务需要"特殊化"某个字段，可以在对应业务文件里单独覆盖，
不影响其他业务。

配置分三层:
  1. 环境 & 鉴权     —— BASE_URL / AUTHORIZATION / 公共请求头
  2. 资金账号        —— 默认账号(股票/期权/组合/碎股) 与 CFD 专用账号
  3. 接口路径        —— 三大类接口的 下单/改单/撤单 路径集中登记
"""

# ============================ 1. 环境 & 鉴权 ============================
# UAT 测试环境地址
BASE_URL = "https://admin-sit.yxzq.com"

# uat
AUTHORIZATION = (
    "90A25FFBB05229F344673D99D401A27E4E4413ACC8A8A0D90C3B3961EFB2F42982D30C191FFDF937115E349E0362F0CC2FBB22DBE526F92D264448E4323297AF464CA3F04A0430CD9A2074BBC42C7AC7E2555F1DF3C696CC7D02D80653548E54405E50E0BF1DE3D1BCE5DF353D584394FA1BC44E85CFBA14189196E3EF5EFC13"
)

# 公共请求头(所有接口共用)。X-Request-Id 会在发送时自动生成，不在这里写死。
COMMON_HEADERS = {
    "Authorization": AUTHORIZATION,
    "X-Channel": "1",       # 渠道: 1-中台, 2-app
    "X-Client-Id": "2",     # APP 用户 ID
    "X-Dt": "t1",           # 设备类型: 1-安卓, 2-ios, 3-其它
    "X-Lang": "1",          # 语言类型: 1-简体, 2-繁体, 3-英文
    "X-Type": "1",          # app 类型: 1-友信智投, 2-uSmart, 3-其它
    "Content-Type": "application/json",
}


# ============================ 2. 资金账号 ============================
# 注意: HK(香港, admin-uat.yxzq.com) 与 SG(新加坡, usmartclient/jy-*.usmartsg.com)
#       是两套独立系统, TOKEN、资金账号、接口路径、请求体结构都不通用。
#       本目录是 HK 环境, 下面 HK 期权专区的字段才是 HK 期权中台下单接口在用的。

# 默认资金账号: 股票 / 期权 / 期权沽空 / 期权组合 / 碎股 共用
DEFAULT_FUND_ACCOUNT = "77000851"#"80019435"

# 沽空专用资金账号(沽空需要有沽空权限的账号，与默认账号不同)
# HK 期权沽空: 用默认账号下 OS 单会报 810006 "请先开户",
# 必须用下面这个带 S 前缀的沽空账号。买入平仓(OS + side=1)同样要用它。
SHORT_FUND_ACCOUNT = "S77000851"

# CFD 专用资金账号
CFD_FUND_ACCOUNT = ""#"70000033"

# 账户类型: 1-普通账户, 2-高级账户(统一下单/改单/撤单需要)
ACCOUNT_TYPE = 1


# ============================ 3. 接口路径 ============================
# 统一维护路径，避免散落在各个文件里。key 命名规则: <业务>_<动作>
PATHS = {
    # --- HK 期权中台(独立服务 option-order-server, 请求体与 SG 统一下单不同) ---
    # 注意: HK 网关对未注册路径统一返回 {"code":110003,"msg":"无权限"}(不是 404),
    #       路径写错时不会报"接口不存在", 别被误导。
    "option_create":  "/option-order-server/admin-api/option-single-order/v1",
    "option_replace": "/option-order-server/admin-api/option-replace-order/v1",
    "option_cancel":  "/option-order-server/admin-api/option-cancel-order/v1",

    # --- 以下 SG 统一下单路径是从 SG 脚本沿用过来的, 在 HK 网关上未验证通过 ---
    "unified_create":  "/order-center-sg/admin-api/unified-order-create/v1",
    "unified_replace": "/order-center-sg/admin-api/unified-order-replace/v1",
    "unified_cancel":  "/order-center-sg/admin-api/unified-order-cancel/v1",

    # --- 碎股 ---
    "odd_create": "/order-center-sg/admin-api/odd-order-create/v1",
    "odd_modify": "/order-center-sg/admin-api/odd-order-modify/v1",
    "odd_cancel": "/order-center-sg/admin-api/odd-order-cancel/v1",

    # --- CFD ---
    "cfd_create":  "/order-center-sg/admin-api/cfd-order-create/v1",
    "cfd_replace": "/order-center-sg/admin-api/cfd-order-replace/v1",
    "cfd_cancel":  "/order-center-sg/admin-api/cfd-order-cancel/v1",
}


def url_for(path_key: str) -> str:
    """根据 PATHS 的 key 拼出完整 URL。路径未登记时给出明确提示。"""
    path = PATHS[path_key]
    if not path:
        raise ValueError(
            f"接口路径 PATHS['{path_key}'] 尚未配置, 请把接口文档上的路径填到 common/config.py"
        )
    return BASE_URL + path


# ============================ 4. HK 期权中台专区 ============================
# 下单 POST /option-order-server/admin-api/option-single-order/v1
#   OptionSingleOrderAdminRequest
#   必填: capitalAccount / entrustType / orderType / requestId / side / symbol
#   选填: brokerAccount / businessType / holdId / price / qty / sessionType
#          / transactionPassage
# 改单 POST /option-order-server/admin-api/option-replace-order/v1
#   OptionReplaceAdminRequest: requestId(必填) / orderId(int64) / price / qty
# 撤单 POST /option-order-server/admin-api/option-cancel-order/v1
#   OptionOrderCancelAdminRequest: orderId(int64) / isForceCancel / requestId
# 改单撤单都不带 capitalAccount, 只认 orderId(int64, 别传字符串)。
# 下面枚举值是在 UAT 上逐个实测出来的(非法值统一报 400 "数据字典校验失败")。

# 资金账号(HK 独立账号体系, 与 SG 的 fundAccount 不是同一套)
CAPITAL_ACCOUNT = "77000851"

# 沽空资金账号(businessType=OS 时用, 含 沽空开仓 与 买入平仓)
# 与上面的 SHORT_FUND_ACCOUNT 同一个值, 这里只是给 HK 期权一个统一命名。
SHORT_CAPITAL_ACCOUNT = SHORT_FUND_ACCOUNT

# 报盘账号(brokerAccount, 选填; AVS UAT 报盘账号见需求图: USHK_AVSUAT_RQD_001)
BROKER_ACCOUNT = None

# businessType 业务类型(字符串): O-期权(缺省值), OS-期权沽空
BUSINESS_TYPE_OPTION = "O"
BUSINESS_TYPE_OPTION_SHORT = "OS"

# entrustType 委托类型: 实测仅 1、2 通过数据字典校验, 常规下单用 1
ENTRUST_TYPE_NORMAL = 1

# orderType 订单类型: 1-市价, 2-限价
# 盘前/盘前+盘中只支持限价单; 市价单在 US 期权上还会被流动性规则拦(800040)
ORDER_TYPE_MARKET = 1
ORDER_TYPE_LIMIT = 2

# side 买卖方向: 1-买入, 2-卖出(需有持仓, 否则 830015 提示走沽空)
SIDE_BUY = 1
SIDE_SELL = 2

# sessionType 交易时段: 0-盘中, 1-仅盘前, 10-盘前+盘中
# 只有这三个值合法, 其它值报 500 "不支持的交易时段";
# 非盘前时段送 1/10 会被时间窗口拦: 801116 "当前时段不支持盘前期权交易"
SESSION_TYPE_REGULAR = 0
SESSION_TYPE_PRE_MARKET = 1
SESSION_TYPE_PRE_AND_REGULAR = 10

# transactionPassage 交易通道: 不传则由服务端按"持仓/在途订单/全局设置"选通道,
# AVS 场景可显式传 "AVS"
TRANSACTION_PASSAGE_AVS = "AVS"
