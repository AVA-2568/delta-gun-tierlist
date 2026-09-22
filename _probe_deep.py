# -*- coding: utf-8 -*-
"""彻查 onebiji M995 全部出现 + orzice ly_data 内嵌数据（临时脚本，跑完即删）。"""
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

print("=" * 30, "onebiji: M995 全部出现")
req = urllib.request.Request(
    "https://www.onebiji.com/hykb_tools/sjz/mrmm/tqc.php?immgj=0", headers={"User-Agent": UA})
page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
seen = []
for m in re.finditer(r'37100500001', page):
    chunk = page[max(0, m.start() - 120):m.start() + 700]
    price = re.search(r'"price2?":"?([\d,]+)"?', chunk)
    hour = re.search(r'"price_hour2?":"?([\d,]+)"?', chunk)
    key = re.search(r'"([to])_37100500001"', chunk)
    kind = re.search(r'(今日|昨日|\d+日|交易|商人|周期)', chunk)
    seen.append((m.start(), key.group(1) if key else "-",
                 price.group(1) if price else "-", hour.group(1) if hour else "-"))
for s in seen[:12]:
    print("  pos=%s 块=%s price=%s price_hour=%s" % s)
print("出现总数:", len(seen))

print("=" * 30, "orzice: ly_data")
req2 = urllib.request.Request("https://orzice.com/v/ammo", headers={"User-Agent": UA})
p2 = urllib.request.urlopen(req2, timeout=30).read().decode("utf-8", "replace")
m = re.search(r'ly_data\s*=\s*(.{0,3000})', p2, re.S)
if m:
    print(m.group(1)[:2500])
else:
    print("ly_data 未找到；搜 var 赋值：")
    for mm in list(re.finditer(r"var\s+(\w+)\s*=", p2))[:30]:
        print("  var", mm.group(1))
