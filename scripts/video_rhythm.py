#!/usr/bin/env python3
"""量一支视频的节奏和动静：在哪切镜头、每个镜头停多久、哪几段几乎不动、哪几段大轮廓几乎没动、有没有黑帧；
给了计划的转场，再量每个转场「变化最大」和「停稳」在哪一刻。
看自己的 MV（像不像幻灯片、有没有硬切和跳帧）和拆参考视频（它多久换一个画面、是不是卡在拍子上）都用它。
    python3 scripts/video_rhythm.py mv.mp4                                   # 自己的成片
    python3 scripts/video_rhythm.py mv.mp4 --analysis song-analysis.json     # 再看切点有没有卡在拍子上（分析文件记了片头在歌里第几秒的，自动换成成片秒）
    python3 scripts/video_rhythm.py mv.mp4 --analysis song-analysis.json --offset -30.5   # 手动给：MV 从歌的 30.5 秒开始（和 analyze_song.py --offset 同一个数；从歌头开始写 --offset 0）
    python3 scripts/video_rhythm.py mv.mp4 --plan 7.0-7.87,15.05,17.23      # 对照计划的转场：一个数是落点，A-B 是转场从 A 到 B（成片秒）
    python3 scripts/video_rhythm.py mv.mp4 --plan 15.05 --inshot 9.2,12.6   # 镜头里设计好的大动作（灯冲亮、冲击波、东西卡拍立起来）：量成切点也算计划内，不算换镜头
    python3 scripts/video_rhythm.py mv.mp4 --hold 20.1-21.6                  # 分镜里故意停住的段：落在里面的「几乎不动」单独列，不算毛病
    python3 scripts/video_rhythm.py reference.mp4 --crop 1440:1080:240:0     # 录屏有黑边、播放条的先裁掉（宽:高:x:y）；合集里 MV 旁边有不动的面板，也裁出 MV 那块再量
Windows 上把 python3 换成 py -3。
判据（两支 MV 做下来定的；0–255 灰度，缩到 240 宽）：
- 几乎不动：相隔约 0.1 秒的两帧的差，每 0.5 秒取中位数，< 1.5。故意停住的一拍可以，连着一秒以上就像幻灯片。
  不用相邻帧比：一秒 12 张的画风在 30 帧的成片里大部分相邻帧一模一样，会被误报成不动
- 大轮廓几乎没动：再按面积平均缩到短边 27 格（横屏 48×27、竖屏 26×47），相隔约 0.1 秒的两帧逐格比，取差得最大的第 5 格，
  每 0.5 秒取中位数，< 14。线条一秒抖 12 次的画风（蜡笔、拼贴、笔刷）整帧的差一直不小，骗得过「几乎不动」；
  缩小以后线条的抖、纸纹的闪被平均掉，只剩大块的形状和明暗动没动。连着一秒以上就像幻灯片。
  不用 98 分位：画面里只有一个小东西在动时，变了的格子不到 2%，98 分位量不到。
  门槛用 1920×1080、1080×1920 的合成视频定的：静止 0；只有线条抖（静止构图上 60 条线每 1/12 秒随机偏 1–2 px）7–11；
  一个半径 75 px 的圆每秒走 300 px，一般 40–70（掠过和它一样灰的色块时会短暂掉下来，不到一秒不算）
- 切点 / 跳帧：相邻两帧差 > 18，并且 > 前后几帧中位数的 2 倍。相隔 0.25 秒以内的几个切点算一次转场（甩镜、快推、收光会量出一串）。
  在你没打算切的地方出现 = 硬切或跳帧
- 计划内：切点（合并后的范围）和 [落点 − 1.0, 落点 + 0.3] 有重叠（一段 A-B 是 [A − 0.3, B + 0.3]）。
  转场都在落点前一秒内动，变化最大的那帧常在落点前（推进照片、眨眼都是）
- 每个计划项：变化最大 = 上面那个窗口里相邻帧差最大的一帧；停稳 = 变化最大之后，相邻帧差 < 底噪 + 10% ×（峰值 − 底噪）
  并保持 3 帧的第一帧。底噪 = 落点后 [+0.3, +1.0] 秒（A-B 从 B 算）里相邻帧差的中位数，超出片尾就用落点前 [−2.0, −1.0] 秒的
  （笔刷、拼贴的线一直在抖，不减底噪会一直量不到停稳）。峰值比底噪高不到 max(3, 底噪) 算没量到变化
- --inshot 的时刻：和切点有重叠的窗口是 [T − 0.3, T + 0.3]。这样的切点算计划内（镜头里的大动作），不切开镜头
- --hold 的段：「几乎不动」「大轮廓几乎没动」落在里面的部分单独列成「故意停住」，剩下的部分照旧连着 1 秒以上才报
- 给了 --plan 时，另按计划的落点（A-B 按 B）把片子分成镜头报一遍停多久：辊子刷版、浪、一台镜头连着推过去的换景量不出切点，
  量出来的镜头数会比分镜少，看分镜对不对得上以这一行为准
- 黑帧：整帧平均亮度 < 8
"""
import argparse
import json
import os
import subprocess
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, need, parse_crop, probe  # noqa: E402

try:
    import numpy as np
except ImportError:
    sys.exit("缺 numpy：pip install numpy")


def parse_plan(s):
    """「8.5」是落点，「7.0-7.87」是一段转场 → [{a, b, lo, hi, label}]，lo–hi 是算计划内的窗口"""
    items = []
    for x in (s or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            if "-" in x[1:]:
                i = x.index("-", 1)
                A, B = sorted((float(x[:i]), float(x[i + 1:])))
                items.append({"a": A, "b": B, "lo": A - 0.3, "hi": B + 0.3, "label": f"{fmt_t(A)}–{fmt_t(B)}"})
            else:
                T = float(x)
                items.append({"a": T, "b": T, "lo": T - 1.0, "hi": T + 0.3, "label": fmt_t(T)})
        except ValueError:
            sys.exit(f"--plan 里的「{x}」看不懂：一个时刻写 8.5，一段转场写 7.0-7.87，逗号隔开")
    return sorted(items, key=lambda p: p["a"])


def parse_times(s, flag):
    """--inshot：逗号隔开的成片秒"""
    out = []
    for x in (s or "").split(","):
        if x.strip():
            try:
                out.append(float(x))
            except ValueError:
                sys.exit(f"{flag} 里的「{x.strip()}」看不懂：写成片秒，逗号隔开，比如 9.2,12.6")
    return sorted(out)


def parse_spans(s, flag):
    """--hold：逗号隔开的 A-B 段（成片秒）→ [[A, B]]"""
    out = []
    for x in (s or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            i = x.index("-", 1)
            out.append(sorted((float(x[:i]), float(x[i + 1:]))))
        except ValueError:
            sys.exit(f"{flag} 里的「{x}」看不懂：写一段 A-B（成片秒），比如 20.1-21.6，逗号隔开")
    return sorted(out)


def split_by(runs, spans):
    """runs 里和 spans 重叠的部分拿出来 → (不在 spans 里的部分, 在 spans 里的部分)"""
    outside, inside = [], []
    for r0, r1 in runs:
        cur = [[r0, r1]]
        for s0, s1 in spans:
            nxt = []
            for c0, c1 in cur:
                if s1 <= c0 or s0 >= c1:
                    nxt.append([c0, c1])
                    continue
                inside.append([max(c0, s0), min(c1, s1)])
                if c0 < s0:
                    nxt.append([c0, s0])
                if s1 < c1:
                    nxt.append([s1, c1])
            cur = nxt
        outside += cur
    return sorted(outside), sorted(inside)


def quiet_runs(series, thr, fps, start, gap):
    """series[k] 是第 k 帧和第 k+gap 帧的差：每 0.5 秒取中位数，低于 thr 的连成段 → [[开始秒, 结束秒]]"""
    win = max(1, int(round(0.5 * fps)))
    runs, cur = [], None
    for k in range(0, len(series), win):
        m = float(np.median(series[k:k + win]))
        t0 = start + (k + gap) / fps
        t1 = start + (min(k + win, len(series)) + gap) / fps
        if m < thr:
            cur = [t0, t1] if cur is None else [cur[0], t1]
        elif cur is not None:
            runs.append(cur)
            cur = None
    if cur is not None:
        runs.append(cur)
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--analysis", help="analyze_song.py 存的 JSON，用来看切点卡没卡拍")
    ap.add_argument("--offset", type=float, help="只影响 --analysis 的拍点：成片秒 = 歌里的秒 + offset（和 analyze_song.py --offset 同一个数；"
                                                 "分析文件里记了 start 就默认用 -start）")
    ap.add_argument("--plan", help="计划的转场（成片秒，逗号隔开）：一个数是落点，A-B 是转场从 A 到 B")
    ap.add_argument("--inshot", help="镜头里设计好的大动作（成片秒，逗号隔开）：量成切点也算计划内，不算换镜头")
    ap.add_argument("--hold", help="分镜里故意停住的段（A-B，逗号隔开）：落在里面的「几乎不动」单独列")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--crop", help="先裁再量，ffmpeg 的 宽:高:x:y")
    ap.add_argument("--fps", type=float, help="按多少帧每秒量（默认原帧率，最多 30）")
    ap.add_argument("--static", type=float, default=1.5, help="几乎不动的线（相隔 0.1 秒的帧差，默认 1.5）")
    ap.add_argument("--contour", type=float, default=14, help="大轮廓几乎没动的线（缩到短边 27 格、相隔 0.1 秒逐格比、差得最大的第 5 格，默认 14）")
    ap.add_argument("--cut", type=float, default=18, help="切点的线（默认 18）")
    ap.add_argument("-o", "--out", help="存 JSON")
    a = ap.parse_args()
    need("ffmpeg")
    if a.analysis and not os.path.exists(a.analysis):
        sys.exit(f"找不到 {a.analysis}（先跑 analyze_song.py -o 存一份）")
    plan = parse_plan(a.plan)
    inshot = parse_times(a.inshot, "--inshot")
    hold = parse_spans(a.hold, "--hold")
    info = probe(a.video)
    fps = a.fps or min(info["fps"] or 30, 30)
    if not (info["width"] and info["height"]):
        sys.exit("读不出画面大小")
    cw, ch = parse_crop(a.crop, info["width"], info["height"])[:2] if a.crop else (info["width"], info["height"])
    w, h = 240, max(2, int(round(ch * 240 / cw / 2)) * 2)     # 自己算成偶数传给 ffmpeg，读的时候才对得上
    # 大轮廓：按面积平均缩到短边 27 格（横屏 48×27、竖屏 26×47），每格在原片里差不多一样大，横竖屏的门槛才能通用
    blk = max(1, round(min(w, h) / 27))
    bh, bw = max(1, h // blk), max(1, w // blk)
    vf = ([f"crop={a.crop}"] if a.crop else []) + [f"fps={fps}", f"scale={w}:{h}", "format=gray"]
    cmd = ["ffmpeg", "-v", "error"]
    if a.start:
        cmd += ["-ss", str(a.start)]
    if a.end:
        cmd += ["-t", str(a.end - a.start)]
    cmd += ["-i", a.video, "-vf", ",".join(vf), "-f", "rawvideo", "-"]

    # 一帧一帧读，只留最近 0.1 秒的几帧，整支片子的像素不进内存
    gap = max(1, int(round(0.1 * fps)))
    size = w * h
    recent = deque(maxlen=gap + 1)
    small = deque(maxlen=gap + 1)
    d, d10, big, lum = [], [], [], []   # d[i]：第 i 帧和第 i+1 帧的差；d10[i]：第 i+gap 帧和第 i 帧的差；big[i]：同样两帧缩到 48 宽后每格差的 98 分位
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            f = np.frombuffer(buf, np.uint8).reshape(h, w).astype(np.int16)
            sm = f[:bh * blk, :bw * blk].reshape(bh, blk, bw, blk).mean(axis=(1, 3))
            lum.append(float(f.mean()))
            if recent:
                d.append(float(np.abs(f - recent[-1]).mean()))
            if len(recent) == gap + 1:
                d10.append(float(np.abs(f - recent[0]).mean()))
                cell = np.abs(sm - small[0]).ravel()
                big.append(float(np.partition(cell, -5)[-5]) if cell.size >= 5 else float(cell.max()))   # 差得最大的第 5 格
            recent.append(f)
            small.append(sm)
    finally:
        p.stdout.close()
        p.wait()
    n = len(lum)
    if n < 3:
        sys.exit("帧太少，没法量")
    d, d10, big, lum = np.array(d), np.array(d10), np.array(big), np.array(lum)
    t = a.start + (np.arange(1, n)) / fps                         # 差值记在后一帧的时间上
    t_end = a.start + n / fps

    # 切点：比前后几帧的中位数大两倍以上、本身又够大
    cuts = []
    for i in range(len(d)):
        nb = np.concatenate([d[max(0, i - 5):i], d[i + 1:i + 6]])
        if d[i] > a.cut and d[i] > 2 * (np.median(nb) if len(nb) else 0):
            if not cuts or t[i] - cuts[-1] > 1.5 / fps:
                cuts.append(float(t[i]))
    # 相隔 0.25 秒以内的切点算一次转场：[开始, 结束, 几下]
    ranges = []
    for c in cuts:
        if ranges and c - ranges[-1][1] <= 0.25:
            ranges[-1][1] = c
            ranges[-1][2] += 1
        else:
            ranges.append([c, c, 1])

    def in_shot(r):
        """和这个切点有重叠的 --inshot 时刻（已经算进某个计划转场的不算）"""
        if any(r[0] <= pi["hi"] and r[1] >= pi["lo"] for pi in plan):
            return []
        return [T for T in inshot if r[0] <= T + 0.3 and r[1] >= T - 0.3]

    edges = [a.start] + [r[0] for r in ranges if not in_shot(r)] + [t_end]   # 镜头里的大动作不切开镜头
    shots = np.diff(edges)

    still = quiet_runs(d10, a.static, fps, a.start, gap)
    flat = quiet_runs(big, a.contour, fps, a.start, gap)
    still_out, still_hold = split_by(still, hold)
    flat_out, flat_hold = split_by(flat, hold)
    long_still = [s for s in still_out if s[1] - s[0] >= 1.0]
    long_flat = [s for s in flat_out if s[1] - s[0] >= 1.0]
    black = [float(a.start + i / fps) for i in np.where(lum < 8)[0]]

    def span(r):
        return fmt_t(r[0]) if r[2] == 1 else f"{fmt_t(r[0])}–{fmt_t(r[1])}（{r[2]} 下）"

    def matched(r):
        """和这个切点有重叠的计划项"""
        return [pi for pi in plan if r[0] <= pi["hi"] and r[1] >= pi["lo"]]

    def nearest(r):
        best = min(plan, key=lambda pi: max(r[0] - pi["b"], pi["a"] - r[1], 0))
        return best, max(r[0] - best["b"], best["a"] - r[1], 0)

    def median_in(lo, hi):
        m = (t >= lo) & (t <= hi)
        return float(np.median(d[m])) if m.sum() >= 3 else None

    # 每个计划项：变化最大、停稳
    plan_res = []
    for pi in plan:
        res = {"plan": [pi["a"], pi["b"]] if pi["a"] != pi["b"] else pi["a"], "peak": None, "settle": None}
        m = np.where((t >= pi["lo"]) & (t <= pi["hi"]))[0]
        if not len(m):
            res["note"] = "不在片子里"
            plan_res.append(res)
            continue
        floor = median_in(pi["b"] + 0.3, pi["b"] + 1.0)
        if floor is None:
            floor = median_in(pi["a"] - 2.0, pi["a"] - 1.0)
        floor = floor or 0.0
        k = int(m[np.argmax(d[m])])
        peak = float(d[k])
        if peak - floor < max(3.0, floor):
            res["note"] = "没量到变化"
            plan_res.append(res)
            continue
        res["peak"] = round(float(t[k]), 3)
        thr = floor + 0.1 * (peak - floor)
        last = min(len(d), k + 1 + int(round(2.0 * fps)))
        for j in range(k + 1, last - 2):
            if (d[j:j + 3] < thr).all():
                res["settle"] = round(float(t[j]), 3)
                res["late"] = round(float(t[j]) - pi["b"], 3)
                break
        plan_res.append(res)

    n_in = sum(1 for r in ranges if in_shot(r))
    print(f"# {os.path.basename(a.video)} 的节奏（{fmt_t(a.start)}–{fmt_t(t_end)}，按 {fps:g} 帧/秒量）\n")
    print(f"- 镜头数 {len(shots)}，切点 {len(ranges)} 处（相隔 0.25 秒以内的算一处"
          + (f"；其中 {n_in} 处是 --inshot 标的镜头里的大动作，不切开镜头" if n_in else "") + "）")
    q = None
    if len(shots):
        q = np.percentile(shots, [10, 50, 90])
        print(f"- 每个镜头停多久：平均 {shots.mean():.2f} 秒，中位 {q[1]:.2f}，短的一成 ≤ {q[0]:.2f}，长的一成 ≥ {q[2]:.2f}")
        buckets = [("<0.5 秒", 0, 0.5), ("0.5–1", 0.5, 1), ("1–2", 1, 2), ("2–4", 2, 4), ("≥4", 4, 1e9)]
        print("- 分布：" + "，".join(f"{nm} {int(((shots >= lo) & (shots < hi)).sum())} 个" for nm, lo, hi in buckets))
    if plan:
        pe = [a.start] + [pi["b"] for pi in plan if a.start < pi["b"] < t_end] + [t_end]
        ps = np.diff(pe)
        print(f"- 按 --plan 的落点分：镜头 {len(ps)} 个，每个停多久平均 {ps.mean():.2f} 秒、中位 {np.median(ps):.2f}、最短 {ps.min():.2f}、最长 {ps.max():.2f}"
              "（辊子刷版、浪、一台镜头连着推过去的换景量不出切点，和分镜对镜头数看这一行）")
    beats = None
    tol = max(0.07, 1.5 / fps)
    if a.analysis:
        an = json.load(open(a.analysis, encoding="utf-8"))
        off = a.offset
        st = float(an.get("start") or 0)
        if off is None:
            off = -st
            if st:
                print(f"- 分析文件里记了片头在歌里第 {st:g} 秒（analyze_song.py --offset 存的），拍点按 --offset {off:g} 换成成片秒")
            # 只在没写 --offset 时提醒：成片和分析里这一段（只做一段时是 end − start，整首是歌长）差 2 秒以上
            vdur = info["duration"] or t_end
            seg_len = (float(an["end"]) - st) if an.get("end") else float(an.get("duration") or 0)
            if seg_len and abs(seg_len - vdur) >= 2:
                print(f"- ⚠ 成片 {vdur:.2f} 秒，分析里这一段 {seg_len:.2f} 秒：只做一段的话加 --offset -<片头在歌里的秒数>（从歌头开始就写 --offset 0），不然卡拍对不上")
        beats = np.array(an["beats"]) + off
        if len(beats) and ranges:
            on = sum(1 for r in ranges if ((beats >= r[0] - tol) & (beats <= r[1] + tol)).any())
            bi = float(np.median(np.diff(beats))) if len(beats) > 1 else 0
            print(f"- 卡在拍子上的切点：{on}/{len(ranges)}（前后 {tol:.2f} 秒内有拍点）" + (f"；镜头中位长度约 {q[1] / bi:.1f} 拍" if bi and q is not None else ""))
    if plan or inshot:
        inplan = [r for r in ranges if matched(r) or in_shot(r)]
        print(f"- 计划内 {len(inplan)} 个、计划外 {len(ranges) - len(inplan)} 个（计划外的多半是硬切或跳帧；"
              "切点落在落点前 1 秒到后 0.3 秒里算计划内，一段 A-B 是前后 0.3 秒，--inshot 是前后 0.3 秒）")
    print(f"- 首帧亮度 {lum[0]:.0f}、尾帧 {lum[-1]:.0f}（0 黑 255 白；首尾别是纯黑、纯白）")
    if plan:
        print("\n## 计划的转场（变化最大、停稳；停稳比计划晚一点正常，早了说明转场在落点前就做完了）\n")
        for pi, res in zip(plan, plan_res):
            if res.get("note") == "不在片子里":
                print(f"- {pi['label']}：不在量的这段片子里")
            elif res.get("note"):
                print(f"- {pi['label']}：没量到变化（转场很轻或镜头连续运动）")
            elif res["settle"] is None:
                print(f"- {pi['label']}：变化最大 {fmt_t(res['peak'])}，之后 2 秒内没停稳（一直在动）")
            else:
                late = res["late"]
                rel = "和计划一样" if abs(late) < 0.5 / fps else (f"比计划晚 {late:.2f} 秒" if late > 0 else f"比计划早 {-late:.2f} 秒")
                print(f"- {pi['label']}：变化最大 {fmt_t(res['peak'])}，停稳 {fmt_t(res['settle'])}（{rel}）")
    print("\n## 切点\n")
    if not ranges:
        print("没有（一镜到底，或者转场都是慢慢过渡的）")
    for r in ranges:
        notes = []
        if beats is not None and len(beats):
            notes.append("卡拍" if ((beats >= r[0] - tol) & (beats <= r[1] + tol)).any() else "没卡拍")
        mt, ins = matched(r), in_shot(r)
        if mt:
            notes.append("计划内：" + "、".join(pi["label"] for pi in mt))
        elif ins:
            notes.append("计划内：镜头里的大动作 " + "、".join(fmt_t(x) for x in ins))
        elif plan:
            best, g = nearest(r)
            notes.append(f"计划外，离最近的计划 {best['label']} 差 {g:.2f} 秒")
        print(f"- {span(r)}" + (f"（{'，'.join(notes)}）" if notes else ""))
    print("\n## 几乎不动的段（连着 1 秒以上）\n")
    print("\n".join(f"- {fmt_t(s[0])}–{fmt_t(s[1])}（{s[1] - s[0]:.1f} 秒）" for s in long_still) if long_still else "没有")
    print("\n## 大轮廓几乎没动的段（只有线条抖、纸纹闪或很慢的推拉，看着像幻灯片；连着 1 秒以上）\n")
    print("\n".join(f"- {fmt_t(s[0])}–{fmt_t(s[1])}（{s[1] - s[0]:.1f} 秒）" for s in long_flat) if long_flat else "没有")
    if hold:
        print("\n## 故意停住的段（--hold；落在里面的不动不算毛病）\n")
        for h0, h1 in hold:
            s_in = sum(min(h1, s1) - max(h0, s0) for s0, s1 in still_hold if s1 > h0 and s0 < h1)
            f_in = sum(min(h1, s1) - max(h0, s0) for s0, s1 in flat_hold if s1 > h0 and s0 < h1)
            print(f"- {fmt_t(h0)}–{fmt_t(h1)}：几乎不动 {s_in:.1f} 秒、大轮廓没动 {f_in:.1f} 秒")
    if black:
        print(f"\n## 黑帧 {len(black)} 帧\n\n" + "、".join(fmt_t(b) for b in black[:40]) + ("……" if len(black) > 40 else ""))
        print("\n钻进黑暗、灯灭、收光、眨眼这类故意黑下去的不算错，对照转场时刻确认")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"fps": fps, "cuts": cuts, "cut_ranges": [[round(r[0], 3), round(r[1], 3)] for r in ranges],
                       "inshot_ranges": [[round(r[0], 3), round(r[1], 3)] for r in ranges if in_shot(r)],
                       "shots": [round(float(s), 3) for s in shots], "still": still, "contour_still": flat,
                       "hold": hold, "still_in_hold": still_hold, "contour_still_in_hold": flat_hold,
                       "plan": plan_res, "black": black, "diff": [round(float(x), 3) for x in d],
                       "contour_diff": [round(float(x), 3) for x in big]}, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
