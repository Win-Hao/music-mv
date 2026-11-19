#!/usr/bin/env python3
"""把歌词里每个汉字的笔画中线（hanzi-writer-data，写字类画风按笔顺一笔笔写歌词用）先下好，存成页面用的 glyphs.js：
渲染时不联网，几个进程拿到的一模一样（从网上现取，有的进程取到、有的没取到，同一个字前后帧就不一样）。
    python3 scripts/glyphs.py lyrics.srt -o mv/glyphs.js          # 页面里 <script src="glyphs.js"></script>，kit.js 的 MV.glyphs 先用它
    python3 scripts/glyphs.py mv/lyrics.js -o mv/glyphs.js        # lyrics.js、纯文本文件也行
只打印字数和取不到的是第几句第几个字，不打印歌词。数据是 hanzi-writer-data（Arphic Public License），存下来的文件留在你自己的项目里用。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import parse_srt  # noqa: E402

URL = "https://cdn.jsdelivr.net/npm/hanzi-writer-data@2.0.1/"
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def lines_of(path):
    if path.lower().endswith(".srt"):
        return [t for _, _, t in parse_srt(path)]
    text = open(path, encoding="utf-8-sig").read()
    if path.lower().endswith(".js") and "LYRICS" in text:
        return [r[2] for r in json.loads(text[text.index("=") + 1:text.rindex(";")])]
    return text.splitlines()


def fetch(ch, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(URL + urllib.parse.quote(ch) + ".json", timeout=30) as r:
                return ch, json.load(r)["medians"]
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ch, None          # 数据里没有这个字
        except Exception:
            time.sleep(1 + k)
    return ch, False                     # 网络问题


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lyrics", help="lyrics.srt、lyrics.js 或纯文本")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    lines = lines_of(a.lyrics)
    chars = sorted({c for ln in lines for c in ln if HAN.match(c)})
    with ThreadPoolExecutor(8) as ex:
        got = dict(ex.map(fetch, chars))
    ok = {c: m for c, m in got.items() if m}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("// 汉字笔画中线，hanzi-writer-data（Arphic Public License），scripts/glyphs.py 生成\n")
        f.write("window.GLYPHS = " + json.dumps(ok, ensure_ascii=False, separators=(",", ":")) + ";\n")
    def where(c):
        for i, ln in enumerate(lines, 1):
            if c in ln:
                return f"第 {i} 句第 {ln.index(c) + 1} 个字"
    none = [c for c, m in got.items() if m is None]
    lost = [c for c, m in got.items() if m is False]
    print(f"{len(chars)} 个不同的汉字，存了 {len(ok)} 个 → {a.out}")
    if none:
        print(f"数据里没有 {len(none)} 个（要另外画）：" + "、".join(where(c) for c in none[:10]))
    if lost:
        print(f"⚠ 网络问题没取到 {len(lost)} 个，再跑一次：" + "、".join(where(c) for c in lost[:10]))
        sys.exit(1)


if __name__ == "__main__":
    main()
