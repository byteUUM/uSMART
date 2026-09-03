"""
日志查询 (HK_SIT)
==================
按关键词查 option-order-server 的日志, 并自动顺着 traceId 拉出完整调用链。

用法:
  python query_log.py <关键词>                    查最近24小时
  python query_log.py <关键词> --hours 3          指定回溯小时数
  python query_log.py <关键词> --trace            命中后自动按traceId拉完整链路
  python query_log.py <关键词> --error            只看 ERROR/WARN
  python query_log.py <关键词> --index uat        查 UAT 索引
  python query_log.py <关键词> --full             打印完整 message(不截断)

例:
  python query_log.py 2d42ec59-56c4-4ae6-9d71-1652a8447e4f --trace
  python query_log.py 1147924237866057728 --hours 2
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common.kibana import search, extract_trace_ids, INDEX_SIT, INDEX_UAT


def show(rows, full=False, only_error=False):
    n = 0
    for r in rows:
        lvl = (r["level"] or "").upper()
        if only_error and lvl not in ("ERROR", "WARN"):
            continue
        n += 1
        msg = r["message"]
        if not full:
            msg = msg.replace("\n", " | ")
            if len(msg) > 400:
                msg = msg[:400] + " ...(--full 看全部)"
        mark = " ★" if lvl == "ERROR" else ""
        print("")
        print("[%s] %-5s%s" % (r["time"], lvl, mark))
        print("   %s" % msg)
    if n == 0:
        print("   (无匹配记录)")
    return n


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    keyword = args[0]
    hours = 24
    do_trace = "--trace" in args
    only_error = "--error" in args
    full = "--full" in args
    index = INDEX_UAT if "uat" in args else INDEX_SIT
    if "--hours" in args:
        try:
            hours = float(args[args.index("--hours") + 1])
        except (IndexError, ValueError):
            pass

    end = datetime.now()
    start = end - timedelta(hours=hours)
    print("=" * 92)
    print("检索词: %s" % keyword)
    print("索引  : %s" % index)
    print("时间  : %s ~ %s (北京时间, 近%s小时)" %
          (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), hours))
    print("=" * 92)

    try:
        rows = search(keyword, index=index, start=start, end=end, order="asc")
    except Exception as e:
        print("查询失败: %s: %s" % (type(e).__name__, e))
        return

    print("命中 %d 条" % len(rows))
    show(rows, full=full, only_error=only_error)

    if do_trace and rows:
        tids = extract_trace_ids(rows)
        print("")
        print("=" * 92)
        print("从日志中提取到 traceId: %s" % (tids or "(无)"))
        print("=" * 92)
        for tid in tids[:3]:
            print("")
            print("-" * 92)
            print("按 traceId=%s 拉完整调用链" % tid)
            print("-" * 92)
            try:
                tr = search(tid, index=index, start=start, end=end, order="asc")
                print("命中 %d 条" % len(tr))
                show(tr, full=full, only_error=only_error)
            except Exception as e:
                print("  查询失败: %s" % e)


if __name__ == "__main__":
    main()
