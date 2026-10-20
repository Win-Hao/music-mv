#!/usr/bin/env python3
"""lyrics.srt → lyrics.js（window.LYRICS = [[开始秒, 结束秒, "这句"], …]），给合成页面用：
网页从本地读 srt 常被浏览器拦，转成 js 用 <script src="lyrics.js"> 引进来最稳。
    python3 scripts/srt2js.py lyrics.srt -o mv/lyrics.js [--offset -30.5]
--offset：MV 从歌的中间开始时，把时间整体挪（成片秒 = 歌里的秒 + offset）。只打印句数，不打印歌词。
"""
import argparse
import json
import re


def ts(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


ap = argparse.ArgumentParser()
ap.add_argument("srt")
ap.add_argument("-o", "--out", required=True)
ap.add_argument("--offset", type=float, default=0.0)
a = ap.parse_args()
rows = []
for b in re.split(r"\n\s*\n", open(a.srt, encoding="utf-8-sig").read().strip()):
    L = b.strip().splitlines()
    for i, l in enumerate(L):
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", l)
        if m:
            g = m.groups()
            s0, s1 = ts(*g[:4]) + a.offset, ts(*g[4:]) + a.offset
            txt = " ".join(L[i + 1:]).strip()
            if s1 > 0 and txt:
                rows.append([round(max(0, s0), 3), round(s1, 3), txt])
            break
with open(a.out, "w", encoding="utf-8") as f:
    f.write("window.LYRICS = " + json.dumps(rows, ensure_ascii=False) + ";\n")
print(f"{len(rows)} 句 → {a.out}")
