"""几个脚本共用的小函数：跑 ffmpeg、量响度、读视频信息。"""
import json
import re
import shutil
import subprocess
import sys


def need(tool):
    if not shutil.which(tool):
        sys.exit(f"找不到 {tool}，先装上（python3 scripts/check_env.py 会告诉你怎么装）")


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
