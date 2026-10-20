#!/usr/bin/env python3
"""检查做 MV 要用的工具在不在。只检查、不安装：缺什么会打印安装命令，装之前先问用户。
    python3 scripts/check_env.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys

ok = True


def line(good, name, hint=""):
    global ok
    print(("✓ " if good else "✗ ") + name + ("" if good else f"    → {hint}"))
    if not good and not name.startswith("（可选）"):
        ok = False


def ver(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()[0]
    except Exception:
        return ""


line(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}（要 3.9+）", "装新一点的 Python")
for tool, hint in [("ffmpeg", "macOS: brew install ffmpeg；Windows: winget install ffmpeg；Linux: apt install ffmpeg"),
                   ("ffprobe", "和 ffmpeg 一起装")]:
    line(bool(shutil.which(tool)), tool, hint)
node = shutil.which("node")
nv = ver(["node", "--version"]) if node else ""
try:
    node_ok = node and int(nv.lstrip("v").split(".")[0]) >= 18
except ValueError:
    node_ok = False
line(bool(node_ok), f"Node.js {nv or ''}（要 18+，HyperFrames 渲染用）", "去 nodejs.org 装 LTS 版")
for mod, pip in [("numpy", "numpy"), ("librosa", "librosa"), ("PIL", "Pillow")]:
    line(importlib.util.find_spec(mod) is not None, f"Python 库 {mod}", f"pip install {pip}")
nm = subprocess.run(["node", "-e", "for (const m of ['puppeteer-core','puppeteer']) { try { require.resolve(m, {paths: [process.cwd()]}); console.log(m); break; } catch {} }"],
                    capture_output=True, text=True, cwd=os.getcwd()).stdout.strip() if node else ""
line(bool(nm), f"（可选）puppeteer {nm}（出样图、设定图、草图，和 p5.brush 逐帧渲染用）",
     "在项目文件夹里 npm i puppeteer-core（用本机 Chrome）或 npm i puppeteer")
has_whisper = bool(shutil.which("whisper")) or importlib.util.find_spec("whisper") is not None \
    or importlib.util.find_spec("faster_whisper") is not None
line(has_whisper, "（可选）Whisper 转歌词",
     "pip install openai-whisper（或 faster-whisper）；不装也行，自己准备 lyrics.srt")
print("\n全部就绪" if ok else "\n有 ✗ 的先装上（装之前问一下用户）")
sys.exit(0 if ok else 1)
