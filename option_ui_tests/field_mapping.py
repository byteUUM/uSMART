"""
字段映射与枚举翻译
==================
记录期权四个 tab「页面列 <-> 接口字段 <-> DB 字段」的映射，以及枚举值的中文翻译。
来源：对 SIT 环境真实接口返回、页面渲染、DB option_order 表逐行核对得到。

用途：测试用例据此把「接口返回值 / DB 值」翻译成「页面应显示的文本」，再和页面实际渲染比对。
"""

# ---------------------------- 枚举翻译 ----------------------------
# 市场 marketType
MARKET_TYPE = {51: "美股"}  # 已知 51=美股；其它值待补
# 币种 currency
CURRENCY = {0: "人民币", 1: "美元", 2: "港币"}
# 交易时段 sessionType
SESSION_TYPE = {0: "仅盘中", 1: "仅盘前", 2: "盘后", 3: "暗盘", 10: "盘前+盘中"}
# 买卖方向 orderSide
ORDER_SIDE = {1: "买入", 2: "卖出"}
# 委托方式 entrustType（1电话委托 2Internet委托）
ENTRUST_TYPE = {1: "电话委托", 2: "Internet委托"}
# 委托属性 orderType（1市价 2限价）
ORDER_TYPE = {1: "市价单", 2: "限价单"}
# 强制平仓 isStopOut
STOP_OUT = {True: "是", False: "否", 0: "否", 1: "是"}

# 订单内部状态 internal_status/orderStatus（来自表字段字典）
ORDER_STATUS = {
    100: "等待冻结", 105: "冻结中", 150: "待提交上手", 155: "提交上手中",
    160: "上手报单中", 250: "废单等待解冻", 300: "等待订单成交",
    350: "等待订单成交(已部分成交)", 400: "等待改单", 450: "等待订单撤单",
    451: "等待上手撤单", 480: "成交中", 800: "部成已撤", 810: "订单完成(全部成交)",
    820: "结束(废单)", 825: "结束(下单失败)", 830: "结束(撤单)",
    840: "结束(日末撤单)", 850: "上手撤单",
}


# ---------------------------- 列 -> 接口字段 映射 ----------------------------
# 今日成交 / 历史成交（成交类，17 列）
DEAL_COLUMN_TO_API = {
    "委托ID": "orderNo",
    "成交时间": "clinchTime",
    "下单时间": "createTime",
    "市场": ("marketType", MARKET_TYPE),
    "币种": ("currency", CURRENCY),
    "交易时段": ("sessionType", SESSION_TYPE),
    "证券名称": "optionName",
    "证券代码": "optionCode",
    "业务类型": "optionBusinessType",
    "买卖方向": ("orderSide", ORDER_SIDE),
    "委托方式": ("entrustType", ENTRUST_TYPE),
    "委托属性": ("orderType", ORDER_TYPE),
    "成交数量": "clinchQty",
    "成交价格": "clinchAvgPrice",
    "成交金额": "clinchAmount",
    # 页面「交易通道」列实际渲染的是 channelCode（形如 AVS-30%-USHK_AVS_RQD_30S），
    # 不是 channelName（AVS）。经实测确认。
    "交易通道": "channelCode",
    "强制平仓": ("isStopOut", STOP_OUT),
}

# 今日委托 / 历史委托（委托类）关键列 -> 接口字段
ENTRUST_COLUMN_TO_API = {
    "委托ID": "orderNo",
    "委托时间": "createTime",
    "市场": ("marketType", MARKET_TYPE),
    "币种": ("currency", CURRENCY),
    "证券名称": "optionName",
    "证券代码": "optionCode",
    "业务类型": "optionBusinessType",
    "买卖方向": ("orderSide", ORDER_SIDE),
    "委托方式": ("entrustType", ENTRUST_TYPE),
    "委托属性": ("orderType", ORDER_TYPE),
    "交易时段": ("sessionType", SESSION_TYPE),
    "委托数量": "orderQty",
    "委托价格": "orderPrice",
    "委托状态": ("orderStatus", ORDER_STATUS),
    "交易通道": "channelCode",
    "强制平仓": ("isStopOut", STOP_OUT),
}


def api_expected_text(column: str, row: dict, mapping: dict) -> str:
    """
    根据映射，把接口返回的一行 row 翻译成某列「页面应显示的文本」。
    返回 None 表示该列无映射（跳过比对）。
    """
    spec = mapping.get(column)
    if spec is None:
        return None
    if isinstance(spec, tuple):
        field, enum = spec
        val = row.get(field)
        if val is None:
            return ""
        return str(enum.get(val, val))
    # 直接字段
    val = row.get(spec)
    return "" if val is None else str(val)
