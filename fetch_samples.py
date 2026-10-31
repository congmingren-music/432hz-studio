# -*- coding: utf-8 -*-
"""一键下载四种音源的采样。

用法：
    python fetch_samples.py          # 下载全部
    python fetch_samples.py erhu     # 只下某一种（erhu|bell|flute|piano）

下载到 ../audio-432/ 下的对应目录（与 render_api.py 的路径约定一致）。
采样来源与许可见 README.md，下载即表示同意各自的许可条款。
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(BASE, "samples")
CDN = "https://gcore.jsdelivr.net/gh"
FALLBACK_CDN = "https://testingcf.jsdelivr.net/gh"

# 每项：(显示名, 仓库路径, 目标子目录, [文件名])
SOURCES = {
    "erhu": (
        "二胡（CC0）",
        "sfzinstruments/aliexpress-erhu@master/Samples/sus",
        "erhu",
        [f"erhu_{k}_sus_rr1.wav" for k in (
            "d5", "e5", "f5", "g5", "a5", "b5", "c6", "gb5", "ab5", "bb5", "eb5",
            "db6", "d6", "eb6", "gb6", "ab6")],
    ),
    "bell": (
        "编钟（MIT）",
        "wizonce9/A-Novel-Physical-Modeling-Approach-for-Sound-Synthesis-of-Chinese-Chime-Bells@master/Instrument/Bianzhong Samples",
        "bell",
        ["0 - 0009 - 音频 - b2.wav", "0 - 0011 - 音频 - a2.wav",
         "0 - 0013 - 音频 - g2.wav", "0 - 0016 - 音频 - e2.wav",
         "0 - 0019 - 音频 - d2.wav", "0 - 0021 - 音频 - c2.wav",
         "1 - 0073 - 音频 - f2.wav"],
    ),
    "flute": (
        "长笛（CC BY 4.0）",
        "sfzinstruments/Ixox.Flute@master/Samples",
        "flute",
        ["nor_m_1_1.flac", "nor_m_1_3.flac", "nor_m_1_4.flac", "nor_m_1_6.flac",
         "nor_m_2_1.flac", "nor_m_2_3.flac", "nor_m_2_4.flac", "nor_m_2_6.flac",
         "nor_m_3_1.flac"],
    ),
    "piano": (
        "钢琴（CC BY 3.0）",
        "sfzinstruments/SalamanderGrandPiano@master/Samples",
        "piano",
        ["C4v8.flac", "D#4v8.flac", "F#4v8.flac", "A4v8.flac", "C5v8.flac"],
    ),
}


def urlencode_path(path):
    """空格和 # 需要编码，其余保持原样（避免中文被重复编码）。"""
    return path.replace(" ", "%20").replace("#", "%23")


def fetch(repo_path, fname, dst):
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return True, "已存在"
    for cdn in (CDN, FALLBACK_CDN):
        url = f"{cdn}/{repo_path}/{urlencode_path(fname)}"
        r = subprocess.run(
            ["curl", "-L", "--fail", "--silent", "--show-error",
             "--max-time", "120", "-o", dst, url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 1000:
            return True, "ok"
        if os.path.exists(dst):
            os.remove(dst)
    return False, "下载失败"


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    targets = [want] if want else list(SOURCES)
    total_ok = 0
    total_fail = 0

    for key in targets:
        if key not in SOURCES:
            print(f"未知音源：{key}（可选 {', '.join(SOURCES)}）")
            continue
        label, repo_path, subdir, files = SOURCES[key]
        d = os.path.join(SAMPLES, subdir)
        os.makedirs(d, exist_ok=True)
        print(f"\n== {label} → {subdir} ==")
        for f in files:
            dst = os.path.join(d, f)
            ok, msg = fetch(repo_path, f, dst)
            if ok:
                total_ok += 1
                size = os.path.getsize(dst) / 1024
                print(f"  {f}  {size:.0f} KB  ({msg})")
            else:
                total_fail += 1
                print(f"  {f}  FAIL")

    print(f"\n完成：成功 {total_ok}，失败 {total_fail}")
    if total_fail:
        print("失败项可重试——CDN 会限流，稍等再跑一次即可。")


if __name__ == "__main__":
    main()
