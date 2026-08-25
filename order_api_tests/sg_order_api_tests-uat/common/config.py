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
# SIT 测试环境地址
BASE_URL = "https://usmartclient-uat.usmartsg.com"

# uat
AUTHORIZATION = (
    "90A25FFBB05229F344673D99D401A27E703FBDAE0229450FAB9DBCEBD7A5953AB99372D769E948107A0016AB7FBCA66BADF2ECA84CF5C5C0D5458B6CFD1CD576268E02D4C278E2E9DFB345990A36FD10C82A8006C18FF836A5328AA7246F94CD405E50E0BF1DE3D1BCE5DF353D5843942F7B726CF2210480B688023D01550DD7"
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
# 默认资金账号: 股票 / 期权 / 期权沽空 / 期权组合 / 碎股 共用
DEFAULT_FUND_ACCOUNT = "80019435"

# 股票沽空专用资金账号(沽空需要有沽空权限的账号，与默认账号不同)
SHORT_FUND_ACCOUNT = "80019713"

# CFD 专用资金账号
CFD_FUND_ACCOUNT = "70000027"#"70000033"

# 账户类型: 1-普通账户, 2-高级账户(统一下单/改单/撤单需要)
ACCOUNT_TYPE = 1


# ============================ 3. 接口路径 ============================
# 统一维护路径，避免散落在各个文件里。key 命名规则: <业务>_<动作>
PATHS = {
    # --- 统一下单(股票/股票沽空/期权/期权沽空/组合期权) ---
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
    """根据 PATHS 的 key 拼出完整 URL。"""
    return BASE_URL + PATHS[path_key]
