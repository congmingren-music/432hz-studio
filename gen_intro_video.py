# -*- coding: utf-8 -*-
"""生成 432 Hz 工作室的介绍视频（静帧卡片 + 界面截图 + 成品片段）。"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

FFMPEG = (os.environ.get("FFMPEG") or "ffmpeg")
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


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def card(path, lines):
    """lines: [(text, size, bold, color, y)]"""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([70, 70, 74, H - 70], fill=RULE)
    for text, size, bold, color, y in lines:
        f = font(F_BOLD if bold else F_REG, size)
        d.text((110, y), text, font=f, fill=color)
    img.save(path, "PNG")
    return path


def make_cards():
    os.makedirs(OUT, exist_ok=True)
    p1 = card(os.path.join(OUT, "c1.png"), [
        ("432 Hz 工作室", 56, True, INK, 220),
        ("本地音乐渲染器 · 四种真实采样音色", 24, False, INK2, 300),
        ("选音源 · 导入乐谱 · 调参 · 出音频与视频", 20, False, TINT, 350),
    ])
    p2 = card(os.path.join(OUT, "c2.png"), [
        ("它能做什么", 40, True, INK, 120),
        ("· 四种音源：二胡 / 编钟 / 长笛 / 钢琴（真实采样）", 24, False, INK2, 210),
        ("· 曲目：茉莉花 · 八音阶 · 五音阶 · Hijaz · 四重奏", 24, False, INK2, 262),
        ("· 导入 MusicXML：打谱软件写的谱直接变声音", 24, False, INK2, 314),
        ("· 自定义编排：段落增删、换音源、调顺序", 24, False, INK2, 366),
        ("· 上传自己的采样，自动测音高", 24, False, INK2, 418),
        ("· 输出 WAV + 频谱视频", 24, False, INK2, 470),
        ("所有声音按 A4 = 432.00 Hz 渲染，逐音校准误差 < 1 音分", 19, False, TINT, 560),
    ])
    p3 = card(os.path.join(OUT, "c3.png"), [
        ("操作界面", 40, True, INK, 90),
    ])
    p4 = card(os.path.join(OUT, "c4.png"), [
        ("打开就能用", 40, True, INK, 250),
        ("python server.py", 28, True, INK2, 330),
        ("http://127.0.0.1:8770", 28, False, TINT, 385),
        ("需要 Python 3.10+ 与 ffmpeg", 19, False, TINT, 470),
    ])
    return p1, p2, p3, p4


def still(png, mp4, seconds=3.0):
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "25", "-i", png,
        "-t", str(seconds), "-vf", f"scale={W}:{H}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", mp4,
    ], check=True)
    return mp4


def main():
    os.makedirs(OUT, exist_ok=True)
    p1, p2, p3, p4 = make_cards()

    segs = []
    segs.append(still(p1, os.path.join(OUT, "s1.mp4"), 3.2))
    segs.append(still(p2, os.path.join(OUT, "s2.mp4"), 5.0))

    # 界面截图（若存在）
    ui = os.path.join(BASE, "studio", "ui5.png")
    if os.path.exists(ui):
        # 截图裁成 16:9 居中
        segs.append(still(ui, os.path.join(OUT, "s3.mp4"), 3.0))

    # 成品片段：取四重奏视频前 18 秒
    demo = os.path.join(BASE, "audio-432", "video", "432hz-quartet-茉莉花.mp4")
    if os.path.exists(demo):
        cut = os.path.join(OUT, "s4.mp4")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", demo, "-t", "18", "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-an", cut,
        ], check=True)
        segs.append(cut)

    segs.append(still(p4, os.path.join(OUT, "s5.mp4"), 3.5))

    listfile = os.path.join(OUT, "list.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file '{s.replace(chr(92), '/')}'\n")

    silent = os.path.join(OUT, "silent.mp4")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", listfile,
        "-c", "copy", silent,
    ], check=True)

    # 配乐：用四重奏音频铺底，淡入淡出
    bgm = os.path.join(BASE, "audio-432", "432hz-quartet-茉莉花.wav")
    final = os.path.join(BASE, "432hz-studio-intro.mp4")
    if os.path.exists(bgm):
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", silent, "-i", bgm,
            "-filter_complex",
            "[1:a]volume=0.55,afade=t=in:st=0:d=1.5,afade=t=out:st=28:d=4[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", final,
        ], check=True)
    else:
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", silent, "-c", "copy", "-movflags", "+faststart", final,
        ], check=True)

    size = os.path.getsize(final) / 1024
    print(f"done: {final}  {size:.0f} KB")


if __name__ == "__main__":
    main()
