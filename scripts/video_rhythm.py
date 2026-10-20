#!/usr/bin/env python3
"""量一支视频的节奏和动静：在哪切镜头、每个镜头停多久、哪几段几乎不动、有没有黑帧。
看自己的 MV（像不像幻灯片、有没有硬切和跳帧）和拆参考视频（它多久换一个画面、是不是卡在拍子上）都用它。
    python3 scripts/video_rhythm.py mv.mp4                                   # 自己的成片
    python3 scripts/video_rhythm.py mv.mp4 --analysis song-analysis.json     # 再看切点有没有卡在拍子上
    python3 scripts/video_rhythm.py reference.mp4 --crop 1440:1080:240:0     # 录屏有黑边、播放条的先裁掉（宽:高:x:y）
判据（两支 MV 做下来定的）：
- 几乎不动：每 0.5 秒里相邻帧差的中位数 < 0.5（0–255 灰度，缩到 240 宽）。故意停住的一拍可以，连着一秒以上就像幻灯片
- 切点 / 跳帧：某两帧差 > 18，并且 > 前后几帧中位数的 2 倍。在你没打算切的地方出现 = 硬切或跳帧
- 黑帧：整帧平均亮度 < 8
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, need, probe  # noqa: E402

try:
    import numpy as np
except ImportError:
    sys.exit("缺 numpy：pip install numpy")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--analysis", help="analyze_song.py 存的 JSON，用来看切点卡没卡拍")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--crop", help="先裁再量，ffmpeg 的 宽:高:x:y")
    ap.add_argument("--fps", type=float, help="按多少帧每秒量（默认原帧率，最多 30）")
    ap.add_argument("--static", type=float, default=0.5, help="几乎不动的线（默认 0.5）")
    ap.add_argument("--cut", type=float, default=18, help="切点的线（默认 18）")
    ap.add_argument("-o", "--out", help="存 JSON")
    a = ap.parse_args()
    need("ffmpeg")
    if a.analysis and not os.path.exists(a.analysis):
        sys.exit(f"找不到 {a.analysis}（先跑 analyze_song.py -o 存一份）")
    info = probe(a.video)
    fps = a.fps or min(info["fps"] or 30, 30)
    vf = []
    if a.crop:
        vf.append(f"crop={a.crop}")
    vf += [f"fps={fps}", "scale=240:-2", "format=gray"]
    cmd = ["ffmpeg", "-v", "error"]
    if a.start:
        cmd += ["-ss", str(a.start)]
    if a.end:
        cmd += ["-t", str(a.end - a.start)]
    cmd += ["-i", a.video, "-vf", ",".join(vf), "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    w = 240
    if info["width"] and info["height"]:
        cw, ch = (int(x) for x in a.crop.split(":")[:2]) if a.crop else (info["width"], info["height"])
        h = int(round(ch * 240 / cw / 2) * 2)
    else:
        sys.exit("读不出画面大小")
    n = len(raw) // (w * h)
    if n < 3:
        sys.exit("帧太少，没法量")
    fr = np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.int16)
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))           # d[i]：第 i 帧和第 i+1 帧的差
    t = a.start + (np.arange(1, n)) / fps                         # 差值记在后一帧的时间上
    lum = fr.mean(axis=(1, 2))

    # 切点：比前后几帧的中位数大两倍以上、本身又够大
    cuts = []
    for i in range(len(d)):
        nb = np.concatenate([d[max(0, i - 5):i], d[i + 1:i + 6]])
        if d[i] > a.cut and d[i] > 2 * (np.median(nb) if len(nb) else 0):
            if not cuts or t[i] - cuts[-1] > 1.5 / fps:
                cuts.append(float(t[i]))
    edges = [a.start] + cuts + [a.start + n / fps]
    shots = np.diff(edges)

    # 几乎不动：每 0.5 秒的中位数
    win = max(1, int(round(0.5 * fps)))
    still, cur = [], None
    for k in range(0, len(d), win):
        m = float(np.median(d[k:k + win]))
        t0 = a.start + (k + 1) / fps
        if m < a.static:
            cur = [t0, t0 + win / fps] if cur is None else [cur[0], t0 + win / fps]
        elif cur is not None:
            still.append(cur)
            cur = None
    if cur is not None:
        still.append(cur)
    long_still = [s for s in still if s[1] - s[0] >= 1.0]
    black = [float(a.start + i / fps) for i in np.where(lum < 8)[0]]

    print(f"# {os.path.basename(a.video)} 的节奏（{fmt_t(a.start)}–{fmt_t(a.start + n / fps)}，按 {fps:g} 帧/秒量）\n")
    print(f"- 镜头数 {len(shots)}，切点 {len(cuts)} 个")
    if len(shots):
        q = np.percentile(shots, [10, 50, 90])
        print(f"- 每个镜头停多久：平均 {shots.mean():.2f} 秒，中位 {q[1]:.2f}，短的一成 ≤ {q[0]:.2f}，长的一成 ≥ {q[2]:.2f}")
        buckets = [("<0.5 秒", 0, 0.5), ("0.5–1", 0.5, 1), ("1–2", 1, 2), ("2–4", 2, 4), ("≥4", 4, 1e9)]
        print("- 分布：" + "，".join(f"{nm} {int(((shots >= lo) & (shots < hi)).sum())} 个" for nm, lo, hi in buckets))
    if a.analysis:
        beats = np.array(json.load(open(a.analysis, encoding="utf-8"))["beats"])
        if len(beats) and cuts:
            tol = max(0.07, 1.5 / fps)
            on = sum(1 for c in cuts if np.min(np.abs(beats - c)) <= tol)
            bi = float(np.median(np.diff(beats)))
            print(f"- 卡在拍子上的切点：{on}/{len(cuts)}（±{tol:.2f} 秒）；镜头中位长度约 {q[1] / bi:.1f} 拍")
    print(f"- 首帧亮度 {lum[0]:.0f}、尾帧 {lum[-1]:.0f}（0 黑 255 白；首尾别是纯黑、纯白）")
    print("\n## 切点\n")
    print("、".join(fmt_t(c) for c in cuts) if cuts else "没有（一镜到底，或者转场都是慢慢过渡的）")
    print("\n## 几乎不动的段（连着 1 秒以上）\n")
    print("\n".join(f"- {fmt_t(s[0])}–{fmt_t(s[1])}（{s[1] - s[0]:.1f} 秒）" for s in long_still) if long_still else "没有")
    if black:
        print(f"\n## 黑帧 {len(black)} 帧\n\n" + "、".join(fmt_t(b) for b in black[:40]) + ("……" if len(black) > 40 else ""))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"fps": fps, "cuts": cuts, "shots": [round(float(s), 3) for s in shots], "still": still,
                       "black": black, "diff": [round(float(x), 3) for x in d]}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
