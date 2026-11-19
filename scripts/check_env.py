#!/usr/bin/env python3
"""检查做 MV 要用的工具在不在。只检查、不安装：缺什么会打印安装命令，装之前先问用户。
    python3 scripts/check_env.py
"""
import importlib.util
import os
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import py_cmd  # noqa: E402

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
line(bool(node_ok), f"Node.js {nv or ''}（要 18+，逐帧渲染用）", "去 nodejs.org 装 LTS 版")
for mod, pip in [("numpy", "numpy"), ("librosa", "librosa"), ("PIL", "Pillow")]:
    line(importlib.util.find_spec(mod) is not None, f"Python 库 {mod}", f"pip install {pip}")
# 在当前目录跑 node 查：和 render_frames.mjs 找的地方一样（项目里的 node_modules、往上几层、NODE_PATH）
nm = ""
if node:
    for m in ("puppeteer-core", "puppeteer"):
        r = subprocess.run(["node", "-e", f"require.resolve('{m}')"], capture_output=True, text=True, cwd=os.getcwd())
        if r.returncode == 0:
            nm = m
            break
line(bool(nm), f"puppeteer {nm}（用无头浏览器一帧帧截图：样图、草图、整片都靠它）",
     "在项目文件夹里 npm i puppeteer-core（用本机的 Chrome / Edge）；本机没有这类浏览器就 npm i puppeteer（会自己下载一个）")
pf, pf86, local = os.environ.get("ProgramFiles", "C:/Program Files"), os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"), os.environ.get("LOCALAPPDATA", "")
browsers = [os.environ.get("CHROME_PATH", ""),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/microsoft-edge",
            os.path.join(pf, "Google/Chrome/Application/chrome.exe"), os.path.join(pf86, "Google/Chrome/Application/chrome.exe"),
            os.path.join(local, "Google/Chrome/Application/chrome.exe") if local else "",
            os.path.join(pf86, "Microsoft/Edge/Application/msedge.exe"), os.path.join(pf, "Microsoft/Edge/Application/msedge.exe")]
found = next((b for b in browsers if b and os.path.exists(b)), "")
if nm != "puppeteer":   # 完整版 puppeteer 自带浏览器
    line(bool(found), f"本机浏览器 {found}（puppeteer-core 用它渲）", "装 Chrome 或 Edge，或者设 CHROME_PATH 指向一个 Chromium 内核的浏览器")
has_whisper = bool(shutil.which("whisper")) or importlib.util.find_spec("whisper") is not None \
    or importlib.util.find_spec("faster_whisper") is not None
line(has_whisper, "（可选）Whisper 转歌词",
     "pip install openai-whisper（或 faster-whisper）；不装也行，自己准备 lyrics.srt")
if sys.platform == "darwin" and platform.machine() == "arm64":   # Apple 芯片：mlx-whisper 跑得快
    line(importlib.util.find_spec("mlx_whisper") is not None, "（可选）mlx-whisper（Apple 芯片上转歌词快很多）",
         "pip install mlx-whisper；不装也行")
print(f"\n跑脚本用：{py_cmd()}")
print("\n全部就绪" if ok else "\n有 ✗ 的先装上（装之前问一下用户）")
sys.exit(0 if ok else 1)
