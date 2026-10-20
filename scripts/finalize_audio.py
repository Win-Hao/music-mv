#!/usr/bin/env python3
"""把原曲按原音量封回成片。渲染器为了不爆音常把歌压小 2 dB 左右（HyperFrames 会压到 -1 dBTP 以下），
所以渲完不直接交，用这个把画面原样留着、音轨换成原曲，再量一下两边响度对不对得上。
    python3 scripts/finalize_audio.py render.mp4 song.mp3 -o mv.mp4
    python3 scripts/finalize_audio.py render.mp4 song.mp3 -o mv.mp4 --start 30.5      # MV 从歌的 30.5 秒开始
    python3 scripts/finalize_audio.py render.mp4 song.mp3 -o mv.mp4 --fade-out 2      # 最后 2 秒淡出
    python3 scripts/finalize_audio.py render.mp4 song.mp3 -o mv.mp4 --target-lufs -14  # 要整体调到某个响度（只调音量，不压缩）
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import lufs, need, probe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("song")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--start", type=float, default=0.0, help="成片第 0 秒对应歌的第几秒")
    ap.add_argument("--fade-out", type=float, default=0.0, help="最后几秒淡出")
    ap.add_argument("--target-lufs", type=float, help="把整首调到这个响度（只加减音量）")
    a = ap.parse_args()
    need("ffmpeg")
    if os.path.abspath(a.video) == os.path.abspath(a.out):
        sys.exit("输出不能覆盖输入，换个文件名")
    dur = probe(a.video)["duration"]
    song_i, song_pk = lufs(a.song, a.start, dur)
    af = []
    if a.target_lufs is not None and song_i is not None:
        af.append(f"volume={a.target_lufs - song_i:.2f}dB")
    if a.fade_out > 0:
        af.append(f"afade=t=out:st={max(0, dur - a.fade_out):.3f}:d={a.fade_out}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", a.video, "-ss", str(a.start), "-i", a.song,
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
           "-t", f"{dur:.3f}", "-movflags", "+faststart"]
    if af:
        cmd += ["-af", ",".join(af)]
    r = subprocess.run(cmd + [a.out], capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    out_i, out_pk = lufs(a.out)
    rend_i, _ = lufs(a.video) if probe(a.video)["audio"] else (None, None)
    print(f"原曲这一段：{song_i} LUFS，峰值 {song_pk} dBFS")
    if rend_i is not None:
        print(f"渲染出来的：{rend_i} LUFS（差 {rend_i - song_i:+.1f} dB）" if song_i is not None else f"渲染出来的：{rend_i} LUFS")
    print(f"封好的成片：{out_i} LUFS，峰值 {out_pk} dBFS → {a.out}")
    print(f"下一步自检：python3 scripts/video_rhythm.py {a.out} --analysis song-analysis.json")
    want = a.target_lufs if a.target_lufs is not None else song_i
    if out_i is not None and want is not None and abs(out_i - want) > 1.0 and not a.fade_out:
        print("⚠ 成片和目标差了 1 dB 以上，查一下 --start 对不对")


if __name__ == "__main__":
    main()
