"""
RabbitMQ 辅助模块（RFS-02 开通资金账号消息 使用）
=================================================
用于手工投递"用户开通资金账号"消息，验证消费后是否刷新用户信息缓存。

依赖: pip install pika
服务信息来自 png/redis与rebbitmq服务信息.png

注意: MQ_EXCHANGE / MQ_ROUTING_KEY / 消息体结构 接口文档未提供，
     需先向开发确认后填入 config.py 再使用本模块。
"""
import json

from common.config import (
    MQ_ADDRESSES,
    MQ_EXCHANGE,
    MQ_PASSWORD,
    MQ_ROUTING_KEY,
    MQ_USERNAME,
)


def publish(message: dict, exchange: str = None, routing_key: str = None):
    """向 RabbitMQ 投递一条消息。"""
    exchange = exchange if exchange is not None else MQ_EXCHANGE
    routing_key = routing_key if routing_key is not None else MQ_ROUTING_KEY
    if not routing_key:
        raise ValueError("MQ_ROUTING_KEY 未配置，请先在 config.py 中补充")

    try:
        import pika
    except ImportError:
        raise RuntimeError("未安装 pika 库，请先执行: pip install pika")

    credentials = pika.PlainCredentials(MQ_USERNAME, MQ_PASSWORD)
    host, port = MQ_ADDRESSES[0]
    params = pika.ConnectionParameters(host=host, port=port, credentials=credentials)

    connection = pika.BlockingConnection(params)
    try:
        channel = connection.channel()
        body = json.dumps(message, ensure_ascii=False)
        channel.basic_publish(exchange=exchange, routing_key=routing_key, body=body)
        print(f"[MQ] 已投递到 exchange={exchange} routing_key={routing_key}")
        print("[MQ] 消息体:", body)
    finally:
        connection.close()
