"""
Redis 缓存校验工具(按 config 环境连对应 redis cluster)
=====================================================
本次优化核心是"加缓存"，用它来验证：
  - 缓存 key 是否生成、内容是否正确(与查库一致)
  - 命中缓存 / 回源查库
  - 缓存失效(删 key 后回源)
  - 扫描 option-order-server:option:* 前缀发现本次新增的缓存 key

依赖: redis-py(>=4.1, 内置 RedisCluster)。已装到 .venv。
注意: redis 无密码时 password 传 None。若连不上多半是网络不通(需在能访问 10.60.6.x 的机器上跑)。
"""
from redis.cluster import RedisCluster, ClusterNode

from common.config import (
    REDIS_STARTUP_NODES, REDIS_PASSWORD, REDIS_KEY_PREFIX, ENV,
    REDIS_KEY_OPTION_INFO, REDIS_KEY_SHORT_USERINFO, REDIS_KEY_USERINFO,
)

_client = None


def get_client():
    """获取(缓存的)RedisCluster 连接。"""
    global _client
    if _client is None:
        nodes = [ClusterNode(h, p) for h, p in REDIS_STARTUP_NODES]
        _client = RedisCluster(
            startup_nodes=nodes,
            password=REDIS_PASSWORD,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _client


def ping() -> bool:
    try:
        get_client().ping()
        print(f"[redis-{ENV}] 连接成功")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[redis-{ENV}] 连接失败: {type(e).__name__}: {e}")
        return False


def scan_keys(pattern: str = None, limit: int = 200):
    """扫描匹配 pattern 的 key(cluster 会遍历所有主节点)。默认扫期权前缀。"""
    pattern = pattern or (REDIS_KEY_PREFIX + "*")
    rc = get_client()
    found = []
    # RedisCluster.scan_iter 会跨所有主节点
    for k in rc.scan_iter(match=pattern, count=100):
        found.append(k)
        if len(found) >= limit:
            break
    return found


def get_value(key: str):
    """读一个 key 的值。自动识别 string / hash / 其它类型。"""
    rc = get_client()
    if not rc.exists(key):
        return None, "not_exist"
    t = rc.type(key)
    if t == "string":
        return rc.get(key), t
    if t == "hash":
        return rc.hgetall(key), t
    if t == "list":
        return rc.lrange(key, 0, -1), t
    if t == "set":
        return list(rc.smembers(key)), t
    return f"<{t}>", t


def ttl(key: str):
    return get_client().ttl(key)


def delete(key: str) -> int:
    """删除 key(用于验证缓存失效后能回源)。返回删除数量。"""
    return get_client().delete(key)


def dump_keys(pattern: str = None, limit: int = 50):
    """打印匹配的 key 及其类型、ttl、值(截断)，便于人工核对缓存内容。"""
    keys = scan_keys(pattern, limit=limit)
    print(f"[redis-{ENV}] 匹配 '{pattern or REDIS_KEY_PREFIX + '*'}' 共 {len(keys)} 个 key:")
    for k in keys:
        val, t = get_value(k)
        sval = str(val)
        if len(sval) > 300:
            sval = sval[:300] + " ...(截断)"
        print(f"  - {k}  [type={t}, ttl={ttl(k)}]")
        print(f"      {sval}")
    return keys


# ============================ 本次优化(ZTHK-17628)专用 ============================

def option_info_key(symbol: str) -> str:
    return REDIS_KEY_OPTION_INFO.format(symbol=symbol)


def short_userinfo_key(uuid) -> str:
    return REDIS_KEY_SHORT_USERINFO.format(uuid=uuid)


def userinfo_key(uuid) -> str:
    return REDIS_KEY_USERINFO.format(uuid=uuid)


def get_option_info(symbol: str):
    """优化点1：读期权基本信息缓存。返回 (值, 类型, ttl)。"""
    key = option_info_key(symbol)
    val, t = get_value(key)
    return val, t, (ttl(key) if val is not None else None)


def get_short_userinfo(uuid):
    """优化点2：读期权沽空账户用户信息缓存。返回 (值, 类型, ttl)。"""
    key = short_userinfo_key(uuid)
    val, t = get_value(key)
    return val, t, (ttl(key) if val is not None else None)


def evict_option_info(symbol: str) -> int:
    """删期权基本信息缓存(验证下单后能回源查库并重建缓存)。"""
    return delete(option_info_key(symbol))


def evict_short_userinfo(uuid) -> int:
    """删沽空账户用户信息缓存。"""
    return delete(short_userinfo_key(uuid))
