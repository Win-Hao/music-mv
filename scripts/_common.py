"""几个脚本共用的小函数：跑 ffmpeg、量响度、读视频信息、读 srt、给出跑脚本的命令。"""
import json
import os
import re
import shutil
import subprocess
import sys


def py_cmd():
    """提示里写的 python 命令：在虚拟环境里就是这个环境的 python（有空格加引号），不然 Windows 用 py -3，其他用 python3"""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        exe = sys.executable
        return f'"{exe}"' if " " in exe else exe
    return "py -3" if sys.platform == "win32" else "python3"


def script_path(name):
    """本脚本同目录里的 name，写成从当前目录出发的相对路径（不在同一个盘就给绝对路径）"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    try:
        p = os.path.relpath(p)
    except ValueError:
        pass
    return p.replace("\\", "/")


def need(tool):
    if not shutil.which(tool):
        sys.exit(f"找不到 {tool}，先装上（{py_cmd()} {script_path('check_env.py')} 会告诉你怎么装）")


def parse_crop(crop, vw, vh):
    """--crop 宽:高:x:y → (宽, 高, x, y)。写错格式、裁到画面外都直接报错：
    ffmpeg 遇到宽高超出画面只报一句看不懂的错、不出图，x、y 超出时还会悄悄挪回画面里，裁出来的不是你要的那块"""
    try:
        w, h, x, y = (int(v) for v in crop.split(":"))
    except ValueError:
        sys.exit(f"--crop 写成 宽:高:x:y（整数像素），比如 1080:1920:420:0；现在是「{crop}」")
    if w <= 0 or h <= 0 or x < 0 or y < 0 or (vw and x + w > vw) or (vh and y + h > vh):
        sys.exit(f"--crop {crop} 超出了画面：这支视频是 {vw}×{vh}，要 x + 宽 ≤ {vw}、y + 高 ≤ {vh}"
                 "（草稿缩小过的，按草稿的像素量，比如 1920×1080 上的 1280:720:20:180 在 960×540 上是 640:360:10:90）")
    return w, h, x, y


def _srt_ts(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def parse_srt(path):
    """读 srt → [(开始秒, 结束秒, 这句)]，按开始时间排好。
    编码依次试 utf-8（带不带 BOM 都行）、utf-16、gbk；换行 CRLF 也行；毫秒用逗号或点、位数不够也行（15,5 = 15.5 秒）；
    一句多行用空格连起来；缺序号也行；空的句子跳过。"""
    raw = open(path, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-16", "gbk"):
        if enc == "utf-16" and raw[:2] not in (b"\xff\xfe", b"\xfe\xff"):
            continue   # 没有 BOM 的 utf-16 几乎见不到，硬解会把 gbk 解成乱码
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    if text is None:
        sys.exit(f"读不了 {path}：不是 utf-8、utf-16 或 gbk 编码，用记事本另存为 UTF-8 再试")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    for b in re.split(r"\n\s*\n", text.strip()):
        L = b.strip().splitlines()
        for i, l in enumerate(L):
            m = re.match(r"\s*(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", l)
            if m:
                g = m.groups()
                txt = " ".join(x.strip() for x in L[i + 1:] if x.strip())
                if txt:
                    rows.append((_srt_ts(*g[:4]), _srt_ts(*g[4:]), txt))
                break
    rows.sort(key=lambda r: r[0])
    return rows


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe(path):
    """时长（秒）、宽、高、帧率、有没有音轨"""
    need("ffprobe")
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
             "-of", "json", str(path)])
    if r.returncode:
        sys.exit(f"读不了 {path}：{r.stderr.strip()}")
    j = json.loads(r.stdout)
    info = {"duration": float(j["format"].get("duration", 0) or 0), "width": None, "height": None, "fps": None, "audio": False}
    for s in j.get("streams", []):
        if s.get("codec_type") == "video" and info["width"] is None:
            info["width"], info["height"] = s.get("width"), s.get("height")
            num, den = (s.get("r_frame_rate") or "0/1").split("/")
            info["fps"] = float(num) / float(den) if float(den) else None
        if s.get("codec_type") == "audio":
            info["audio"] = True
    return info


def lufs(path, start=None, dur=None):
    """整段的综合响度（LUFS）和真峰值（dBTP）。没有音轨返回 (None, None)"""
    need("ffmpeg")
    cmd = ["ffmpeg", "-hide_banner", "-nostats"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if dur is not None:
        cmd += ["-t", str(dur)]
    cmd += ["-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"]
    r = run(cmd)
    tail = r.stderr[r.stderr.rfind("Summary:"):] if "Summary:" in r.stderr else ""
    i = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", tail)
    p = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", tail)
    f = lambda m: None if not m or m.group(1) == "-inf" else float(m.group(1))
    return f(i), f(p)


def fmt_t(t):
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m)}:{s:05.2f}"
