#!/usr/bin/env python3
"""把视频抽成带时间的接触表（一张图上一格一帧），给看不了视频的 agent 和人一起看片用。
    python3 scripts/contact_sheet.py mv.mp4 --every 0.5 -o review/sheet.jpg            # 全片每 0.5 秒一格
    python3 scripts/contact_sheet.py mv.mp4 --every 0.1 --start 32 --end 34 -o review/cut-32.jpg   # 转场前后逐帧
    python3 scripts/contact_sheet.py mv.mp4 --srt lyrics.srt -o review/lyrics.jpg      # 每句歌词开始后 0.2 秒一格，格子下面写这句应该是什么
    python3 scripts/contact_sheet.py --images sketches/ -o storyboard.png              # 一个文件夹的图拼成一张（草图总览）
一张最多 --per-sheet 格（默认 48），多了自动拆成 sheet-01.jpg、sheet-02.jpg……
按帧号抽，不用 fps 滤镜（那个标的时间会偏早约 0.2 秒）。
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, need, probe  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("缺 Pillow：pip install Pillow")


def font(size):
    for p in ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
              "C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def parse_srt(path):
    rows = []
    for b in re.split(r"\n\s*\n", open(path, encoding="utf-8-sig").read().strip()):
        L = b.strip().splitlines()
        for i, l in enumerate(L):
            m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", l)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                rows.append((a, " ".join(L[i + 1:]).strip()))
                break
    return rows


def grab(video, frames, width, tmp):
    """按帧号抽：frames = 帧号列表 → {帧号: 图片路径}"""
    need("ffmpeg")
    out = {}
    for k in range(0, len(frames), 80):              # select 表达式太长会出错，分批
        chunk = frames[k:k + 80]
        expr = "+".join(f"eq(n\\,{n})" for n in chunk)
        pat = os.path.join(tmp, f"b{k:05d}_%04d.jpg")
        base = ["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", f"select='{expr}',scale={width}:-2"]
        r = subprocess.run(base + ["-fps_mode", "passthrough", "-q:v", "3", pat], capture_output=True, text=True)
        if r.returncode and "fps_mode" in r.stderr:      # ffmpeg 5.1 以前没有 -fps_mode
            r = subprocess.run(base + ["-vsync", "0", "-q:v", "3", pat], capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr)
        got = sorted(glob.glob(os.path.join(tmp, f"b{k:05d}_*.jpg")))
        for n, p in zip(sorted(set(chunk)), got):
            out[n] = p
    return out


def build(cells, cols, out, title):
    """cells = [(图片路径, 标签, 第二行)]"""
    if not cells:
        sys.exit("没有可拼的帧")
    ims = [Image.open(c[0]).convert("RGB") for c in cells]
    w = max(i.width for i in ims)
    h = max(i.height for i in ims)
    f1, f2 = font(max(14, w // 14)), font(max(12, w // 18))
    lab = int(f1.size * 1.5 + (f2.size * 1.4 if any(c[2] for c in cells) else 0)) + 8
    rows = (len(ims) + cols - 1) // cols
    head = int(f1.size * 2) if title else 0
    sheet = Image.new("RGB", (cols * (w + 8) + 8, head + rows * (h + lab + 8) + 8), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    if title:
        d.text((10, 6), title, fill=(230, 230, 230), font=f1)
    for i, (im, c) in enumerate(zip(ims, cells)):
        x, y = 8 + (i % cols) * (w + 8), head + 8 + (i // cols) * (h + lab + 8)
        sheet.paste(im, (x, y))
        d.text((x + 4, y + h + 4), c[1], fill=(255, 220, 90), font=f1)
        if c[2]:
            d.text((x + 4, y + h + 4 + f1.size * 1.4), c[2][:28], fill=(220, 220, 220), font=f2)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sheet.save(out, quality=88)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--every", type=float, default=0.5, help="几秒一格（默认 0.5）")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--srt", help="按字幕抽：每句开始后 --srt-delay 秒一格，格子下写这句歌词")
    ap.add_argument("--srt-delay", type=float, default=0.2)
    ap.add_argument("--images", help="不抽视频，把这个文件夹里的图拼起来")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--width", type=int, default=320, help="每格宽（像素）")
    ap.add_argument("--per-sheet", type=int, default=48)
    a = ap.parse_args()

    if a.images:
        files = sorted(p for p in glob.glob(os.path.join(a.images, "*")) if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
        with tempfile.TemporaryDirectory() as tmp:
            cells = []
            for p in files:
                im = Image.open(p).convert("RGB")
                im.thumbnail((a.width * 2, a.width * 2))
                q = os.path.join(tmp, os.path.basename(p) + ".jpg")
                im.save(q)
                cells.append((q, os.path.splitext(os.path.basename(p))[0], ""))
            print(build(cells, a.cols, a.out, f"{a.images}（{len(cells)} 张）"))
        return

    if not a.video:
        sys.exit("要给视频路径，或者用 --images")
    info = probe(a.video)
    fps, dur = info["fps"] or 30, info["duration"]
    if a.srt:
        rows = [(t + a.srt_delay, txt) for t, txt in parse_srt(a.srt) if t + a.srt_delay < dur]
        want = [(int(round(t * fps)), fmt_t(t), txt) for t, txt in rows]
    else:
        end = min(a.end or dur, dur - 0.5 / fps)
        n = int((end - a.start) / a.every + 1e-6) + 1
        want = [(int(round((a.start + i * a.every) * fps)), fmt_t(a.start + i * a.every), "") for i in range(n)]
    want = [w for w in want if w[0] < int(dur * fps)]
    outs = []
    with tempfile.TemporaryDirectory() as tmp:
        got = grab(a.video, sorted(set(w[0] for w in want)), a.width, tmp)
        cells = [(got[n], lab, txt) for n, lab, txt in want if n in got]
        chunks = [cells[i:i + a.per_sheet] for i in range(0, len(cells), a.per_sheet)]
        base, ext = os.path.splitext(a.out)
        for k, ch in enumerate(chunks, 1):
            out = a.out if len(chunks) == 1 else f"{base}-{k:02d}{ext}"
            title = f"{os.path.basename(a.video)}  {ch[0][1]} – {ch[-1][1]}" + ("" if a.srt else f"  每 {a.every} 秒一格")
            outs.append(build(ch, a.cols, out, title))
    print("\n".join(outs))


if __name__ == "__main__":
    main()
