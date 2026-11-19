#!/usr/bin/env python3
"""lyrics.srt → lyrics.js（window.LYRICS = [[开始秒, 结束秒, "这句"], …]），给 MV 页面用：
网页从本地读 srt 常被浏览器拦，转成 js 用 <script src="lyrics.js"> 引进来最稳。
    python3 scripts/srt2js.py lyrics.srt -o mv/lyrics.js [--offset -30.5]
    python3 scripts/srt2js.py lyrics.srt -o mv/lyrics.js --words lyrics-words.json   # 带上逐字时间：每句多一项，每个字开唱的秒
    python3 scripts/srt2js.py lyrics.srt -o mv/lyrics.js --words song.json           # Whisper 加 --word_timestamps True 出的 json 也行
--offset：MV 从歌的中间开始时，把时间整体挪（成片秒 = 歌里的秒 + offset）。--words 里的时间和 lyrics.srt 一样是歌里的秒，跟着一起挪。
--words 给了，每句变成 [开始, 结束, "这句", [第 1 个字开唱的秒, 第 2 个…]]：kit.js 的 MV.lyricAt 就按每个字自己的时间出字；
没给逐字时间的句子还是三项，照旧一个字一个字按固定间隔出。
字位：中文一个字一个字位，连着的英文字母、数字算一个词占一个字位；空格、标点不占字位（kit.js 的 MV.lyricUnits 是同一套拆法）。
--words 认两种：
  1. 自己整理的 lyrics-words.json：{"lines": [{"chars": [{"text": "字", "t0": 12.34}, …]}, …]}，一句一项、和 lyrics.srt 同样的句数和顺序
     （text 也可以写成 ch；t1 有就留着不用）。字和这句对不上（错字、多字少字）的，按下面第 2 种的办法对
  2. Whisper 的 json（segments 里的 words：word、start、end）：一个词有几个字就把这个词的时间平分；再按字和 lyrics.srt 每句
     （句子前后放宽 1 秒）比对，对上的字用它的时间，没对上的（Whisper 听错、srt 改过的字）按前后对上的字插值
打印每句的序号和起止（给了 --offset 就是成片秒），给了 --words 再打印每句几个字有自己的时间；不打印歌词。
"""
import argparse
import difflib
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, parse_srt  # noqa: E402

LATIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’]*")


def units(text):
    """一句歌词拆成字位（要唱、有自己时间的单位）：中文一个字一个，连着的英文字母、数字一个词一个；空格、标点不算"""
    out, i = [], 0
    while i < len(text):
        m = LATIN.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = text[i]
        if not (ch.isspace() or unicodedata.category(ch)[0] in "PSZ"):
            out.append(ch)
        i += 1
    return out


def norm(u):
    return u.lower()


def timeline_from_whisper(j):
    """Whisper json → [(字位, 开始秒)]：一个词几个字位就把这个词的时间平分"""
    out = []
    for sg in j.get("segments", []):
        for w in sg.get("words", []) or []:
            us = units(str(w.get("word", "")))
            s, e = float(w.get("start", 0)), float(w.get("end", w.get("start", 0)))
            for k, u in enumerate(us):
                out.append((u, s + (e - s) * k / max(1, len(us))))
    return out


def lines_from_json(j):
    """自己整理的格式 → 每句 [(字位, 开始秒)]"""
    rows = j.get("lines", j) if isinstance(j, dict) else j
    out = []
    for L in rows:
        cs = L.get("chars", []) if isinstance(L, dict) else L
        line = []
        for c in cs:
            txt = str(c.get("text", c.get("ch", "")))
            t0 = c.get("t0", c.get("start"))
            if t0 is None:
                continue
            us = units(txt)
            for u in us or ([txt] if txt.strip() else []):
                line.append((u, float(t0)))
        out.append(line)
    return out


def align(us, cand, s0, s1):
    """srt 这句的字位 us 对上候选 [(字位, 秒)]：对上的用候选的时间，没对上的按前后插值，夹在 [s0, s1] 里、不往回走。返回 (时间表, 对上几个)"""
    t = [None] * len(us)
    sm = difflib.SequenceMatcher(None, [norm(u) for u in us], [norm(c[0]) for c in cand], autojunk=False)
    hit = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            t[blk.a + k] = cand[blk.b + k][1]
            hit += 1
    known = [(i, x) for i, x in enumerate(t) if x is not None]
    for i in range(len(us)):
        if t[i] is not None:
            continue
        prev = next(((j, x) for j, x in reversed(known) if j < i), None)
        nxt = next(((j, x) for j, x in known if j > i), None)
        a = prev if prev else (-1, s0)
        b = nxt if nxt else (len(us), s1)
        t[i] = a[1] + (b[1] - a[1]) * (i - a[0]) / (b[0] - a[0])
    out, last = [], s0
    for x in t:   # 不早于句首、不晚于句尾、不往回走
        x = min(max(x, last), s1)
        out.append(x)
        last = x
    return out, hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--words", help="逐字时间：自己整理的 lyrics-words.json，或者 Whisper --word_timestamps True 出的 json（都是歌里的秒）")
    a = ap.parse_args()
    lines = parse_srt(a.srt)
    times = [None] * len(lines)
    stats = [None] * len(lines)
    if a.words:
        j = json.load(open(a.words, encoding="utf-8-sig"))
        whisper = isinstance(j, dict) and "segments" in j
        per_line = None if whisper else lines_from_json(j)
        if per_line is not None and len(per_line) != len(lines):
            print(f"⚠ {a.words} 有 {len(per_line)} 句，lyrics.srt 有 {len(lines)} 句：不按句对，所有字连起来按时间和每句比对")
        flat = timeline_from_whisper(j) if whisper else [c for L in per_line for c in L]
        for i, (s0, s1, txt) in enumerate(lines):
            us = units(txt)
            if not us:
                continue
            if per_line is not None and len(per_line) == len(lines) and [norm(c[0]) for c in per_line[i]] == [norm(u) for u in us]:
                tt = [c[1] for c in per_line[i]]                       # 字一个不差：直接用
                out, hit, last = [], len(us), s0
                for x in tt:
                    x = min(max(x, last), s1)
                    out.append(x)
                    last = x
            else:
                cand = [c for c in flat if s0 - 1.0 <= c[1] <= s1 + 0.5]
                out, hit = align(us, cand, s0, s1)
            times[i], stats[i] = out, (hit, len(us))
    rows, idx = [], []
    for i, (s0, s1, txt) in enumerate(lines):
        if times[i]:
            s0 = min(s0, times[i][0])   # 第一个字比句首还早（字头对得更准）：句子跟着提前，字不会在句子出来之前就该出
        t0, t1 = s0 + a.offset, s1 + a.offset
        if t1 > 0:
            row = [round(max(0, t0), 3), round(t1, 3), txt]
            if times[i]:
                row.append([round(x + a.offset, 3) for x in times[i]])
            rows.append(row)
            idx.append(i)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("window.LYRICS = " + json.dumps(rows, ensure_ascii=False) + ";\n")
    for i, r in zip(idx, rows):
        note = ""
        if stats[i]:
            hit, n = stats[i]
            note = f"  逐字 {n} 个字位" + ("，都有自己的时间" if hit == n else f"，{hit} 个对上、{n - hit} 个按前后插的（拿不准，对着歌核一下）")
        elif a.words:
            note = "  没有逐字时间（照旧按固定间隔出字）"
        print(f"第 {i + 1} 句  {fmt_t(r[0])}–{fmt_t(r[1])}{note}")
    before = f"（片头之前的 {idx[0]} 句不要了）" if idx and idx[0] > 0 else ""
    print(f"{len(rows)} 句{before}，时间是{'成片秒' if a.offset else '歌里的秒'} → {a.out}")


if __name__ == "__main__":
    main()
