"""
数据库校验模块
==============
按 orderId 从 HK_SIT 库查询期权订单/成交数据，供测试用例与接口返回、页面渲染做交叉比对。

数据源（探查确认）：
  - 实时订单   option_order_server.option_order          (id = orderId)  今日 tab 数据在此
  - 实时成交   option_order_server.option_order_clinch    (order_id)
  - 历史订单   option_order_server.option_order_history   (id = orderId)  历史 tab 归档订单
  - 历史成交   option_order_server.option_order_clinch_history (order_id)  历史 tab 归档成交
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, _ROOT)
from db import query, use_env  # noqa: E402

use_env("HK_SIT")

UUID = "876169404924960768"  # 资金账号 77000851 对应的 user_uuid


def get_order(order_id):
    """从实时订单表查一条；查不到再查历史订单表。返回 dict 或 None，并标注来源。"""
    r = query(
        "select * from option_order_server.option_order where id=%s", (order_id,)
    )
    if r:
        r[0]["_src"] = "option_order"
        return r[0]
    r = query(
        "select * from option_order_server.option_order_history where id=%s", (order_id,)
    )
    if r:
        r[0]["_src"] = "option_order_history"
        return r[0]
    return None


def get_clinch(order_id):
    """查成交流水（实时 + 历史合并），返回 list[dict]。"""
    rows = query(
        "select clinch_time, clinch_price, clinch_qty, clinch_amount, status "
        "from option_order_server.option_order_clinch where order_id=%s order by clinch_time",
        (order_id,),
    )
    if rows:
        return rows
    return query(
        "select clinch_time, clinch_price, clinch_qty, clinch_amount, status "
        "from option_order_server.option_order_clinch_history where order_id=%s order by clinch_time",
        (order_id,),
    )


def count_orders(realtime=True):
    """统计该客户订单数。realtime=True 查实时表，False 查历史表。"""
    table = "option_order" if realtime else "option_order_history"
    r = query(
        f"select count(*) as cnt from option_order_server.{table} where user_uuid=%s",
        (UUID,),
    )
    return int(r[0]["cnt"]) if r else -1


def count_clinch(realtime=True):
    """统计该客户成交流水数。"""
    table = "option_order_clinch" if realtime else "option_order_clinch_history"
    r = query(
        f"select count(*) as cnt from option_order_server.{table} where user_uuid=%s",
        (UUID,),
    )
    return int(r[0]["cnt"]) if r else -1


if __name__ == "__main__":
    # 自检
    print("实时订单数:", count_orders(True))
    print("历史订单数:", count_orders(False))
    print("实时成交流水数:", count_clinch(True))
    print("历史成交流水数:", count_clinch(False))
