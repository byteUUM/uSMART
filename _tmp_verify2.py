# -*- coding: utf-8 -*-
"""复测 option-order-detail/v1 的 OS 单 orderQty/Price/Amount 返 0 bug, UAT+SIT 都测"""
import io, sys, uuid
from decimal import Decimal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import requests
sys.path.insert(0, r"d:\code-3")
from db import query, use_env

ENVS = {
    "SIT": {
        "base": "https://admin-sit.yxzq.com/option-order-server/admin-api/option-order-detail/v1",
        "cfg": r"d:\code-3\avs_option\hk_avs_sit",
        "dbenv": "HK_SIT",
        "cases": [
            ("OS 沽空/买入平仓", 1150828142044127232, "1150828142044127233"),
            ("O  普通(对照)",    1150829756956024832, "1150829756956024833"),
        ],
    },
    "UAT": {
        "base": "https://admin-uat.yxzq.com/option-order-server/admin-api/option-order-detail/v1",
        "cfg": r"d:\code-3\avs_option\hk_avs_uat",
        "dbenv": "HK_UAT",
        "cases": [
            ("OS 买入平仓",     1150822240485662720, "1150822240485662721"),
            ("O  普通(对照)",    1150824830682292224, "1150824830682292225"),
        ],
    },
}

def num(v):
    try:
        return Decimal(str(v))
    except Exception:
        return v

for envname, cfg in ENVS.items():
    sys.path.insert(0, cfg["cfg"])
    # 每个环境的 config 是不同文件, 用 importlib 隔离
    import importlib.util
    spec = importlib.util.spec_from_file_location("cfg_%s" % envname, cfg["cfg"] + r"\common\config.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    AUTH = m.AUTHORIZATION
    use_env(cfg["dbenv"])
    print("\n" + "#" * 78)
    print("# %s   %s" % (envname, cfg["base"]))
    print("#" * 78)
    for tag, oid, no in cfg["cases"]:
        h = {"Accept": "application/json, text/plain, */*", "Authorization": AUTH,
             "Content-Type": "application/json;charset=UTF-8", "Desensitization": "1",
             "Origin": cfg["base"].split("/option-order")[0],
             "Referer": cfg["base"].split(".com")[0] + ".com/admin/index.html",
             "X-Request-Id": str(uuid.uuid4()), "User-Agent": "Mozilla/5.0"}
        try:
            r = requests.post(cfg["base"], headers=h, json={"orderNo": no}, timeout=30)
            j = r.json()
        except Exception as e:
            print("  [%s] 请求失败 %s" % (tag, str(e)[:100])); continue
        d = j.get("data") or {}
        db = query("""select business_type, order_qty, order_price, order_amount
                      from option_order_server.option_order where id=%s""", (oid,))
        dbr = db[0] if db else {}
        print("\n  %s  no=%s  code=%s biz=%s" % (tag, no, j.get("code"), dbr.get("business_type")))
        rows = [("orderQty","order_qty"),("orderPrice","order_price"),("orderAmount","order_amount")]
        allok = True
        for ak, dk in rows:
            av, dv = num(d.get(ak)), num(dbr.get(dk))
            ok = (av == dv)
            allok = allok and ok
            print("     %-12s 接口=%-10s 库=%-12s %s" % (ak, d.get(ak), dbr.get(dk), "OK" if ok else "!! 不一致"))
        print("     ==> %s" % ("全部一致(已修复)" if allok else "仍有返0/不一致(未修复)"))
