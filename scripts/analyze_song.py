#!/usr/bin/env python3
"""听懂一首歌的「骨架」：BPM、每一拍和每小节第一拍、分段和每段多响、突然安静 / 低音撤掉 / 重新进来的地方、最重的几下。
结果给第 1 步写 song.md 用，也给分镜对拍子用。歌词和情绪不在这里，那要听、要查。
    python3 scripts/analyze_song.py song.mp3 -o song-analysis.json
打印一份 markdown 摘要；-o 存全部数据（每一拍的时间都在里面）。
BPM 是自动测的，可能差一倍（快歌测成一半、慢歌测成两倍）：跟着歌拍手对一下，不对就按 --tempo-hint 重测。
"""
import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")   # librosa 读 mp4、m4a 时会提示换后端，不影响结果

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, lufs  # noqa: E402

try:
    import numpy as np
    import librosa
except ImportError:
    sys.exit("缺 numpy / librosa：pip install numpy librosa")

SR, HOP = 22050, 512


def smooth(x, n):
    if n <= 1:
        return x
    k = np.ones(n) / n
    return np.convolve(np.pad(x, (n // 2, n - 1 - n // 2), mode="edge"), k, mode="valid")


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("-o", "--out", help="存成 JSON（每一拍、每一段、每个事件）")
    ap.add_argument("--tempo-hint", type=float, help="大概的 BPM（测出来差一倍时给它）")
    ap.add_argument("--sections", type=int, help="想分几段（默认按歌长自动，约 20 秒一段）")
    a = ap.parse_args()

    y, sr = librosa.load(a.song, sr=SR, mono=True)
    dur = len(y) / sr
    fps = sr / HOP

    # 拍子：整体起音强度定 BPM 和每一拍；低频（底鼓、贝斯）起音定每小节第一拍（按 4/4）
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    kw = {"start_bpm": a.tempo_hint} if a.tempo_hint else {}
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP, **kw)
    tempo = float(np.atleast_1d(tempo)[0])
    bt = librosa.frames_to_time(beats, sr=sr, hop_length=HOP)
    low_onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP, fmax=200, n_mels=12)
    if len(beats) >= 8:
        phase = int(np.argmax([low_onset[beats[p::4]].sum() for p in range(4)]))
    else:
        phase = 0
    downbeats = bt[phase::4]

    # 响度曲线：整体和 150 Hz 以下（看低音什么时候撤、什么时候回来），0.25 秒平滑
    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    S = np.abs(librosa.stft(y, hop_length=HOP))
    freqs = librosa.fft_frequencies(sr=sr)
    low = np.sqrt((S[freqs <= 150] ** 2).mean(axis=0))
    n = max(1, int(0.25 * fps))
    L_all, L_low = smooth(db(rms), n), smooth(db(low), n)
    ref = np.percentile(L_all, 95)

    # 分段：每拍的音色（MFCC）+ 和声（chroma）特征，聚成连续的几段
    k = a.sections or int(np.clip(round(dur / 20), 4, 12))
    mf = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP, n_mfcc=13)
    ch = librosa.feature.chroma_stft(S=S ** 2, sr=sr, hop_length=HOP)
    feat = np.vstack([librosa.util.normalize(mf, axis=1), ch])
    if len(beats) > k * 2:
        sync = librosa.util.sync(feat, beats, aggregate=np.median)
        bidx = librosa.segment.agglomerative(sync, k)
        edges = sorted(set([0.0] + [float(bt[i - 1]) if i > 0 else 0.0 for i in bidx[1:]] + [dur]))
    else:
        edges = list(np.linspace(0, dur, k + 1))
    sections = []
    for s0, s1 in zip(edges[:-1], edges[1:]):
        if s1 - s0 < 1:
            continue
        i0, i1 = int(s0 * fps), max(int(s0 * fps) + 1, int(s1 * fps))
        rel = float(np.median(L_all[i0:i1]) - ref)
        level = "强" if rel > -4 else ("中" if rel > -10 else "弱")
        sections.append({"start": round(s0, 2), "end": round(s1, 2), "rel_db": round(rel, 1), "level": level})

    # 事件：前 1 秒和后 0.75 秒比，跌了 / 涨了 10 dB 以上（整体 = 突然安静 / 重新进来；低频 = 低音撤掉 / 低音回来）
    events = []
    w0, w1 = int(1.0 * fps), int(0.75 * fps)
    for name, L, up, dn in [("all", L_all, "重新进来", "突然安静"), ("low", L_low, "低音回来", "低音撤掉")]:
        last = -9.0
        for i in range(w0, len(L) - w1, max(1, int(0.05 * fps))):
            before, after = L[i - w0:i].mean(), L[i:i + w1].mean()
            d = after - before
            t = i / fps
            if abs(d) >= 10 and t - last > 1.5 and max(before, after) > ref - 25:
                events.append({"t": round(t, 2), "type": up if d > 0 else dn, "change_db": round(float(d), 1)})
                last = t
    events.sort(key=lambda e: e["t"])

    # 最重的几下：起音峰值，间隔 3 秒以上取前 8；再找最后一下重音（最后 30% 里够重的最后一个）
    pk = librosa.util.peak_pick(onset, pre_max=10, post_max=10, pre_avg=50, post_avg=50, delta=0.5, wait=int(0.3 * fps))
    strength = onset[pk] * np.interp(pk, np.arange(len(L_all)), 10 ** ((L_all - ref) / 20))
    order = np.argsort(-strength)
    hits = []
    for j in order:
        t = pk[j] / fps
        if all(abs(t - h["t"]) >= 3 for h in hits):
            hits.append({"t": round(float(t), 2), "strength": round(float(strength[j]), 2)})
        if len(hits) >= 8:
            break
    hits.sort(key=lambda h: h["t"])
    thr = np.percentile(strength, 90) if len(strength) else 0
    late = [pk[j] / fps for j in range(len(pk)) if pk[j] / fps > dur * 0.7 and strength[j] >= thr]
    last_hit = round(float(late[-1]), 2) if late else None

    I, peak = lufs(a.song)
    data = {"file": os.path.basename(a.song), "duration": round(dur, 2), "lufs": I, "true_peak": peak,
            "bpm": round(tempo, 1), "beat_interval": round(60 / tempo, 3) if tempo else None,
            "beats": [round(float(t), 3) for t in bt], "downbeats": [round(float(t), 3) for t in downbeats],
            "sections": sections, "events": events, "hits": hits, "last_hit": last_hit}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)

    print(f"# {data['file']} 的骨架\n")
    print(f"- 时长 {fmt_t(dur)}，响度 {I} LUFS（成片的音轨要和这个一样，差 1 dB 以上就是导出时变小了）")
    print(f"- BPM 约 {tempo:.1f}（一拍 {60 / tempo:.3f} 秒，一小节 {240 / tempo:.2f} 秒）。自动测的可能差一倍，跟着拍手对一下")
    print(f"- 共 {len(bt)} 拍；第一拍 {fmt_t(bt[0]) if len(bt) else '-'}，小节第一拍从 {fmt_t(downbeats[0]) if len(downbeats) else '-'} 起每 4 拍一个（按 4/4 估的）")
    print("\n## 分段（按音色和和声自动分的，名字要听了再定：前奏、主歌、副歌……；「强」的几段多半是副歌）\n")
    print("| 段 | 起 | 止 | 多响（和最响处比） |\n|---|---|---|---|")
    for i, s in enumerate(sections, 1):
        print(f"| {i} | {fmt_t(s['start'])} | {fmt_t(s['end'])} | {s['level']}（{s['rel_db']} dB） |")
    print("\n## 突然变化的地方（镜头最该在这些点上变：停住、留白、换场、放最重要的画面）\n")
    if events:
        for e in events:
            print(f"- {fmt_t(e['t'])} {e['type']}（{e['change_db']:+} dB）")
    else:
        print("- 没有 10 dB 以上的突变（这首歌很平，靠分段和副歌来变）")
    print("\n## 最重的几下（适合卡点：转场、角色大动作、画面里的东西落下）\n")
    print("- " + "、".join(fmt_t(h["t"]) for h in hits))
    if last_hit:
        print(f"- 最后一下重音：{fmt_t(last_hit)}（结尾画面落在这里，后面留白）")
    if a.out:
        print(f"\n每一拍的时间都在 {a.out} 里（beats、downbeats）")


if __name__ == "__main__":
    main()
