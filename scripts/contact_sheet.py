#!/usr/bin/env python3
"""把视频抽成带时间的接触表（一张图上一格一帧），给看不了视频的 agent 和人一起看片用。
    python3 scripts/contact_sheet.py mv.mp4 --every 0.5 -o review/sheet.jpg            # 全片每 0.5 秒一格
    python3 scripts/contact_sheet.py mv.mp4 --every 0.1 --start 32 --end 34 -o review/cut-32.jpg   # 转场前后逐帧
    python3 scripts/contact_sheet.py mv.mp4 --srt lyrics.srt -o review/lyrics.jpg      # 每句歌词开始后 0.2 秒一格，格子下面写第几句、起止（不印歌词）
    python3 scripts/contact_sheet.py mv.mp4 --srt lyrics.srt --offset -30.5 -o review/lyrics.jpg   # MV 从歌的 30.5 秒开始（和 analyze_song.py --offset 同一个数）
    python3 scripts/contact_sheet.py mv.mp4 --around 8,16.5,24 -o review/cuts.jpg      # 每个转场一行：前后 0.6 秒、每 0.1 秒一格，正好在转场上的一格框出来
    python3 scripts/contact_sheet.py --images sketches/ -o storyboard.png              # 一个文件夹的图拼成一张（草图总览）
    python3 scripts/contact_sheet.py reference.mp4 --every 1 --crop 1080:1920:420:0 -o review/ref.jpg   # 录屏有黑边、播放条的先裁掉（宽:高:x:y，和 video_rhythm.py --crop 一样）
    python3 scripts/contact_sheet.py mv.mp4 --every 1 --guides douyin -o review/safe.jpg   # 竖屏每格画上抖音安全范围（红框）和歌词带（虚线）
    python3 scripts/contact_sheet.py mv.mp4 --every 1 --guides wide -o review/safe.jpg     # 横屏：字幕安全框（红框，画面的 90%）和歌词带
    python3 scripts/contact_sheet.py mv.mp4 --every 1 --guides douyin --lyric-band 1327-1445 -o review/safe.jpg   # 歌词不在默认那条带上：写你放的位置（none 不画）
一张最多 --per-sheet 格（默认 48），多了拆成几张：第一张就是 -o 给的名字，后面是 -02、-03……（--around 按整行拆），每张标题写第几张、共几张，结尾打印全部文件名。
按帧号抽，不用 fps 滤镜（那个标的时间会偏早约 0.2 秒）。--crop 对 --every、--srt、--around 都管用：先裁再抽；裁到画面外直接报错。
--guides douyin：按 1080×1920 里横向 108–972、纵向 288–1540 画安全范围，纵向 1250–1500 画歌词带，别的竖屏尺寸按比例换算。
--guides wide：横屏（16:9、4:3）画字幕安全框（四边各留 5%）和歌词带（画面高度的 85%–95.5%，kit 默认歌词放的地方），按画面大小换算。
  横屏的片子给了 douyin 会自动换成 wide。--lyric-band 按 1080×1920（douyin）或 1920×1080（wide）的纵向像素写，别的尺寸按比例换算。
Windows 上把 python3 换成 py -3。
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, need, parse_crop, parse_srt, probe  # noqa: E402

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


def _select(video, expr, width, pat, crop=None):
    vf = (f"crop={crop}," if crop else "") + f"select='{expr}',scale={width}:-2"
    base = ["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", vf]
    r = subprocess.run(base + ["-fps_mode", "passthrough", "-q:v", "3", pat], capture_output=True, text=True)
    if r.returncode and "fps_mode" in r.stderr:      # ffmpeg 5.1 以前没有 -fps_mode
        r = subprocess.run(base + ["-vsync", "0", "-q:v", "3", pat], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)


def grab(video, frames, width, tmp, crop=None):
    """按帧号抽：frames = 排好序、不重复的帧号列表 → {帧号: 图片路径}"""
    need("ffmpeg")
    out = {}
    steps = {b - a for a, b in zip(frames, frames[1:])}
    if len(frames) > 80 and len(steps) == 1:          # 等间隔：一遍解码抽完
        n0, n1, k = frames[0], frames[-1], steps.pop()
        _select(video, f"gte(n\\,{n0})*lte(n\\,{n1})*not(mod(n-{n0}\\,{k}))", width, os.path.join(tmp, "e_%05d.jpg"), crop)
        got = sorted(glob.glob(os.path.join(tmp, "e_*.jpg")))
        return dict(zip(frames, got))
    for k in range(0, len(frames), 80):              # select 表达式太长会出错，分批
        chunk = frames[k:k + 80]
        expr = "+".join(f"eq(n\\,{n})" for n in chunk)
        _select(video, expr, width, os.path.join(tmp, f"b{k:05d}_%04d.jpg"), crop)
        got = sorted(glob.glob(os.path.join(tmp, f"b{k:05d}_*.jpg")))
        for n, p in zip(chunk, got):
            out[n] = p
    return out


# 参考线：安全范围（不被头像、按钮、文案挡住）和歌词带。douyin 按 1080×1920，wide 按 1920×1080，别的尺寸按比例换算
GUIDES = {
    "douyin": {"ref": (1080, 1920), "safe": (108, 288, 972, 1540), "band": (1250, 1500), "name": "抖音安全范围"},
    "wide": {"ref": (1920, 1080), "safe": (96, 54, 1824, 1026), "band": (918, 1031), "name": "字幕安全框（画面的 90%）"},
}


def draw_guides(im, kind, band):
    w, h = im.size
    gd = GUIDES[kind]
    sx, sy = w / gd["ref"][0], h / gd["ref"][1]
    d = ImageDraw.Draw(im, "RGBA")
    lw = max(1, round(w / 160))
    if band:
        y0, y1 = band[0] * sy, band[1] * sy
        d.rectangle([0, y0, w, y1], fill=(90, 200, 255, 45))           # 歌词带：半透明底 + 上下两条虚线
        dash = max(4, w // 40)
        for y in (y0, y1):
            for x in range(0, w, dash * 2):
                d.line([x, y, min(w, x + dash), y], fill=(90, 200, 255, 230), width=lw)
    s = gd["safe"]
    d.rectangle([s[0] * sx, s[1] * sy, s[2] * sx, s[3] * sy], outline=(255, 40, 40, 255), width=lw)


def build(cells, cols, out, title, guides=None, band=None):
    """cells = [(图片路径, 标签, 第二行)] 或 [(图片路径, 标签, 第二行, 要不要框出来)]；guides：每格画参考线（douyin / wide）"""
    if not cells:
        sys.exit("没有可拼的帧")
    ims = [Image.open(c[0]).convert("RGB") for c in cells]
    if guides:
        for im in ims:
            draw_guides(im, guides, band)
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
        mark = len(c) > 3 and c[3]
        if mark:   # 正好在要看的时刻上：粗红框
            d.rectangle([x - 6, y - 6, x + w + 5, y + h + lab - 2], outline=(255, 60, 60), width=6)
        d.text((x + 4, y + h + 4), c[1], fill=(255, 90, 90) if mark else (255, 220, 90), font=f1)
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
    ap.add_argument("--srt", help="按字幕抽：每句开始后 --srt-delay 秒一格，格子下写第几句、起止（不印歌词）")
    ap.add_argument("--srt-delay", type=float, default=0.2)
    ap.add_argument("--offset", type=float, default=0.0, help="只影响 --srt：成片秒 = 歌里的秒 + offset（和 analyze_song.py --offset 同一个数）")
    ap.add_argument("--around", help="几个时刻（逗号隔开），每个一行：前后 --span 秒、每 --step 秒一格")
    ap.add_argument("--span", type=float, default=0.6)
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--images", help="不抽视频，把这个文件夹里的图拼起来")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--width", type=int, default=320, help="每格宽（像素）")
    ap.add_argument("--per-sheet", type=int, default=48)
    ap.add_argument("--crop", help="先裁再抽，ffmpeg 的 宽:高:x:y（录屏的黑边、播放条先裁掉）")
    ap.add_argument("--guides", choices=["douyin", "wide"], help="douyin：竖屏画抖音安全范围和歌词带；wide：横屏画字幕安全框和歌词带")
    ap.add_argument("--lyric-band", help="歌词带画在哪：纵向 A-B 像素（douyin 按 1920 高、wide 按 1080 高），none 不画")
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
    vw, vh = info["width"], info["height"]
    if a.crop:
        vw, vh = parse_crop(a.crop, vw, vh)[:2]
    guides = a.guides
    if guides == "douyin" and vw and vh and vw >= vh:
        print(f"这支是横屏（{vw}×{vh}），--guides douyin 只管竖屏，换成 --guides wide 画")
        guides = "wide"
    elif guides == "wide" and vw and vh and vh > vw:
        print(f"这支是竖屏（{vw}×{vh}），--guides wide 只管横屏，换成 --guides douyin 画")
        guides = "douyin"
    band = None
    if guides:
        band = GUIDES[guides]["band"]
        if a.lyric_band:
            if a.lyric_band.strip().lower() == "none":
                band = None
            else:
                try:
                    i = a.lyric_band.index("-", 1)
                    band = tuple(sorted((float(a.lyric_band[:i]), float(a.lyric_band[i + 1:]))))
                except ValueError:
                    sys.exit(f"--lyric-band 写成 A-B（纵向像素，按 {GUIDES[guides]['ref'][1]} 高算），或者 none；现在是「{a.lyric_band}」")
    cols, per = a.cols, a.per_sheet
    if a.around:
        ts = [float(x) for x in a.around.split(",") if x.strip()]
        half = int(round(a.span / a.step))
        cols = 2 * half + 1
        per = max(1, a.per_sheet // cols) * cols         # 按整行拆
        want = []
        for T in ts:
            for j in range(-half, half + 1):
                t = T + j * a.step
                want.append((int(round(t * fps)), fmt_t(t) if t >= 0 else "-", "", j == 0))
    elif a.srt:
        # 片头前就开始、片头还在唱的句子也出一格（在片头那一刻 + delay）；格子下面只写第几句和起止，不印歌词
        rows = [(i, s0 + a.offset, s1 + a.offset) for i, (s0, s1, _) in enumerate(parse_srt(a.srt), 1)]
        rows = [(i, s0, s1) for i, s0, s1 in rows if s1 > 0 and s0 < dur]
        want = []
        for i, s0, s1 in rows:
            t = max(s0, 0.0) + a.srt_delay
            note = f"第 {i} 句 {fmt_t(s0) if s0 >= 0 else '片头前'}–{fmt_t(s1)}"
            want.append((int(round(t * fps)), fmt_t(t), note, False))
    else:
        end = min(a.end or dur, dur - 0.5 / fps)
        n = int((end - a.start) / a.every + 1e-6) + 1
        want = [(int(round((a.start + i * a.every) * fps)), fmt_t(a.start + i * a.every), "", False) for i in range(n)]
    total = int(dur * fps)
    outs = []
    with tempfile.TemporaryDirectory() as tmp:
        got = grab(a.video, sorted(set(w[0] for w in want if 0 <= w[0] < total)), a.width, tmp, a.crop)
        if a.around:   # 片外的格子（开头前、结尾后）用黑格占位，保持每行对齐
            blank = os.path.join(tmp, "blank.jpg")
            ref = next(iter(got.values()), None)
            Image.new("RGB", Image.open(ref).size if ref else (a.width, a.width * 9 // 16)).save(blank)
            cells = [(got.get(n, blank), lab, txt, mk) for n, lab, txt, mk in want]
        else:
            cells = [(got[n], lab, txt, mk) for n, lab, txt, mk in want if n in got]
        chunks = [cells[i:i + per] for i in range(0, len(cells), per)]
        base, ext = os.path.splitext(a.out)
        names = [a.out if k == 1 else f"{base}-{k:02d}{ext}" for k in range(1, len(chunks) + 1)]   # 第一张就是 -o，后面接 -02、-03
        for k, (ch, out) in enumerate(zip(chunks, names), 1):
            if a.around:
                title = f"{os.path.basename(a.video)}  每行一个时刻（{'外圈红框' if guides else '红框'}），前后 {a.span} 秒、每 {a.step} 秒一格"
            else:
                title = f"{os.path.basename(a.video)}  {ch[0][1]} – {ch[-1][1]}" + ("" if a.srt else f"  每 {a.every} 秒一格")
            if guides:
                title += f"  红框：{GUIDES[guides]['name']}" + ("；虚线：歌词带" if band else "")
            if len(chunks) > 1:
                title += f"  （第 {k}/{len(chunks)} 张）"
            outs.append(build(ch, cols, out, title, guides, band))
    if len(outs) > 1:
        print(f"格子多，拆成了 {len(outs)} 张（每张最多 {per} 格，--per-sheet 可改），都要看：")
    print("\n".join(outs))


if __name__ == "__main__":
    main()
