# -*- coding: utf-8 -*-
"""介绍视频 v2：加中文旁白、拉长界面页、保留 18 秒演示。

时间轴（总长约 40 秒）：
  0.0–5.0    片头        voice1 @0.3
  5.0–12.0   功能        voice2 @5.2
  12.0–17.5  界面        voice3 @12.3
  17.5–35.5  四重奏演示   voice4 @17.9（只说一句，其余留白给音乐）
  35.5–40.0  结尾        voice5 @36.0

旁白由 make_voice.ps1 用 Windows SAPI（Microsoft Huihui Desktop, zh-CN）生成。
"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

FFMPEG = os.environ.get("FFMPEG") or r"C:\Users\cmr\.video-watch\tools\ffmpeg-full\bin\ffmpeg.exe"
BASE = r"C:\我的\dsh\locales"
OUT = os.path.join(BASE, "intro")
W, H = 1280, 720

PAPER = (247, 242, 235)
INK = (8, 31, 92)
INK2 = (51, 78, 172)
TINT = (112, 150, 209)
RULE = (216, 228, 244)
F_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
F_REG = r"C:\Windows\Fonts\msyh.ttc"

# 旁白时间点（秒）
VOICE_AT = [0.3, 5.2, 12.3, 17.9, 36.0]


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def card(path, lines):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([70, 70, 74, H - 70], fill=RULE)
    for text, size, bold, color, y in lines:
        d.text((110, y), text, font=font(F_BOLD if bold else F_REG, size), fill=color)
    img.save(path, "PNG")
    return path


def still(png, mp4, seconds):
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "25", "-i", png,
        "-t", str(seconds), "-vf", f"scale={W}:{H}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", mp4,
    ], check=True)
    return mp4


def main():
    os.makedirs(OUT, exist_ok=True)

    p1 = card(os.path.join(OUT, "c1.png"), [
        ("432 Hz 工作室", 56, True, INK, 230),
        ("本地音乐渲染器 · 四种真实采样音色", 24, False, INK2, 312),
        ("选音源 · 导入乐谱 · 调参 · 出音频与视频", 20, False, TINT, 362),
    ])
    p2 = card(os.path.join(OUT, "c2.png"), [
        ("它能做什么", 40, True, INK, 110),
        ("· 四种音源：二胡 / 编钟 / 长笛 / 钢琴（真实采样）", 24, False, INK2, 200),
        ("· 曲目：茉莉花 · 八音阶 · 五音阶 · Hijaz · 四重奏", 24, False, INK2, 252),
        ("· 导入 MusicXML：打谱软件写的谱直接变声音", 24, False, INK2, 304),
        ("· 自定义编排：段落增删、换音源、调顺序", 24, False, INK2, 356),
        ("· 上传自己的采样，自动测音高", 24, False, INK2, 408),
        ("· 输出 WAV + 频谱视频", 24, False, INK2, 460),
        ("所有声音按 A4 = 432.00 Hz 渲染，逐音校准误差 < 1 音分", 19, False, TINT, 550),
    ])
    p3 = card(os.path.join(OUT, "c3.png"), [("操作界面", 40, True, INK, 90)])
    p4 = card(os.path.join(OUT, "c4.png"), [
        ("打开就能用", 40, True, INK, 250),
        ("python server.py", 28, True, INK2, 330),
        ("http://127.0.0.1:8770", 28, False, TINT, 385),
        ("需要 Python 3.10+ 与 ffmpeg", 19, False, TINT, 470),
    ])

    segs = []
    segs.append(still(p1, os.path.join(OUT, "s1.mp4"), 5.0))
    segs.append(still(p2, os.path.join(OUT, "s2.mp4"), 7.0))

    ui = os.path.join(BASE, "studio", "ui5.png")
    if os.path.exists(ui):
        segs.append(still(ui, os.path.join(OUT, "s3.mp4"), 5.5))

    demo = os.path.join(BASE, "audio-432", "video", "432hz-quartet-茉莉花.mp4")
    if os.path.exists(demo):
        cut = os.path.join(OUT, "s4.mp4")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", demo, "-t", "18", "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-an", cut,
        ], check=True)
        segs.append(cut)

    segs.append(still(p4, os.path.join(OUT, "s5.mp4"), 4.5))

    listfile = os.path.join(OUT, "list.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file '{s.replace(chr(92), '/')}'\n")

    silent = os.path.join(OUT, "silent2.mp4")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", listfile,
        "-c", "copy", silent,
    ], check=True)

    # 旁白 + 配乐
    voices = [os.path.join(OUT, f"voice-{i}.wav") for i in range(1, 6)]
    have_voice = all(os.path.exists(v) for v in voices)

    bgm = os.path.join(BASE, "audio-432", "432hz-quartet-茉莉花.wav")
    final = os.path.join(BASE, "432hz-studio-intro.mp4")

    if have_voice:
        inputs = ["-i", silent]
        for v in voices:
            inputs += ["-i", v]
        inputs += ["-i", bgm]

        # 旁白各段延迟到对应时刻；配乐压到 0.32
        parts = []
        for idx, at in enumerate(VOICE_AT):
            ms = int(at * 1000)
            parts.append(f"[{idx+1}:a]adelay={ms}|{ms},volume=1.6[v{idx+1}]")
        bg_idx = len(voices) + 1
        parts.append(f"[{bg_idx}:a]volume=0.22[bg]")

        mix_in = "".join(f"[v{i+1}]" for i in range(len(voices))) + "[bg]"
        n_in = len(voices) + 1
        parts.append(f"{mix_in}amix=inputs={n_in}:duration=longest:dropout_transition=0:normalize=0,volume=0.8,alimiter=limit=0.93[aout]")

        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", "40.04", "-movflags", "+faststart", final,
        ], check=True)
    else:
        print("警告：旁白缺失，只合成配乐")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", silent, "-i", bgm,
            "-filter_complex", "[1:a]volume=0.4,afade=t=out:st=34:d=5[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", final,
        ], check=True)

    print(f"done: {final}  {os.path.getsize(final)/1024:.0f} KB")


if __name__ == "__main__":
    main()
