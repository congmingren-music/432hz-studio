# -*- coding: utf-8 -*-
"""介绍视频 v3：内容加厚、解说先行、说完停顿再进演示。

时间轴（总 70.5 秒）：
  0.0–6.5    片头           voice1 @0.5
  6.5–18.0   音源           voice2 @6.7
  18.0–27.0  校准           voice3 @18.0
  27.0–37.5  界面           voice4 @27.0
  37.5–46.0  演示预告       voice5 @37.5（7.16 秒讲完，留 1.3 秒停顿）
  46.0–64.0  四重奏演示     18 秒纯音乐，无旁白
  64.0–70.5  结尾           voice6 @64.5
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

VOICE_AT = [0.5, 6.7, 18.0, 27.0, 37.5, 67.5]
SEG_LEN = [6.5, 11.5, 9.0, 10.5, 8.5, 18.0, 10.0]
TOTAL = sum(SEG_LEN)   # 70.5


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def card(path, lines, rule=True):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    if rule:
        d.rectangle([70, 70, 74, H - 70], fill=RULE)
    for text, size, bold, color, x, y in lines:
        d.text((x, y), text, font=font(F_BOLD if bold else F_REG, size), fill=color)
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

    # 1 片头
    p1 = card(os.path.join(OUT, "c1.png"), [
        ("432 Hz 工作室", 56, True, INK, 110, 230),
        ("本地音乐渲染器 · 四种真实采样音色", 24, False, INK2, 110, 312),
        ("选音源 · 导入乐谱 · 调参 · 出音频与视频", 20, False, TINT, 110, 362),
    ])

    # 2 音源
    p2 = card(os.path.join(OUT, "c2.png"), [
        ("四种真实采样", 44, True, INK, 110, 120),
        ("二胡", 30, True, INK2, 110, 240),
        ("编钟", 30, True, INK2, 110, 310),
        ("长笛", 30, True, INK2, 110, 380),
        ("钢琴", 30, True, INK2, 110, 450),
        ("全部是真实乐器录音，不是合成器", 20, False, TINT, 110, 560),
    ])

    # 3 校准
    p3 = card(os.path.join(OUT, "c3.png"), [
        ("A4 = 432.00 Hz", 52, True, INK, 110, 200),
        ("十二平均律 f(n) = 432 × 2^((n−69)/12)", 24, False, INK2, 110, 300),
        ("每个音单独对采样测频、按目标频率变调", 22, False, INK2, 110, 370),
        ("实测误差 < 1 音分", 26, True, INK, 110, 440),
    ])

    # 4 界面（截图）
    p4 = os.path.join(BASE, "studio", "ui5.png")

    # 5 演示预告
    p5 = card(os.path.join(OUT, "c5.png"), [
        ("四重奏 · 茉莉花", 52, True, INK, 110, 230),
        ("编钟前奏 → 二胡主旋律 → 长笛变奏 → 编钟尾声", 22, False, INK2, 110, 320),
        ("下面进入演示", 20, False, TINT, 110, 400),
    ])

    # 7 结尾
    p7 = card(os.path.join(OUT, "c7.png"), [
        ("打开就能用", 40, True, INK, 110, 250),
        ("python server.py", 28, True, INK2, 110, 330),
        ("http://127.0.0.1:8770", 28, False, TINT, 110, 385),
        ("需要 Python 3.10+ 与 ffmpeg", 19, False, TINT, 110, 470),
    ])

    segs = []
    for png, sec in ((p1, SEG_LEN[0]), (p2, SEG_LEN[1]), (p3, SEG_LEN[2])):
        segs.append(still(png, os.path.join(OUT, f"s{len(segs)+1}.mp4"), sec))

    if os.path.exists(p4):
        segs.append(still(p4, os.path.join(OUT, "s4.mp4"), SEG_LEN[3]))

    segs.append(still(p5, os.path.join(OUT, "s5.mp4"), SEG_LEN[4]))

    demo = os.path.join(BASE, "audio-432", "video", "432hz-quartet-茉莉花.mp4")
    if os.path.exists(demo):
        cut = os.path.join(OUT, "s6.mp4")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", demo, "-t", str(SEG_LEN[5]), "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "25", "-an", cut,
        ], check=True)
        segs.append(cut)

    segs.append(still(p7, os.path.join(OUT, "s7.mp4"), SEG_LEN[6]))

    listfile = os.path.join(OUT, "list3.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for s in segs:
            f.write(f"file '{s.replace(chr(92), '/')}'\n")

    silent = os.path.join(OUT, "silent3.mp4")
    subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", silent,
    ], check=True)

    voices = [os.path.join(OUT, f"voice-{i}.wav") for i in range(1, 7)]
    have_voice = all(os.path.exists(v) for v in voices)
    bgm = os.path.join(BASE, "audio-432", "432hz-quartet-茉莉花.wav")
    final = os.path.join(BASE, "432hz-studio-intro.mp4")

    if have_voice and os.path.exists(bgm):
        inputs = ["-i", silent]
        for v in voices:
            inputs += ["-i", v]
        # 配乐循环铺满全片（原曲只有 49.78 秒）
        inputs += ["-stream_loop", "-1", "-i", bgm]
        # 演示段单独铺一路原声
        inputs += ["-stream_loop", "-1", "-i", bgm]

        parts = []
        for idx, at in enumerate(VOICE_AT):
            ms = int(at * 1000)
            parts.append(f"[{idx+1}:a]adelay={ms}|{ms},volume=1.6[v{idx+1}]")
        bg_idx = len(voices) + 1
        demo_idx = len(voices) + 2
        parts.append(f"[{bg_idx}:a]atrim=0:{TOTAL},volume=0.16[bg]")
        demo_ms = int(SEG_LEN[0] + SEG_LEN[1] + SEG_LEN[2] + SEG_LEN[3] + SEG_LEN[4]) * 1000
        fade_at = SEG_LEN[5] - 1.5
        parts.append(f"[{demo_idx}:a]atrim=0:{SEG_LEN[5]},"
                     f"afade=t=out:st={fade_at}:d=1.5,"
                     f"volume=1.7,adelay={demo_ms}|{demo_ms}[demo]")
        mix_in = "".join(f"[v{i+1}]" for i in range(len(voices))) + "[bg][demo]"
        n_in = len(voices) + 2
        parts.append(f"{mix_in}amix=inputs={n_in}:duration=longest:dropout_transition=0:"
                     f"normalize=0,volume=0.8,alimiter=limit=0.93[aout]")

        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(parts),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", str(TOTAL), "-movflags", "+faststart", final,
        ], check=True)
    else:
        print("警告：旁白或配乐缺失")
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-i", silent, "-c", "copy", "-movflags", "+faststart", final,
        ], check=True)

    print(f"done: {final}  {os.path.getsize(final)/1024:.0f} KB  total {TOTAL}s")


if __name__ == "__main__":
    main()
