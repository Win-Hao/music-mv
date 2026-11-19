#!/usr/bin/env python3
"""听懂一首歌的「骨架」：BPM、每一拍和每小节第一拍、分段和每段多响、突然安静 / 低音撤掉 / 重新进来的地方、最重的几下、起音、每帧响度。
结果给第 1 步写 song.md 用，也给分镜和 MV 页面对拍子用。歌词和情绪不在这里，那要听、要查。
    python3 scripts/analyze_song.py song.mp3 -o song-analysis.json --js mv/song.js
    python3 scripts/analyze_song.py song.mp3 -o song-analysis.json --js mv/song.js --offset -24 --end 40   # 只做歌的 24–40 秒
打印一份 markdown 摘要；-o 存全部数据（每一拍的时间都在里面）；--js 另存一份 window.SONG 给 MV 页面用
（拍点、分段、突变、重音、起音、每秒 30 个点的响度和低音包络），页面里按真实拍点卡拍，不靠 BPM 往后推。
只做歌的一段时加 --offset -24 --end 40（片头在歌里第 24 秒、片尾在第 40 秒）：--js 的时间都换成成片秒（成片秒 = 歌里的秒 − 24），
片长 = 40 − 24，这段以外的拍点、事件、响度都截掉，SONG.start 记下 24；打印的时刻后面括号里写成片秒。-o 存的 JSON 仍是歌里的秒（多记 start、end）。
只做一段时拍点默认沿用整首测的（片段改长改短，段里的拍点不变，渲好的帧接着能用）；这段自己测出来的速度和整首的差 2% 以上
（中途变速、几段接起来的歌），就改用这段自己测的，并打印出来。
BPM 按测到的拍点算（拍点按序号拟合的斜率），不是 librosa 估的那个取整的数（128 BPM 的歌它会报 129.2）。
BPM 可能差一倍（快歌测成一半、慢歌测成两倍）或者锁成 3:4：上网搜这首歌的 BPM 对一下，或者打开 mv/index.html 看小球落地对不对得上鼓点，
不对就加 --tempo-hint <搜到的 BPM> 重测：只在它上下 8% 里找。慢歌测成两倍时减半要小心，见 references/render.md「拍子不对」。
"""
import argparse
import json
import math
import os
import sys
import warnings

warnings.filterwarnings("ignore")   # librosa 读 mp4、m4a 时会提示换后端，不影响结果

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import fmt_t, lufs, need  # noqa: E402

try:
    import numpy as np
    import librosa
    import scipy.stats   # librosa 自带的依赖
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


def beat_period(bt):
    """一拍几秒：先按每 8 拍的跨度取中位数估个大概，给每个拍点编号（漏了一拍的地方编号跳 2），再按编号直线拟合。
    librosa 估的 BPM 按帧取整（128 BPM 的歌报 129.2），拍点本身跟着起音走，拟合出来的才是真的速度"""
    bt = np.asarray(bt, float)
    if len(bt) < 3:
        return None
    k = min(8, len(bt) - 1)
    p0 = float(np.median((bt[k:] - bt[:-k]) / k))
    if p0 <= 0:
        return None
    idx = np.concatenate([[0.0], np.cumsum(np.maximum(1, np.round(np.diff(bt) / p0)))])
    return float(np.polyfit(idx, bt, 1)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("-o", "--out", help="存成 JSON（每一拍、每一段、每个事件）")
    ap.add_argument("--js", help="另存 window.SONG = {...} 给 MV 页面用")
    ap.add_argument("--offset", type=float, default=0.0, help="只做一段时写 -片头在歌里的秒数：成片秒 = 歌里的秒 + offset")
    ap.add_argument("--end", type=float, help="只做一段时片尾在歌里的秒数（不给就到歌尾）")
    ap.add_argument("--tempo-hint", type=float, help="网上查到的 BPM（测出来差一倍或锁成 3:4 时给它）：只在它上下 8%% 里找")
    ap.add_argument("--sections", type=int, help="想分几段（默认按歌长自动，约 20 秒一段）")
    a = ap.parse_args()

    need("ffmpeg")   # 量响度要用，先查，免得分析完才报找不到
    y, sr = librosa.load(a.song, sr=SR, mono=True)
    dur = len(y) / sr
    fps = sr / HOP
    if len(y) == 0 or float(np.abs(y).max()) < 1e-4:
        sys.exit(f"{a.song} 几乎没有声音（全是静音），分析不出拍子。换一个文件，或者看看是不是导出错了")
    # 只做歌的一段：片头在歌里第 seg0 秒，片尾在第 seg1 秒；成片秒 = 歌里的秒 − seg0
    seg = bool(a.offset) or a.end is not None
    seg0 = -a.offset + 0.0
    seg1 = dur if a.end is None else min(a.end, dur)
    if a.end is not None and a.end > dur + 0.05:
        print(f"⚠ --end {a.end:g} 超过了歌长 {dur:.2f} 秒，按歌尾算")
    if seg1 - seg0 < 0.5:
        sys.exit(f"这段太短：片头在歌里第 {seg0:g} 秒、片尾在第 {seg1:g} 秒（--offset 写负的片头秒数，比如 --offset -24 --end 40）")

    # 拍子：整体起音强度定 BPM 和每一拍；低频（底鼓、贝斯）起音定每小节第一拍（按 4/4）
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    kw = {}
    if a.tempo_hint:
        # 只在给的 BPM 上下 8% 里找。librosa 默认只把它当起点，锁到 3:4 这类错格时拉不回来（一首 75 BPM 的歌只测后半段时锁成 99.4）
        kw = {"start_bpm": a.tempo_hint, "prior": scipy.stats.uniform(a.tempo_hint * 0.92, a.tempo_hint * 0.16)}
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=sr, hop_length=HOP, **kw)
    tempo = float(np.atleast_1d(tempo)[0])
    if not tempo or len(beats) == 0:
        sys.exit("测不出拍子（太安静，或者没有明显的节奏）。试试加 --tempo-hint 120 这类大概的 BPM 再跑")
    bt = librosa.frames_to_time(beats, sr=sr, hop_length=HOP)
    local = None
    if seg:
        # 只做一段：这段（前后多带 4 秒）自己再测一遍。和整首测的速度差 2% 以上（中途变速、几段接起来的歌）就用这段自己的；
        # 差不多就沿用整首的，片段改长改短时段里的拍点不变，渲好的帧接着能用
        i0, i1 = int(max(0.0, seg0 - 4) * fps), int(min(dur, seg1 + 4) * fps)
        _, lb = librosa.beat.beat_track(onset_envelope=onset[i0:i1], sr=sr, hop_length=HOP, **kw)
        lbt = librosa.frames_to_time(lb + i0, sr=sr, hop_length=HOP)
        pg = beat_period(bt[(bt >= seg0) & (bt <= seg1)])
        pl = beat_period(lbt[(lbt >= seg0) & (lbt <= seg1)])
        if pg and pl and abs(pg / pl - 1) > 0.02:
            local = (60 / pg, 60 / pl)
            beats, bt = lb + i0, lbt
    low_onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP, fmax=200, n_mels=12)
    period = beat_period(bt[(bt >= seg0 - 1e-6) & (bt <= seg1 + 1e-6)] if seg else bt) or beat_period(bt) or 60 / tempo

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
        edges = [float(bt[i - 1]) if i > 0 else 0.0 for i in bidx[1:]]
    else:
        edges = list(np.linspace(0, dur, k + 1))
    edges = sorted(set([0.0, dur] + [float(e) for e in edges if 0 < e < dur]))
    # 短于 1 秒的碎段并进相邻的段（并进短一点的那个邻居；头一段只能往后并，最后一段只能往前并）
    while len(edges) > 2:
        lens = np.diff(edges)
        i = int(np.argmin(lens))
        if lens[i] >= 1:
            break
        if i == 0:
            del edges[1]
        elif i == len(lens) - 1:
            del edges[i]
        else:
            del edges[i if lens[i - 1] <= lens[i + 1] else i + 1]
    sections = []
    for s0, s1 in zip(edges[:-1], edges[1:]):
        i0, i1 = int(s0 * fps), max(int(s0 * fps) + 1, int(s1 * fps))
        rel = float(np.median(L_all[i0:i1]) - ref)
        level = "强" if rel > -4 else ("中" if rel > -10 else "弱")
        sections.append({"start": round(s0, 2), "end": round(s1, 2), "rel_db": round(rel, 1), "level": level})

    # 事件：前 1 秒和后 0.75 秒的平均响度比，跌了 / 涨了够多（整体 8 dB = 突然安静 / 重新进来；低频 10 dB = 低音撤掉 / 低音回来）。
    # 刚越线时变化还没到底，所以越线后再往后 1 秒找变化最大的那一点当事件时间；同一类事件 1.5 秒内只留最强的一个
    events = []
    w0, w1, look = int(1.0 * fps), int(0.75 * fps), int(1.0 * fps)
    for name, L, up, dn, thr in [("all", L_all, "重新进来", "突然安静", 8), ("low", L_low, "低音回来", "低音撤掉", 10)]:
        c = np.concatenate([[0.0], np.cumsum(L)])
        idx = np.arange(w0, len(L) - w1)
        if not len(idx):
            continue
        before, after = (c[idx] - c[idx - w0]) / w0, (c[idx + w1] - c[idx]) / w1
        d = after - before
        loud = np.maximum(before, after) > ref - 25
        cands, k = [], 0
        while k < len(idx):
            if abs(d[k]) >= thr and loud[k]:
                sign = np.sign(d[k])
                rise = d[k:k + look] * sign
                j = k + int(np.argmax(rise))
                cands.append((float(idx[j] / fps), float(d[j])))
                k = j + 1
                while k < len(idx) and np.sign(d[k]) == sign and abs(d[k]) >= thr:   # 还在同一次变化里
                    k += 1
            else:
                k += 1
        kept = []
        for t, dv in sorted(cands, key=lambda x: -abs(x[1])):
            typ = up if dv > 0 else dn
            if all(not (e["type"] == typ and abs(e["t"] - t) < 1.5) for e in kept):
                kept.append({"t": round(t, 2), "type": typ, "change_db": round(dv, 1)})
        events += kept
    events.sort(key=lambda e: e["t"])

    # 小节第一拍（按 4/4）：四种起法里低频起音（底鼓、贝斯）平均最强的那种。
    # 最强和第二强差不到 10% 算拿不准：改成让最强的「重新进来 / 低音回来」（没有就用最响那段的起点）落在小节第一拍上；
    # 只做一段时先在这段里找
    phase, unsure = 0, None
    if len(beats) >= 8:
        pw = np.array([float(low_onset[beats[p::4]].mean()) for p in range(4)])
        phase = int(np.argmax(pw))
        top = np.sort(pw)[::-1]
        gap = float((top[0] - top[1]) / top[0]) if top[0] > 0 else 0.0
        if gap < 0.10:
            ups = [e for e in events if e["type"] in ("重新进来", "低音回来")]
            ups = [e for e in ups if seg0 - 1e-6 <= e["t"] <= seg1 + 1e-6] or ups
            if ups:
                e = max(ups, key=lambda e: e["change_db"])
                anchor, what = e["t"], e["type"]
            else:
                secs = [s for s in sections if s["end"] > seg0 and s["start"] < seg1] or sections
                anchor, what = max(seg0, max(secs, key=lambda s: s["rel_db"])["start"]), "最响那段的起点"
            phase = int(np.argmin(np.abs(bt - anchor))) % 4
            unsure = (gap, anchor, what)
    downbeats = bt[phase::4]

    # 最重的几下：起音峰值，间隔 3 秒以上，整首取前 8（只做一段时截到这段里：片段改长改短，段里原有的那几下不变）
    # 峰之间只隔约 0.1 秒：隔太久会在密的起音里跳过更强的正拍、落到反拍上
    pk = librosa.util.peak_pick(onset, pre_max=10, post_max=10, pre_avg=50, post_avg=50, delta=0.5, wait=max(1, int(round(0.1 * fps))))
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

    def last_strong(t0, t1):
        """歌里 t0–t1 这段的最后一下重音：段里 hits 的最后一个，和段里最后 30% 中够重（段里起音的前一成）的最后一个，取更晚的"""
        hs = [h["t"] for h in hits if t0 - 1e-6 <= h["t"] <= t1 + 1e-6]
        inside = [j for j in range(len(pk)) if t0 - 1e-6 <= pk[j] / fps <= t1 + 1e-6]
        thr = np.percentile(strength[inside], 90) if inside else 0
        late = [pk[j] / fps for j in inside if pk[j] / fps > t0 + 0.7 * (t1 - t0) and strength[j] >= thr]
        cand = hs[-1:] + late[-1:]
        return round(float(max(cand)), 2) if cand else None
    last_hit = last_strong(0.0, dur)
    seg_last = last_strong(seg0, seg1) if seg else last_hit   # 只做一段：结尾画面落在这段自己的最后一下上，不是整首的

    # 起音（鼓点、拨弦这类）：上面挑出的峰，强度归一到 0–1，给页面卡小动作
    smax = float(strength.max()) if len(strength) else 0.0
    onsets = [[round(float(pk[j] / fps), 3), round(float(strength[j] / smax), 2)] for j in range(len(pk)) if smax and strength[j] / smax >= 0.08]

    # 响度包络：每秒 30 个点，0–1（最响处往下 36 dB 算 0），给页面让光、颗粒、镜头的呼吸跟着音乐起伏
    env_fps = 30
    tt = np.arange(0, dur, 1 / env_fps)
    ft = np.arange(len(L_all)) / fps

    def unit(L):
        hi = np.percentile(L, 98)
        return [round(float(v), 2) for v in np.clip((np.interp(tt, ft, L) - (hi - 36)) / 36, 0, 1)]
    env = {"fps": env_fps, "all": unit(L_all), "low": unit(L_low)}

    I, peak = lufs(a.song)
    bpm = 60 / period
    data = {"file": os.path.basename(a.song), "duration": round(dur, 2), "start": round(seg0, 3), "end": round(seg1, 2),
            "lufs": I, "true_peak": peak,
            "bpm": round(bpm, 2), "beat_interval": round(period, 4), "tempo_hint": a.tempo_hint,
            "beats_from": "segment" if local else "song",
            "beats": [round(float(t), 3) for t in bt], "downbeats": [round(float(t), 3) for t in downbeats],
            "sections": sections, "events": events, "hits": hits, "last_hit": last_hit, "segment_last_hit": seg_last,
            "onsets": onsets, "env": env}
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    if a.js:
        write_js(data, a.js, seg0, seg1)

    def inseg(t):
        return seg0 - 1e-6 <= t <= seg1 + 1e-6

    def at(t):
        """只做一段时，歌里的秒后面加成片秒"""
        if not seg:
            return ""
        return f"（成片 {fmt_t(t - seg0)}）" if inseg(t) else "（不在这段里）"

    print(f"# {data['file']} 的骨架\n")
    if seg:
        print(f"- 只做歌的 {fmt_t(seg0)}–{fmt_t(seg1)}，片长 {seg1 - seg0:.2f} 秒；括号里是成片秒")
    print(f"- 时长 {fmt_t(dur)}，响度 {I} LUFS（成片的音轨要和这个一样，差 1 dB 以上就是导出时变小了）")
    print(f"- BPM 约 {bpm:.1f}（按测到的拍点算{'这段的' if seg else ''}；一拍 {period:.3f} 秒，一小节 {4 * period:.2f} 秒）"
          + (f"，按 --tempo-hint {a.tempo_hint:g} 限定在上下 8% 里测的" if a.tempo_hint else
             "。自动测的可能差一倍或者锁成 3:4：上网搜这首歌的 BPM 对一下，或者浏览器打开 mv/index.html，看模板里的小球落地对不对得上鼓点；不对就加 --tempo-hint <搜到的 BPM> 重跑"))
    if local:
        print(f"- 这段自己测出来约 {local[1]:.1f} BPM，整首一起测的在这段里是 {local[0]:.1f}，差 2% 以上（中途变速、几段接起来的歌常这样）：拍点按这段自己测的。"
              "片段改长改短后拍点可能变，改了起止要重渲用到拍点的镜头")
    first_in = next((float(t) for t in downbeats if t >= seg0 - 1e-6), None) if seg else None
    print(f"- 共 {len(bt)} 拍；第一拍 {fmt_t(bt[0]) if len(bt) else '-'}，小节第一拍从 {fmt_t(downbeats[0]) if len(downbeats) else '-'}{at(downbeats[0]) if len(downbeats) else ''} 起每 4 拍一个（按 4/4 估的）"
          + (f"；这段里第一个是 {fmt_t(first_in)}{at(first_in)}" if first_in is not None and first_in != float(downbeats[0]) else ""))
    if unsure:
        print(f"- 小节第一拍拿不准（四种起法只差 {unsure[0] * 100:.0f}%），已对到 {fmt_t(unsure[1])}{at(unsure[1])} 的{unsure[2]}")
    print("\n## 分段（按音色和和声自动分的，不标主歌副歌；lyrics.srt 里重复出现、所在段又「强」的那组句子多半是副歌）\n")
    print("| 段 | 起 | 止 | 多响（和最响处比） |\n|---|---|---|---|")
    shown = 0
    for i, s in enumerate(sections, 1):
        if seg:   # 只列和这段有重叠的；段头段尾超出这段的，裁到这段的起止，写明整段从哪到哪
            if s["end"] <= seg0 + 1e-6 or s["start"] >= seg1 - 1e-6:
                continue
            b0 = f"{fmt_t(max(s['start'], seg0))}（成片 {fmt_t(max(s['start'], seg0) - seg0)}）" + (f"，这一段 {fmt_t(s['start'])} 就开始了" if s["start"] < seg0 - 1e-6 else "")
            b1 = f"{fmt_t(min(s['end'], seg1))}（成片 {fmt_t(min(s['end'], seg1) - seg0)}）" + (f"，这一段到 {fmt_t(s['end'])} 才完" if s["end"] > seg1 + 1e-6 else "")
        else:
            b0, b1 = fmt_t(s["start"]), fmt_t(s["end"])
        shown += 1
        print(f"| {i} | {b0} | {b1} | {s['level']}（{s['rel_db']} dB） |")
    if seg and shown < len(sections):
        print(f"\n（这段以外还有 {len(sections) - shown} 段没列）")
    print("\n## 突然变化的地方（镜头最该在这些点上变：停住、留白、换场、放最重要的画面）\n")
    ev = [e for e in events if inseg(e["t"])] if seg else events
    if ev:
        for e in ev:
            off_db = e["type"] in ("重新进来", "低音回来") and len(downbeats) and float(np.abs(downbeats - e["t"]).min()) > 0.1
            print(f"- {fmt_t(e['t'])}{at(e['t'])} {e['type']}（{e['change_db']:+} dB）"
                  + ("（不在小节第一拍上：副歌、大转场的落点以这里为准）" if off_db else ""))
    elif events:
        print("- 这段里没有明显的突变")
    else:
        print("- 没有明显的突变（整体 8 dB、低音 10 dB 以上的跌落或涨回都没有；这首歌很平，靠分段和副歌来变）")
    if seg and len(ev) < len(events):
        print(f"- （这段以外还有 {len(events) - len(ev)} 处没列）")
    print("\n## 最重的几下（适合卡点：转场、角色大动作、画面里的东西落下）\n")
    hs = [h for h in hits if inseg(h["t"])] if seg else hits
    if hs:
        print("- " + "、".join(fmt_t(h["t"]) + at(h["t"]) for h in hs))
    if seg:
        print(f"- 这是整首里最重的 8 下截到这段里的（这段里有 {len(hs)} 下）：片段改长改短，段里原有的这几下不变。"
              "页面里要某一下当锚点，按时间窗取（比如 17.6–19.5 秒之间那一下），别取 SONG.hits 的最后一个：片段一改，最后一个就换了")
    if seg_last:
        left = seg1 - seg_last
        what = "这段的最后一下重音" if seg else "最后一下重音"
        if left < 3:
            print(f"- {what}：{fmt_t(seg_last)}{at(seg_last)}（结尾画面落在这里，后面留白；song.js 的 last_hit）")
        else:
            print(f"- {what}：{fmt_t(seg_last)}{at(seg_last)}（离结尾还有 {left:.1f} 秒，后面还在唱；song.js 的 last_hit）")
    if a.out:
        print(f"\n每一拍的时间都在 {a.out} 里（beats、downbeats；歌里的秒）")
    if a.js:
        print(f"页面用的拍点和响度 → {a.js}（window.SONG" + (f"，成片秒，片长 {seg1 - seg0:.2f} 秒，start = {seg0:g}" if seg else "") + "）")


def write_js(d, path, s0, s1):
    """window.SONG：时间都换成成片的秒（歌里的秒 − s0），只留歌里 [s0, s1] 这段；start 记片头在歌里的秒数"""
    L = s1 - s0
    sh = lambda t: round(t - s0, 3)          # noqa: E731
    keep = lambda t: 0 <= t - s0 <= L + 1e-6  # noqa: E731
    fps = d["env"]["fps"]
    k, n = int(round(s0 * fps)), int(math.ceil(L * fps - 1e-6))
    env = {key: (([0.0] * -k + v) if k < 0 else v[k:])[:n] for key, v in d["env"].items() if key != "fps"}
    # 分段裁到这段里；裁出来短于 1 秒的头尾并进旁边那段
    secs = [dict(s, start=round(max(0.0, s["start"] - s0), 2), end=round(min(L, s["end"] - s0), 2))
            for s in d["sections"] if s["end"] - s0 > 0 and s["start"] - s0 < L]
    if len(secs) > 1 and secs[0]["end"] - secs[0]["start"] < 1:
        secs = [dict(secs[1], start=0.0)] + secs[2:]
    if len(secs) > 1 and secs[-1]["end"] - secs[-1]["start"] < 1:
        secs = secs[:-2] + [dict(secs[-2], end=round(L, 2))]
    hits = [dict(h, t=sh(h["t"])) for h in d["hits"] if keep(h["t"])]
    last = d.get("segment_last_hit", d["last_hit"])
    last = sh(last) if last is not None and keep(last) else (hits[-1]["t"] if hits else None)
    song = {"file": d["file"], "duration": round(L, 2), "start": round(s0, 3), "bpm": d["bpm"], "beat_interval": d["beat_interval"],
            "beats": [sh(t) for t in d["beats"] if keep(t)], "downbeats": [sh(t) for t in d["downbeats"] if keep(t)],
            "sections": secs,
            "events": [dict(e, t=sh(e["t"])) for e in d["events"] if keep(e["t"])],
            "hits": hits, "last_hit": last,
            "onsets": [[sh(t), s] for t, s in d["onsets"] if keep(t)],
            "env": dict(env, fps=fps)}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.SONG = " + json.dumps(song, ensure_ascii=False, separators=(",", ":")) + ";\n")


if __name__ == "__main__":
    main()
