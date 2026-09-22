# -*- coding: utf-8 -*-
"""onebiji o_ 块（市场全览？）完整对象提取（临时脚本，跑完即删）。"""
import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
req = urllib.request.Request(
    "https://www.onebiji.com/hykb_tools/sjz/mrmm/tqc.php?immgj=0", headers={"User-Agent": UA})
page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
open(r"E:\WK\日常\.cache\onebiji_live.html", "w", encoding="utf-8").write(page)

print("页面长度", len(page))
# 「市场全览」关键词定位
for kw in ("市场全览", "全览", "交易行价", "行情"):
    for m in list(re.finditer(kw, page))[:3]:
        print(f"[{kw}] 上下文:", repr(page[max(0, m.start()-80):m.start()+120]))
    print("-" * 50)

# o_37100500001 完整对象（平衡花括号提取）
def extract_obj(anchor: str) -> str | None:
    idx = page.find(anchor)
    if idx < 0:
        return None
    start = page.find("{", idx)
    depth = 0
    for i in range(start, min(start + 4000, len(page))):
        if page[i] == "{":
            depth += 1
        elif page[i] == "}":
            depth -= 1
            if depth == 0:
                return page[start:i + 1]
    return None

for anchor in ('"o_37100500001"', '"t_37100500001"', '"o_37100300001"'):
    obj = extract_obj(anchor)
    print("=" * 20, anchor)
    if obj:
        try:
            parsed = json.loads(obj)
            for k, v in parsed.items():
                s = str(v)
                print(f"   {k}: {s[:90]}")
        except Exception as exc:
            print("  解析失败:", exc, obj[:400])
    else:
        print("  未找到")
