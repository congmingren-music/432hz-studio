# -*- coding: utf-8 -*-
"""生成 B 站投稿封面（1584×892，16:9）。"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

W, H = 1584, 892
PAPER = (247, 242, 235)
INK = (8, 31, 92)
INK2 = (51, 78, 172)
TINT = (112, 150, 209)
RULE = (216, 228, 244)

F_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
F_REG = r"C:\Windows\Fonts\msyh.ttc"

OUT = r"C:\我的\dsh\locales\cover-432.png"


def f(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


img = Image.new("RGB", (W, H), PAPER)
d = ImageDraw.Draw(img)

# 左侧竖线
d.rectangle([86, 86, 92, H - 86], fill=RULE)

# 主标题
d.text((140, 210), "432", font=f(F_BOLD, 168), fill=INK)
d.text((478, 296), "Hz", font=f(F_BOLD, 58), fill=INK2)

# 副标题
d.text((146, 410), "本地音乐渲染器", font=f(F_BOLD, 44), fill=INK)
d.text((146, 478), "四种真实乐器采样 · 逐音校准误差 < 1 音分", font=f(F_REG, 26), fill=INK2)

# 右侧乐器
x = 900
for i, name in enumerate(["二胡", "编钟", "长笛", "钢琴"]):
    d.text((x, 200 + i * 92), name, font=f(F_BOLD, 46), fill=INK2)

# 底部说明
d.text((146, 700), "可导入 MusicXML 乐谱 · 自定义编排 · 输出音频与频谱视频", font=f(F_REG, 24), fill=TINT)
d.text((146, 760), "开源 · 本地运行 · 不联网", font=f(F_REG, 24), fill=TINT)

# 右下角角标
d.rectangle([W - 300, H - 96, W - 86, H - 46], outline=TINT, width=2)
d.text((W - 286, H - 88), "真实采样", font=f(F_REG, 26), fill=TINT)

img.save(OUT, "PNG")
print(f"done: {OUT}")
