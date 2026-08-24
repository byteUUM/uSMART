"""
Redis 缓存辅助模块（3.5 用户信息缓存 / 3.6 缓存刷新 使用）
============================================================
用于验证:
  - 缓存是否写入、TTL 是否为 8 小时
  - 资金账号 -> 客户号 映射 key 是否存在
  - 清空缓存后是否回源
  - 变更后缓存是否被刷新/删除

依赖: pip install redis
服务信息来自 png/redis与rebbitmq服务信息.png
"""
from common.config import (
    CACHE_EXPECT_TTL_HOURS,
    CACHE_KEY_KEYWORDS,
    REDIS_NODES,
    REDIS_PASSWORD,
    REDIS_TIMEOUT,
)

_client = None


def get_client():
    """获取 Redis 集群客户端(懒加载, 单例)。"""
    global _client
    if _client is not None:
        return _client
    try:
        from redis.cluster import ClusterNode, RedisCluster
    except ImportError:
        raise RuntimeError("未安装 redis 库，请先执行: pip install redis")

    nodes = [ClusterNode(host, port) for host, port in REDIS_NODES]
    _client = RedisCluster(
        startup_nodes=nodes,
        password=REDIS_PASSWORD,
        socket_timeout=REDIS_TIMEOUT,
        decode_responses=True,
    )
    return _client


def scan_keys(pattern: str, limit: int = 200):
    """按 pattern 扫描 key(集群模式会遍历所有主节点)。"""
    client = get_client()
    keys = []
    for key in client.scan_iter(match=pattern, count=100):
        keys.append(key)
        if len(keys) >= limit:
            break
    print(f"[Redis] pattern={pattern} 命中 {len(keys)} 个 key: {keys[:20]}")
    return keys


def find_user_keys(account_or_client_id: str):
    """按账号/客户号模糊查找用户信息缓存 key(key 前缀未知时用)。"""
    found = []
    for kw in CACHE_KEY_KEYWORDS:
        found += scan_keys(f"*{kw}*{account_or_client_id}*")
        found += scan_keys(f"*{kw}*")
    return sorted(set(found))


def get_value(key: str):
    """读取 key 的值。"""
    value = get_client().get(key)
    print(f"[Redis] GET {key} -> {value}")
    return value


def get_ttl(key: str):
    """读取 key 剩余 TTL(秒)。-1 表示永不过期, -2 表示不存在。"""
    ttl = get_client().ttl(key)
    print(f"[Redis] TTL {key} -> {ttl}s ({ttl / 3600:.2f}h)" if ttl > 0
          else f"[Redis] TTL {key} -> {ttl}")
    return ttl


def check_ttl_is_8h(key: str, tolerance_min: int = 10):
    """校验 TTL 接近预期的 8 小时。"""
    ttl = get_ttl(key)
    expect = CACHE_EXPECT_TTL_HOURS * 3600
    if ttl <= 0:
        print(f"[校验] {key} 无 TTL [FAIL]")
        return False
    ok = abs(ttl - expect) <= tolerance_min * 60
    print(f"[校验] TTL 预期 {expect}s 实际 {ttl}s -> {'[PASS]' if ok else '[FAIL]'}")
    return ok


def delete_keys(keys):
    """删除指定 key(模拟缓存失效/清空缓存)。"""
    if isinstance(keys, str):
        keys = [keys]
    client = get_client()
    count = 0
    for key in keys:
        count += client.delete(key)
    print(f"[Redis] 已删除 {count} 个 key: {keys}")
    return count


def set_raw_value(key: str, value: str, ttl_seconds: int = None):
    """
    直接写入原始值(用于 CACHE-05 旧格式兼容、CACHE-08 映射不一致 等构造场景)。
    """
    client = get_client()
    client.set(key, value, ex=ttl_seconds)
    print(f"[Redis] SET {key} = {value} (ttl={ttl_seconds})")
