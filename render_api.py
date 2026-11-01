# -*- coding: utf-8 -*-
"""432Hz 工作室 · 渲染引擎

参数化的采样渲染核心，供 HTTP 服务调用。
支持：内置音源（二胡/编钟/长笛/钢琴）+ 用户上传采样；曲目与速度可调。
"""
import datetime
import itertools
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave

import numpy as np

def _find_ffmpeg():
    """按 环境变量 FFMPEG → PATH → 本机已知路径 的顺序定位 ffmpeg。"""
    env = os.environ.get("FFMPEG")
    if env and os.path.exists(env):
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    for p in (r"C:\Users\cmr\.video-watch\tools\ffmpeg-full\bin\ffmpeg.exe",):
        if os.path.exists(p):
            return p
    return "ffmpeg"


FFMPEG = _find_ffmpeg()
BASE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(BASE, "samples")
USER_DIR = os.path.join(SAMPLES, "user")
OUT_DIR = os.path.join(BASE, "out")
SR = 44100

# ── 内置音源：名称 -> (目录, 文件名模板正则, 实测基频表, 起音跳过秒) ──
BUILTIN = {
    "erhu": {
        "label": "二胡",
        "dir": os.path.join(SAMPLES, "erhu"),
        "pattern": r"erhu_{key}_sus_rr1\.wav$",
        "hz": {"d5": 292.39, "eb5": 310.40, "e5": 330.36, "f5": 349.77, "gb5": 368.59,
               "g5": 393.31, "ab5": 415.91, "a5": 442.42, "bb5": 467.48, "b5": 494.33,
               "c6": 527.51, "db6": 553.92, "d6": 593.59, "eb6": 621.88,
               "gb6": 739.77, "ab6": 832.92},
        "seek": 0.24,
    },
    "bell": {
        "label": "编钟",
        "dir": os.path.join(SAMPLES, "bell"),
        "pattern": r" - {key}\.wav$",
        "hz": {"c2": 524.87, "d2": 590.82, "e2": 662.15, "f2": 699.83,
               "g2": 785.96, "a2": 884.21, "b2": 987.84},
        "seek": None,
    },
    "flute": {
        "label": "长笛",
        "dir": os.path.join(SAMPLES, "flute"),
        "pattern": r"{key}\.flac$",
        "hz": {"nor_m_1_1": 261.83, "nor_m_1_3": 312.23, "nor_m_1_4": 372.11,
               "nor_m_1_6": 440.09, "nor_m_2_1": 524.58, "nor_m_2_3": 622.65,
               "nor_m_2_4": 739.99, "nor_m_2_6": 880.06, "nor_m_3_1": 1046.07},
        "seek": None,
    },
    "piano": {
        "label": "钢琴",
        "dir": os.path.join(SAMPLES, "piano"),
        "pattern": r"{key}v8\.flac$",
        "hz": {"C4": 261.41, "D#4": 311.31, "F#4": 369.40, "A4": 440.12, "C5": 524.53},
        "seek": None,
    },
    "guzheng": {
        "label": "古筝",
        "dir": os.path.join(SAMPLES, "guzheng"),
        "pattern": r"guzheng-{key}-v1-rr1\.flac$",
        # 实测基频（440 基准）。古筝是五声调弦，部分采样点偏离十二平均律，
        # 用实测值算变调比率即可自动补偿。
        "hz": {"38": 73.11, "43": 96.69, "45": 110.97, "50": 147.30, "53": 175.07,
               "55": 195.48, "57": 221.03, "60": 262.87, "62": 292.75, "65": 342.29,
               "67": 390.88, "72": 523.30, "74": 587.57, "79": 801.18, "86": 1194.09},
        # 谐波纯度实测（2026-10-31）：43/60/79/86 四个采样的最强成分不在整数倍泛音上，
        # 技术上会产生金属感；但 A/B 试听后用户认为「原采样更好听」——变调升上去会变薄，
        # 比金属感更难受。所以默认不排除，需要时把 key 加进 avoid 再试。
        # 高音区策略：经 A/B 试听，用户选定「排除 79/86、用 74 升调补厚」这一版。
        # 86 降调虽然谐波能量更整齐（G5 75% vs 28%），但听感被判定「方向不对」，默认关闭。
        "avoid": {"79", "86"},
        # per-midi 强制指定采样（比 avoid 精确：只改这个音，不动同采样覆盖的其他音）。
        # E4(64) 原用 65 号降 0.7 半音，三窗口谐波 95.7/24.6/15.9 极不稳定（采样某段带杂音），
        # 改 62 号升 2 半音实测 87.1%，稳定得多。
        "map": {"64": "62"},
        "high_key": None,
        "high_from": 76,
        "seek": None,
    },
    "xiao": {
        "label": "箫（竖笛近似）",
        "dir": os.path.join(SAMPLES, "xiao"),
        # key 直接用文件名，pattern 原样匹配
        "pattern": r"{key}",
        # 素材实为 BassRecorder / TenRecorder（竖笛），非真箫；作者以 -xiao 后缀模仿箫的音色
        "hz": {"BassRecorder_Sus_Fs2_rr1_Main-xiao.flac": 185.06, "BassRecorder_Sus_Gs2_rr1_Main-xiao.flac": 208.65, "BassRecorder_Sus_As2_rr1_Main-xiao.flac": 232.16, "TenRecorder_Sus_C3_rr1_Main-xiao.flac": 261.95, "TenRecorder_Sus_D3_rr1_Main-xiao.flac": 293.62, "TenRecorder_Sus_E3_rr1_Main-xiao.flac": 328.52, "TenRecorder_Sus_Fs3_rr1_Main-xiao.flac": 370.75, "TenRecorder_Sus_Gs3_rr1_Main-xiao.flac": 416.22, "TenRecorder_Sus_As3_rr1_Main-xiao.flac": 466.51, "TenRecorder_Sus_C4_rr1_Main-xiao.flac": 522.70, "TenRecorder_Sus_D4_rr1_Main-xiao.flac": 587.96, "TenRecorder_Sus_E4_rr1_Main-xiao.flac": 659.95, "TenRecorder_Sus_Fs4_rr1_Main-xiao.flac": 741.46, "TenRecorder_Sus_Gs4_rr1_Main-xiao.flac": 830.67, "TenRecorder_Sus_A4_rr1_Main-xiao.flac": 881.31, "TenRecorder_Sus_C5_rr1_Main-xiao.flac": 1046.05},
        "seek": None,
    },
    "suona": {
        # ⚠️ 2026-11-01 查明：这套素材**不是唢呐，是双簧管**。
        # 上游 README 原文写的是「唢呐 · 双簧管代」，文件名全是 Oboe_*。
        # 双簧管圆润、鼻音轻，唢呐尖锐、鼻音重——处理手段改不了这个本质差异。
        # 所以如实按双簧管使用；高音替身改由编钟（bell，F#5–A6 谐波 83–99%）承担。
        "label": "双簧管（唢呐代）",
        "dir": os.path.join(SAMPLES, "suona"),
        "pattern": r"suona-{key}-v\d\.flac$",
        # 音高来自 sfz 的 pitch_keycenter（= 文件名音名 MIDI + 12），基频用理论值：
        # 实测严重受强泛音干扰（A#2 的 1167 Hz 是 233 Hz 的第 5 泛音），故不采信自动检测。
        "hz": {"58": 233.08, "62": 293.66, "65": 349.23, "70": 466.16,
               "74": 587.33, "77": 698.46, "82": 932.33, "86": 1174.66, "89": 1396.91},
        "seek": None,
    },
    "guqin": {
        # 2026-11-01 用户提供「古琴采音.zip」：散音 7 个（真古琴七弦正调）+ 泛音 7 个。
        # 散音自相关实测与正调完全吻合：C2 64.66 / D2 73.38 / F2 87.33 / G2 98.44 /
        # A2 110.80 / C3 130.09 / D3 147.00，偏差都在 ±20 音分内。表里用理论值更稳。
        # ⚠️ 只有 7 个音（C2–D3），弹 G2–G4 的旋律要升 1–3 倍，变调质量待测。
        "label": "古琴（散音七弦）",
        "dir": os.path.join(SAMPLES, "guqin"),
        "pattern": r"guqin-{key}\.wav$",
        "hz": {"36": 65.41, "38": 73.42, "41": 87.31, "43": 98.0,
               "45": 110.0, "48": 130.81, "50": 146.83},
        "seek": None,
    },
    "guqinfan": {
        # 古琴泛音（2026-11-01 同一批采音里的「泛1-7」）。
        # 泛音是古琴三音色（散音/按音/泛音）之一，音色清亮、接近纯音。
        # 音高用自相关实测值；它们不是连续音阶（G3 A3 G4 C5 D5 E5 A5），
        # 弹中间的音靠变调，所以更适合做点缀而不是主奏。
        "label": "古琴泛音",
        "dir": os.path.join(SAMPLES, "guqin"),
        "pattern": r"guqinfan-{key}\.wav$",
        "hz": {"55": 194.27, "57": 220.50, "67": 397.30, "72": 518.82,
               "74": 588.00, "76": 668.18, "81": 882.00},
        "seek": None,
    },
}

# ── 曲目：MIDI + 时长 ──
MOLIHUA = [
    (76, 0.36), (74, 0.36), (76, 0.36), (79, 0.36),
    (81, 0.36), (79, 0.36), (72, 0.42), (81, 0.36),
    (79, 0.42), (76, 0.36),
    (79, 0.36), (81, 0.60),
    (72, 0.36), (74, 0.36), (76, 0.36),
    (74, 0.36), (72, 0.36), (81, 0.36), (72, 0.44),
    (79, 1.20),
    (79, 0.36), (76, 0.36), (79, 0.36), (81, 0.55),
    (72, 0.34), (74, 0.34), (76, 0.34), (72, 0.34), (81, 0.34), (79, 0.44),
    (79, 0.36), (74, 0.34), (76, 0.34), (79, 0.34), (76, 0.34), (74, 0.44),
    (72, 0.36), (81, 0.36), (72, 1.00),
]

PIECES = {
    "molihua": {"label": "茉莉花（主歌）", "notes": MOLIHUA},
    "bayin": {"label": "八音阶", "notes": [(m, 0.5) for m in (72, 74, 76, 77, 79, 81, 83, 84)]},
    "wuyin": {"label": "五音阶", "notes": [(m, 0.55) for m in (66, 68, 70, 61 + 12, 63 + 12)]},
    "hijaz": {"label": "Hijaz 音阶", "notes": [(m, 0.5) for m in (78, 79, 82, 83, 85, 86, 88, 90)]},
}


def _ensure_dirs():
    os.makedirs(USER_DIR, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)


def read_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return sr, a


def peak_near(sig, sr, center, width=0.07):
    lo, hi = center * (1 - width), center * (1 + width)
    win = np.hanning(sig.size)
    spec = np.abs(np.fft.rfft(sig * win))
    freqs = np.fft.rfftfreq(sig.size, d=1.0 / sr)
    band = (freqs >= lo) & (freqs <= hi)
    if not np.any(band):
        return None
    idxs = np.flatnonzero(band)
    k = idxs[np.argmax(spec[band])]
    if 0 < k < len(spec) - 1:
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        denom = a - 2 * b + c
        d = 0.5 * (a - c) / denom if denom != 0 else 0.0
    else:
        d = 0.0
    return float((k + d) * sr / sig.size)


# 音色补偿：高音区古筝弦本身偏亮（听着像「电铃」），低音区基频弱（听着发闷）。
# ⚠️ 这些补丁是**专门为古筝调的**。2026-11-01 实测：套到唢呐身上会把它的低频压掉 7 dB
# （−36.6 → −29.7 dB），长笛/箫同理。所以只有 TONE_BY 里列出的音源才套补丁，其余中性。
# 0 表示不处理；可用 tune_tone.py 做 A/B。
TONE = {
    "bright_midi": 74,     # >= 这个 MIDI 视为高音区
    "bright_gain": -3.0,   # 高音区高频增益（dB，负数=柔化）
    "shelf_hz": 7000,      # 高频搁架起点
    "warm_midi": 50,       # <= 这个 MIDI 视为低音区
    "warm_gain": 2.5,      # 低音区低频增益（dB，正数=补厚度）
    "low_hz": 180,         # 低频搁架起点
}

# 哪些音源套用上面的补丁。古筝是它服务的对象，其他音源一律中性——
# 证据：关掉补丁后唢呐低频回升 6.9 dB，音色才恢复它自己的胸腔共鸣。
TONE_BY = {"guzheng"}


# 按音源平衡音量（2026-11-01 实测各音源 RMS 后标定）。
# 差异极大：长笛 -14.9 dBFS、古筝 -21.1、编钟 -28.7、古琴 -51.0、古琴泛音 -61.3。
# 古琴/泛音的录音电平很低但信噪比健康（16–29 dB），放大后底噪仍在 -40 dB 以下，可以放心补。
GAIN_BY = {
    "guqin": 28.0,      # +28.9 dB（-51.0 → 约 -22）
    "guqinfan": 45.0,   # +33.1 dB（-61.3 → 约 -28）
    "guzheng": 1.0,     # 基准
    "flute": 1.0,
    "bell": 1.6,        # +4.1 dB
    "piano": 1.6,
    "erhu": 1.0,
    "xiao": 1.0,
    "suona": 1.0,
}

# 整曲输出增益（dB）：再往上提一点整体响度。
# ⚠️ 2026-11-01 用 tanh 做软限幅被判定「有压扁的感觉」——因为 tanh 是**全段连续压缩**，
# 不是只在峰值处介入。改成只压缩超过阈值的那部分（软膝），其余样本原样保留。
OUTPUT_GAIN_DB = 3.0
LIMIT_THRESHOLD = 0.92   # 超过这个值才压缩


def _soft_limit(x, thresh=LIMIT_THRESHOLD):
    """软膝限幅：只压超过 thresh 的样本，其余不动。避免整段被压扁。"""
    absx = np.abs(x)
    over = absx > thresh
    if not over.any():
        return x
    out = x.copy()
    # 超出部分按 1/4 斜率收进去，最高映射到 0.99
    out[over] = np.sign(x[over]) * (thresh + (absx[over] - thresh) * 0.25)
    return np.clip(out, -0.99, 0.99)


def _tone_filters(midi, timbre=None):
    """按音高返回音色补偿滤镜。只有 TONE_BY 白名单里的音源才套用。"""
    if timbre is not None and timbre not in TONE_BY:
        return []
    out = []
    if TONE.get("bright_gain") and midi >= TONE["bright_midi"]:
        out.append(f"highshelf=f={int(TONE['shelf_hz'])}:g={float(TONE['bright_gain']):.1f}")
    if TONE.get("warm_gain") and midi <= TONE["warm_midi"]:
        out.append(f"lowshelf=f={int(TONE['low_hz'])}:g={float(TONE['warm_gain']):.1f}")
    return out


def midi_of(freq):
    return 69 + 12 * math.log2(freq / 440.0)


# ── 古琴曲库（guqin/<曲集>/<曲名>.xml，MusicXML）──
# 408 首全量解析太慢，所以只建索引（扫文件名），真正解析在 piece_notes() 里按需做并缓存。
GUQIN_DIR = os.path.join(BASE, "guqin")
_GUQIN_INDEX = None
_GUQIN_NOTES = {}


def guqin_index():
    """扫描 guqin/ 目录（含一级子目录），返回 {id: {label, album, path}}。"""
    global _GUQIN_INDEX
    if _GUQIN_INDEX is not None:
        return _GUQIN_INDEX
    idx = {}
    if os.path.isdir(GUQIN_DIR):
        for root, _dirs, files in os.walk(GUQIN_DIR):
            album = "" if os.path.abspath(root) == os.path.abspath(GUQIN_DIR) else os.path.basename(root)
            for name in sorted(files):
                if not name.lower().endswith((".xml", ".musicxml")):
                    continue
                stem = os.path.splitext(name)[0]
                pid = f"guqin-{album}-{stem}" if album else f"guqin-{stem}"
                idx[pid] = {
                    "label": f"{album} · {stem}" if album else stem,
                    "album": album or "古琴",
                    "path": os.path.join(root, name),
                }
    _GUQIN_INDEX = idx
    return idx


def piece_notes(pid):
    """取曲目音符：内置 PIECES 直接给；古琴曲按需解析并缓存。"""
    if pid in PIECES:
        return PIECES[pid]["notes"]
    if pid in _GUQIN_NOTES:
        return _GUQIN_NOTES[pid]
    ent = guqin_index().get(pid)
    if not ent:
        return None
    notes = None
    try:
        import musicxml
        tracks, _meta = musicxml.parse_musicxml_tracks(ent["path"])
        main = musicxml.pick_main_track(tracks)
        if main and main["notes"]:
            notes = [[int(n["midi"]), float(n["dur"]), float(n["start"])] for n in main["notes"]]
    except Exception:
        notes = None
    _GUQIN_NOTES[pid] = notes
    return notes


def all_pieces():
    """给界面用的曲目清单 [{id, label, group}]。"""
    out = [{"id": k, "label": v["label"], "group": "内置"} for k, v in PIECES.items() if k != "quartet"]
    out += [{"id": k, "label": v["label"], "group": v["album"]} for k, v in guqin_index().items()]
    return out



def user_sources():
    """扫描用户上传的采样包，返回 {id: {label, samples:[{midi, hz, path}]}}。"""
    _ensure_dirs()
    out = {}
    if not os.path.isdir(USER_DIR):
        return out
    for name in sorted(os.listdir(USER_DIR)):
        d = os.path.join(USER_DIR, name)
        meta_path = os.path.join(d, "meta.json")
        if not os.path.isdir(d) or not os.path.exists(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            out[name] = meta
        except Exception:
            continue
    return out


def analyze_upload(path):
    """上传一个采样：解码 → 测基频 → 返回 (hz, midi)。"""
    tmp = os.path.join(OUT_DIR, "_probe.wav")
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", path,
         "-t", "3", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", tmp],
        check=True, capture_output=True,
    )
    sr, sig = read_wav(tmp)
    os.remove(tmp)
    # 取稳定段
    seg = sig[int(0.3 * sr):int(min(2.5, len(sig) / sr) * sr)]
    if seg.size < 2048:
        raise ValueError("采样太短")

    # 基频检测：最强峰常常是 2 次/3 次泛音（钢琴、竖笛、古筝尤甚），
    # 所以把最强峰按整数倍往下折，取「谐波序列能量总和」最大的候选当基频。
    win = np.hanning(seg.size)
    spec = np.abs(np.fft.rfft(seg * win))
    freqs = np.fft.rfftfreq(seg.size, d=1.0 / SR)
    band = (freqs >= 60) & (freqs <= 1600)
    if not band.any():
        raise ValueError("测不出基频")
    idxs = np.flatnonzero(band)
    peak = float(freqs[idxs[np.argmax(spec[idxs])]])

    best, best_score = peak, -1.0
    for n in range(1, 9):
        f = peak / n
        if f < 55.0:
            break
        score = 0.0
        for k in range(1, 7):
            fk = f * k
            if fk > freqs[-1]:
                break
            j = int(np.argmin(np.abs(freqs - fk)))
            score += spec[max(0, j - 2):j + 3].max() / (1.0 + (k - 1) * 0.35)
        if score > best_score:
            best, best_score = f, score
    hz = best
    return float(hz), int(round(midi_of(hz)))


def _resolve_source(timbre):
    builtin = BUILTIN.get(timbre)
    if builtin:
        return {
            "id": timbre,
            "label": builtin["label"],
            "dir": builtin["dir"],
            "pattern": builtin["pattern"],
            "seek": builtin["seek"],
            "seek_map": builtin.get("seek_map"),
            "map": builtin.get("map"),
            "avoid": builtin.get("avoid", set()),
            "high_key": builtin.get("high_key"),
            "high_from": builtin.get("high_from", 999),
            "samples": [{"key": k, "hz": v} for k, v in builtin["hz"].items()],
        }
    users = user_sources()
    if timbre in users:
        u = users[timbre]
        return {
            "id": timbre,
            "label": u.get("label", timbre),
            "dir": os.path.join(USER_DIR, timbre),
            "pattern": "{key}",
            "seek": None,
            "samples": [{"key": s["file"], "hz": s["hz"]} for s in u["samples"]],
        }
    raise KeyError(f"未知音源 {timbre}")


def _find_file(directory, pattern, key):
    pat = pattern.replace("{key}", re.escape(key))
    for name in os.listdir(directory):
        if re.search(pat, name):
            return os.path.join(directory, name)
    return None


_RR_COUNTER = itertools.count()


def _find_files(directory, pattern, key):
    """同一音高的全部变体（v1/v2 × rr1/rr2/rr3）。只有表里写了 v1/rr1 的正则，这里放宽。"""
    pat = pattern.replace("{key}", re.escape(key))
    pat = pat.replace("v1", r"v\d").replace("rr1", r"rr\d")
    if not os.path.isdir(directory):
        return []
    hits = [n for n in os.listdir(directory) if re.search(pat, n)]
    return [os.path.join(directory, n) for n in sorted(hits)]


def _pick_sample_file(src, key):
    """多 rr 采样时轮换，避免同一音符每次都用同一个取样（重复会显得机械）。"""
    files = _find_files(src["dir"], src["pattern"], key)
    if not files:
        return _find_file(src["dir"], src["pattern"], key)
    if len(files) == 1:
        return files[0]
    return files[next(_RR_COUNTER) % len(files)]


def _nearest(samples, midi, avoid=()):
    """选最近采样点；avoid 里的 key 视为质量不合格（非谐波，会发声金属感）跳过。"""
    pool = [s for s in samples if str(s["key"]) not in avoid] or samples
    best = None
    for s in pool:
        smidi = midi_of(s["hz"])
        diff = midi - smidi
        if best is None or abs(diff) < abs(best["diff"]):
            best = {"key": s["key"], "hz": s["hz"], "diff": diff, "smidi": smidi}
    return best


def _out_name(prefix, tempo):
    """输出文件名带时间戳，避免同速度重复渲染把上一次成品覆盖掉。

    ⚠️ Windows 文件名里 `:` 是 NTFS 数据流分隔符，写出来的文件主名不存在，必须清掉。
    """
    safe = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", prefix).strip("_")
    return f"{safe}-{int(tempo * 100)}-{datetime.datetime.now():%Y%m%d-%H%M%S}.wav"


# ── 按音域分工（2026-11-01 用户选定 B 方案）──
# 古筝只有 35 个采样（五声调弦），半音位和 C6 以上靠变调凑，谐波掉到 15–36%；
# 中低音区（≤A4）实测 76–99%，是它真正的可用范围。
# 所以：古筝退守 A4 以下，A#4–C6 交长笛，C#6 以上交编钟（F#5–A6 实测 83–99.7%）。
# 这不是"修补古筝"，是让它只在自己能弹的地方弹——之前七条修补路线全部失败后得出的结论。
SPLIT_DEFAULT = [("guzheng", 0, 70), ("flute", 70, 85), ("bell", 85, 128)]


def render_piece(timbre, piece, tempo=1.0, ring=2.0, on_progress=None,
                 alt=None, alt_from=81, alt_to=None, style=None,
                 shadow=None, shadow_from=78, shadow_gain=0.4, split="default"):
    """整曲渲染。

    alt/alt_from/alt_to：**高音段换乐器**。旋律的 midi 落在 [alt_from, alt_to] 区间时
    改用 alt 这个音源弹（默认向上不限）。

    shadow/shadow_from/shadow_gain：**高音段叠加遮盖层**。主奏照常弹，但 midi ≥ shadow_from
    的音同时叠一层 shadow 音源（同音高），用它的金属余音盖住古筝高音的刺耳。
    2026-11-01 用户提出：与其换掉古筝，不如叠编钟掩盖——保留古筝音色又能压住问题。

    split：**按音域分工**（比 alt 更灵活，推荐用这个）。格式
    `[("guzheng", 0, 70), ("flute", 70, 85), ("bell", 85, 128)]`，
    每个元素是 (音源, lo, hi)，midi 落在 [lo, hi) 的音用该音源。
    背景：古筝只有 35 个采样（五声调弦），半音位和 C6 以上靠变调凑，谐波只有 15–36%；
    中低音区（≤A4）实测 76–99%，是它真正的可用范围。所以让它退守中低音。

    style：驻波方案，见 STYLE_PRESETS（clean/alive/body/rich）。None = 沿用当前全局状态。
    """
    _ensure_dirs()
    if style:
        set_style(style)
    src = _resolve_source(timbre)
    alt_src = _resolve_source(alt) if alt else None
    if split == "default":
        split = SPLIT_DEFAULT
    split_layers = None
    if split:
        split_layers = [(_resolve_source(t), float(lo), float(hi)) for t, lo, hi in split]
    shadow_src = _resolve_source(shadow) if shadow else None
    notes = piece_notes(piece)
    if not notes:
        raise KeyError(f"未知曲目 {piece}")

    tmp_dir = os.path.join(OUT_DIR, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # 二元组 [midi, dur] 顺序累加；三元组 [midi, dur, start] 按谱面绝对时间定位（古琴曲库走这条）
    has_start = bool(notes) and len(notes[0]) >= 3
    sc = 1.0 / tempo
    # 保留完整余音时，缓冲区要额外留出余音长度，否则每个音都被尾部截掉
    tail_pad = _tail_max()
    if has_start:
        span = max(float(n[2]) + float(n[1]) for n in notes)
        total = span * sc + ring + 2.0 + tail_pad
    else:
        total = sum(float(n[1]) for n in notes) * sc + 2.0 + tail_pad
    buf = np.zeros(int(total * SR) + SR * 4, dtype=np.float64)

    cursor = 0.0
    for i, n in enumerate(notes):
        midi, dur = int(n[0]), float(n[1])
        start_t = float(n[2]) if has_start else cursor
        seg_dur = max(0.9, dur * 1.7) * (1.0 / tempo) + ring * 0.35
        # 按音域分工优先（split），其次高音段换乐器（alt）
        use_src = src
        if split_layers:
            for layer_src, lo, hi in split_layers:
                if lo <= midi < hi:
                    use_src = layer_src
                    break
        elif alt_src is not None and midi >= alt_from and (alt_to is None or midi < alt_to):
            use_src = alt_src
        sig = _note_audio(use_src, midi, seg_dur, f"{i}", tmp_dir)

        i0 = int(start_t * sc * SR)
        i1 = min(i0 + sig.size, buf.size)
        buf[i0:i1] += sig[:i1 - i0]
        # 高音段叠加遮盖层：同音高再叠一层 shadow（编钟），用它盖住刺耳
        if shadow_src is not None and midi >= shadow_from:
            sh = _note_audio(shadow_src, midi, seg_dur * 1.4, f"{i}s", tmp_dir)
            j1 = min(i0 + sh.size, buf.size)
            if i0 < buf.size:
                buf[i0:j1] += sh[:j1 - i0] * float(shadow_gain)
        if not has_start:
            cursor += dur * sc + 0.03
        if on_progress:
            on_progress(int((i + 1) / len(notes) * 100))

    end_t = (max(float(n[2]) + float(n[1]) for n in notes) * sc) if has_start else cursor
    # 保留完整余音时，结尾要留出余响，否则刚叠起来的尾韵又被裁掉
    used = int((end_t + ring + 0.8 + _tail_max()) * SR)
    buf = buf[:min(used, buf.size)]
    ntail = int(SR * 1.2)
    if buf.size > ntail:
        buf[-ntail:] *= np.linspace(1.0, 0.0, ntail)
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf *= 0.85 / peak
    # 整曲增益：提到接近常规音乐响度；只在峰值超过阈值处做软膝限幅
    if OUTPUT_GAIN_DB:
        buf *= 10 ** (float(OUTPUT_GAIN_DB) / 20.0)
    buf = _soft_limit(buf)
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)

    name = _out_name(f"studio-{timbre}-{piece}", tempo)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path, len(pcm) / SR


# 非谐波窄带陷波：79 号最强峰在 5.77× 基频（比所有谐波都响），86 号在 3.85/4.58/6.87×。
# 这些不是整数倍，听感就是「金属铃」。用 bandreject 精确挖掉，保留整数倍谐波。
NOTCH = {
    "79": [5.77, 7.12, 7.67, 6.83],
    "86": [4.58, 3.85, 6.87],
}


# 升调抗混叠：曾试过给 rate>1.25 的音加低通，用户判定「方向不对，且把前半段拉回去了」。
# 默认关闭，保留能力备查；别再默认开启。
LOWPASS = {"on": False, "from_rate": 1.25, "ceiling": 16000.0, "floor_hz": 9000.0}


def _notch_filters(key, target_f0, sr=SR):
    out = []
    for m in NOTCH.get(str(key), []):
        f = target_f0 * m
        if 80 < f < sr / 2 - 300:
            out.append(f"bandreject=f={f:.0f}:width_type=h:w={max(80.0, f * 0.035):.0f}")
    return out


TAIL = {
    # 2026-11-01 试听反馈：「好像都是拼接的，没有复合的感觉，只留了一个音最突出的一段，
    # 没有保留隐在其他音之后的那段余震」。改法：不再按音符时长截断采样，
    # 而是保留采样的**完整余音**，只在最末尾做一次长淡出，让相邻音的余响自然交叠。
    "on": True,
    "min_keep": 3.5,     # 固定模式下的余音长度（秒）；采样比这长就保留到末尾
    "tail_fade": 1.2,    # 末尾淡出长度（秒）
    # 动态余音：低音区能量"堵"，余响互相干扰最重（佩兰后半段 6 秒余音时曾有 22 个音同时响），
    # 所以低音留短、高音留长。开启后按 midi 取 low/mid/high 三档。
    "dynamic": True,
    "low_midi": 60, "low_keep": 2.2,    # < C4：短
    "high_midi": 72, "high_keep": 5.0,  # >= C5：长
    "mid_keep": 3.2,                    # C4–B4：中
}


def _tail_keep(midi):
    """按音高决定这个音保留多长的余音（秒）。"""
    if not TAIL.get("dynamic"):
        return float(TAIL["min_keep"])
    if midi < int(TAIL["low_midi"]):
        return float(TAIL["low_keep"])
    if midi >= int(TAIL["high_midi"]):
        return float(TAIL["high_keep"])
    return float(TAIL["mid_keep"])


def _tail_max():
    """所有可能余音长度里的最大值，用于分配缓冲区。"""
    if not TAIL.get("on"):
        return 0.0
    if not TAIL.get("dynamic"):
        return float(TAIL["min_keep"])
    return max(float(TAIL["low_keep"]), float(TAIL["mid_keep"]), float(TAIL["high_keep"]))


def _render_one(src, sample, midi, dur, tmp_dir, tag):
    """用指定采样渲染一个音（单层）。

    dur 只作为「最短保留时长」的下限；TAIL.on 时不再按 dur 硬截断，
    而是把采样剩下的部分完整保留，让余音能叠进后续的音里。
    """
    target = 432.0 * 2 ** ((midi - 69) / 12.0)
    rate = target / sample["hz"]
    f = _pick_sample_file(src, sample["key"])
    if not f:
        raise FileNotFoundError(sample["key"])
    out = os.path.join(tmp_dir, f"{tag}.wav")
    # per-key 起音裁剪：某些采样的前几百毫秒是宽带撞击瞬态（听感=金属铃），跳过后音色干净得多
    seek = (src.get("seek_map") or {}).get(str(sample["key"]), src.get("seek"))
    parts = [f"aresample={SR}", f"asetrate={int(round(SR * rate))}", f"aresample={SR}"]
    # 升调超过阈值时切掉混叠带
    if LOWPASS.get("on") and rate > LOWPASS["from_rate"]:
        cutoff = max(LOWPASS["floor_hz"], min(14000.0, LOWPASS["ceiling"] / rate))
        parts.append(f"lowpass=f={cutoff:.0f}:poles=2")
    parts += _tone_filters(midi, src.get("id"))
    parts += _notch_filters(sample["key"], target)
    parts += ["afade=t=in:st=0:d=0.008"]
    if TAIL.get("on"):
        # 保留余音；长度按音高动态取（低音短、高音长）
        keep = max(_tail_keep(midi), dur)
        parts += [f"atrim=0:{keep:.3f}",
                  f"afade=t=out:st={max(0.0, keep - float(TAIL['tail_fade'])):.3f}"
                  f":d={float(TAIL['tail_fade']):.3f}"]
    else:
        fade = min(0.6, dur * 0.5)
        parts += [f"atrim=0:{dur:.3f}",
                  f"afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}"]
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    if seek:
        cmd += ["-ss", str(seek)]
    cmd += ["-i", f, "-af", ",".join(parts), "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", out]
    subprocess.run(cmd, check=True, capture_output=True)
    _, sig = read_wav(out)
    os.remove(out)
    # 按音源平衡音量：各音源的录音电平差极大（古琴 -51 dBFS、长笛 -14.9，差 36 dB），
    # 不补偿的话，古琴为主的作品听感就是「音量很小」。
    g = float(GAIN_BY.get(src.get("id"), 1.0)) if GAIN_BY else 1.0
    if g != 1.0:
        sig = sig * g
    return sig


# 八度叠加：高音区把「主层采样」与「更低八度的干净采样升调」叠起来，
# 主层保音色，辅层补被升调削掉的谐波厚度。gain=0 关闭。
# ⚠️ 这也是**为古筝调的黑科技**，套到别的音源上会污染音色，所以只有 DUAL_BY 里的音源才做。
DUAL = {
    "above_midi": 74,      # >= 这个 MIDI 才叠加
    "gain": 0.5,           # 辅层音量（相对主层）
    "aux_lower": 5,        # 辅层采样至少比主层低这么多半音（逼它取更低八度）
}

DUAL_BY = {"guzheng"}

# 低音补亮：低音区古筝弦基频弱、泛音少，听着发闷。
# ⚠️ 默认关闭（gain=0）：曾默认 0.35，用户反馈「有杂音」。要试再临时打开。
DUAL_LOW = {
    "below_midi": 55,      # <= 这个 MIDI 才叠加
    "gain": 0.0,           # 高八度层音量（默认关）
    "aux_higher": 10,      # 辅层采样至少比主层高这么多半音
}


# ── 驻波区：时域/相位处理（2026-11-01 用户提出「谐波区之外试试驻波区」）──
# 采样回放每触发一次都是同一波形，所以「死」；真实乐器有微小音高漂移与腔体驻波。
# BEAT：叠一个极微失谐的副本 → 拍频（驻波的时域表现），0.5–3Hz 的缓慢起伏 = 「活」。
# COMB：短延迟混合 → 梳状滤波，模拟琴箱/管体的驻波腔，比 EQ 更接近物理。
BEAT = {
    "on": False,        # 用户实测「效果好一些」，默认开之前先做整曲 A/B
    "cents": 2.0,       # 失谐量（音分），2 约等于真人演奏的微观漂移
    "layers": 1,        # 叠几层
    "level": 0.5,       # 副本音量（相对主层）
}
COMB = {
    "on": False,
    "delay_ms": 6.0,    # 延迟长度决定梳齿间距（1/delay）；6ms ≈ 167Hz 间隔
    "level": 0.25,      # 反馈量（0.2–0.4 像木箱，>0.5 会发金属味）
}

# 驻波方案预设（2026-11-01 实测数据，可按曲目/音源切换）
#   clean：原样   差异 0%
#   alive：拍频   包络起伏 16.8→21.7 dB（时间维"活"），频谱几乎不变，与原版差异 16.7%
#   body ：梳状   低频 70.8→73.5%、高频 8.9→7.7%（音色变厚变暖），与原版差异仅 3.2%
#   rich ：两者   起伏 22.2 dB + 低频 73.7%，差异 18.4%
STYLE_PRESETS = {
    "clean": {"beat": False, "comb": False},
    "alive": {"beat": True, "comb": False},
    "body": {"beat": False, "comb": True},
    "rich": {"beat": True, "comb": True},
}


def set_style(name):
    """切换驻波方案。返回切换后的状态字典。"""
    cfg = STYLE_PRESETS.get(name)
    if cfg is None:
        raise KeyError(f"未知方案 {name}，可选：{', '.join(STYLE_PRESETS)}")
    BEAT["on"] = bool(cfg["beat"])
    COMB["on"] = bool(cfg["comb"])
    return {"style": name, "beat": BEAT["on"], "comb": COMB["on"]}


def _detune_copy(sig, cents):
    """按音分微变调（线性插值）——用于制造拍频。"""
    ratio = 2.0 ** (cents / 1200.0)
    n = max(2, int(sig.size / ratio))
    idx = np.arange(n) * ratio
    return np.interp(idx, np.arange(sig.size), sig)


def _beating(sig):
    """叠微失谐副本，制造拍频。返回与输入等长的片段。"""
    if not BEAT.get("on"):
        return sig
    out = sig.copy()
    for i in range(int(BEAT.get("layers", 1))):
        off = float(BEAT["cents"]) * (i + 1) * (1 if i % 2 == 0 else -1)
        c = _detune_copy(sig, off)
        n = min(out.size, c.size)
        out[:n] += c[:n] * (float(BEAT["level"]) / (i + 1))
    return out


def _comb(sig):
    """短延迟反馈 —— 梳状滤波，模拟腔体驻波。"""
    if not COMB.get("on"):
        return sig
    d = max(1, int(SR * float(COMB["delay_ms"]) / 1000.0))
    out = sig.copy()
    g = float(COMB["level"])
    for i in range(d, out.size, d):
        j = min(i + d, out.size)
        out[i:j] += out[i - d:i - d + (j - i)] * g
    return out


def _note_audio(src, midi, dur, idx, tmp_dir):
    """渲染单个音，返回 numpy 片段。高音区强制用指定采样降调，并做八度叠加补厚度。"""
    s = None
    # per-midi 强制指定采样（比 avoid 更精确，不影响同采样覆盖的其他音）
    forced = (src.get("map") or {}).get(str(midi))
    hk = src.get("high_key")
    if forced:
        for x in src["samples"]:
            if str(x["key"]) == str(forced):
                s = {"key": x["key"], "hz": x["hz"], "smidi": midi_of(x["hz"]),
                     "diff": midi - midi_of(x["hz"])}
                break
    if s is None and hk and midi >= src.get("high_from", 999):
        for x in src["samples"]:
            if str(x["key"]) == str(hk):
                smidi = midi_of(x["hz"])
                s = {"key": x["key"], "hz": x["hz"], "smidi": smidi, "diff": midi - smidi}
                break
    if s is None:
        s = _nearest(src["samples"], midi, src.get("avoid", ()))
    sig = _render_one(src, s, midi, dur, tmp_dir, f"n{idx}")
    if DUAL.get("gain") and midi >= DUAL["above_midi"] and src.get("id") in DUAL_BY:
        lower = [x for x in src["samples"] if midi_of(x["hz"]) <= s["smidi"] - float(DUAL["aux_lower"])]
        if lower:
            s2 = _nearest(lower, midi)
            sig2 = _render_one(src, s2, midi, dur, tmp_dir, f"n{idx}a")
            n = min(sig.size, sig2.size)
            sig = sig[:n] + sig2[:n] * float(DUAL["gain"])
    if DUAL_LOW.get("gain") and midi <= DUAL_LOW["below_midi"]:
        higher = [x for x in src["samples"] if midi_of(x["hz"]) >= s["smidi"] + float(DUAL_LOW["aux_higher"])]
        if higher:
            s3 = _nearest(higher, midi)
            sig3 = _render_one(src, s3, midi, dur, tmp_dir, f"n{idx}h")
            n = min(sig.size, sig3.size)
            sig = sig[:n] + sig3[:n] * float(DUAL_LOW["gain"])
    # 驻波区处理：先拍频（相位层）再梳状（腔体层），顺序影响结果，先叠相位更自然
    sig = _beating(sig)
    sig = _comb(sig)
    return sig


def render_duet(piece, lead="guzheng", pad="flute", pad_gain=0.5, pad_octave=12,
                pad_every=1, pad_dur=5.0, pad_min_midi=55, pad_fade=0.25,
                tempo=1.0, ring=2.0, on_progress=None):
    """双音源编配：主奏弹旋律，衬底按拍铺长音。

    古琴曲是单声部，直接弹容易显得空。主奏照常走每个音；
    衬底每 pad_every 个音触发一次、音高偏移 pad_octave、持续 pad_dur，
    密度减半，避免和主奏叠成一团。

    ⚠️ 2026-11-01 两次试听结论：
    第 1 轮：能否听出「另一件乐器」取决于音色可分离度，不是变调保真度——箫变调 1.0 听着像单音，长笛被拉到 0.37× 反而最突出。
    第 2 轮：但**长笛同度**又太贴着主旋律（等于同一条旋律叠一遍），低音区变调失真最重、抢戏，整体不悠扬。
    所以做衬底的正确形状是：**高一个八度（飘在上面）+ 只在音区中高段出现 + 慢起音**。
    """
    _ensure_dirs()
    notes = piece_notes(piece)
    if not notes:
        raise KeyError(f"曲目为空或未知：{piece}")
    lead_src = _resolve_source(lead)
    pad_src = _resolve_source(pad) if pad else None
    tmp = os.path.join(OUT_DIR, "_duet")
    os.makedirs(tmp, exist_ok=True)
    sc = 1.0 / tempo
    span = max(float(n[2]) + float(n[1]) for n in notes)
    total = span * sc + max(1.2, ring) + 2.0
    lead_buf = np.zeros(int(total * SR) + SR, dtype=np.float64)
    pad_buf = np.zeros_like(lead_buf)
    pad_fade_n = max(1, int(pad_fade * SR)) if pad_fade else 0

    for i, n in enumerate(notes):
        midi, dur, start = int(n[0]), float(n[1]), float(n[2])
        seg = max(0.9, dur * 1.7) * sc + ring * 0.35
        sg = _note_audio(lead_src, midi, seg, f"l{i}", tmp)
        i0 = int(start * sc * SR)
        i1 = min(i0 + sg.size, lead_buf.size)
        if i0 < lead_buf.size:
            lead_buf[i0:i1] += sg[:i1 - i0]
        if pad_src and midi >= pad_min_midi and i % max(1, int(pad_every)) == 0:
            psig = _note_audio(pad_src, midi + int(pad_octave), pad_dur * sc, f"p{i}", tmp)
            if pad_fade_n and psig.size > pad_fade_n:      # 慢起音，做出「吹进来」的感觉
                psig = psig.copy()
                psig[:pad_fade_n] *= np.linspace(0.0, 1.0, pad_fade_n)
            j0 = int(start * sc * SR)
            j1 = min(j0 + psig.size, pad_buf.size)
            if j0 < pad_buf.size:
                pad_buf[j0:j1] += psig[:j1 - j0]
        if on_progress and i % 4 == 0:
            on_progress(min(95, int(i / max(1, len(notes)) * 95)))

    # 关键：按「主奏峰值」归一化，pad 再按 pad_gain 比例叠加。
    # 之前是混完一起归一化，pad 越大整体被压得越狠 → 听感是主奏变弱，而不是多出一层。
    lead_peak = float(np.max(np.abs(lead_buf))) if lead_buf.size else 0.0
    scale = (0.85 / lead_peak) if lead_peak > 0 else 1.0
    buf = lead_buf * scale + pad_buf * scale * float(pad_gain)
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0.98:                      # 只在真的会削波时整体压一下
        buf *= 0.98 / peak
    ntail = int(SR * 1.5)
    if buf.size > ntail:
        buf[-ntail:] *= np.linspace(1.0, 0.0, ntail)
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)
    safe_piece = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", str(piece))
    name = _out_name(f"studio-duet-{safe_piece}", tempo)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    return path, buf.size / SR


def render_quartet(tempo=1.0, ring=2.0, on_progress=None):
    """多音源编排：编钟前奏 → 二胡主题 → 长笛变奏 → 二胡+编钟 → 编钟尾声。"""
    _ensure_dirs()
    tmp = os.path.join(OUT_DIR, "_qt")
    os.makedirs(tmp, exist_ok=True)

    erhu = _resolve_source("erhu")
    bell = _resolve_source("bell")
    flute = _resolve_source("flute")
    sc = 1.0 / tempo

    tracks = []
    stages = []

    def report(p):
        if on_progress:
            on_progress(min(99, p))

    # 前奏：编钟三连击
    report(5)
    cur = 0.0
    for i, d in enumerate([2.6, 2.2, 1.8]):
        tracks.append((cur, _note_audio(bell, 72, d, f"p{i}", tmp) * 0.9))
        cur += 1.9 * sc
    stages.append(("前奏", cur))
    cur += 0.8

    # 主题 A：二胡
    report(20)
    a0 = cur
    for i, (m, d) in enumerate(MOLIHUA):
        tracks.append((cur, _note_audio(erhu, m, max(0.9, d * 1.9), f"a{i}", tmp)))
        cur += (d + 0.06) * sc
    stages.append(("主题A 二胡", a0))
    cur += 1.2

    # 主题 A'：长笛
    report(45)
    ap0 = cur
    for i, (m, d) in enumerate(MOLIHUA):
        tracks.append((cur, _note_audio(flute, m, max(1.0, d * 2.0), f"f{i}", tmp) * 0.92))
        cur += (d * 1.12 + 0.08) * sc
    stages.append(("主题A' 长笛", ap0))
    cur += 1.0

    # 主题 B：二胡 + 编钟点缀
    report(70)
    b0 = cur
    for i, (m, d) in enumerate(MOLIHUA):
        tracks.append((cur, _note_audio(erhu, m, max(0.9, d * 1.9), f"b{i}", tmp)))
        if i % 4 == 0:
            tracks.append((cur, _note_audio(bell, 72 if i % 8 == 0 else 79, 2.2, f"c{i}", tmp) * 0.42))
        cur += (d + 0.06) * sc
    stages.append(("主题B 合奏", b0))
    cur += 1.0

    # 尾声：编钟长衰减 + 二胡
    report(90)
    tracks.append((cur, _note_audio(bell, 72, 6.0, "e0", tmp) * 0.85))
    tracks.append((cur + 0.6, _note_audio(erhu, 79, 2.3, "e1", tmp) * 0.5))
    stages.append(("尾声", cur))
    cur += 5.6 * sc

    total = cur + 0.4
    buf = np.zeros(int(total * SR) + SR, dtype=np.float64)
    for start, sig in tracks:
        i0 = int(start * SR)
        i1 = min(i0 + sig.size, buf.size)
        if i0 < buf.size:
            buf[i0:i1] += sig[:i1 - i0]

    ntail = int(SR * 1.5)
    if buf.size > ntail:
        buf[-ntail:] *= np.linspace(1.0, 0.0, ntail)
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf *= 0.85 / peak
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)

    name = _out_name("studio-quartet", tempo)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    report(100)
    return path, len(pcm) / SR, [{"name": n, "at": round(t, 2)} for n, t in stages]


def _layer_note_count(layer):
    k = layer.get("kind", "piece")
    if k == "note":
        return int(layer.get("count", 1))
    if k == "notes":
        return len(layer.get("notes", []))
    return len(piece_notes(layer.get("piece")) or [])


def _layer_seconds(layer, sc):
    """与 _render_layer 口径一致地估算一个 layer 的时长（秒）。"""
    kind = layer.get("kind", "piece")
    if kind == "note":
        return max(1, int(layer.get("count", 1))) * float(layer.get("gap", 1.9)) * sc
    if kind == "notes":
        raw = layer.get("notes", [])
        if not raw:
            return 0.0
        if len(raw[0]) >= 3:
            return max(float(n[2]) + float(n[1]) for n in raw) * sc
        return sum(float(n[1]) + 0.06 for n in raw) * sc
    notes = piece_notes(layer.get("piece", "molihua")) or []
    if not notes:
        return 0.0
    if len(notes[0]) >= 3:
        # 乐谱导入/古琴曲库是 [midi, dur, start]，时长看绝对跨度
        return max(float(n[2]) + float(n[1]) for n in notes) * sc
    return sum(float(n[1]) + 0.06 for n in notes) * sc


def estimate_sections(sections, tempo=1.0, ring=2.0):
    """给界面用的时长估算：每段秒数 + 含 pad 与尾部余音的总时长。

    尾部对齐 render_sections 的算法：max(1.2, ring) + 0.4 缓冲，再加 1 秒软尾。
    """
    sc = 1.0 / tempo
    parts = []
    total = 0.0
    for sec in sections or []:
        if sec.get("kind") == "stack":
            dur = max((_layer_seconds(l, sc) for l in sec.get("layers", [])), default=0.0)
        else:
            dur = _layer_seconds(sec, sc)
        parts.append(round(dur, 2))
        total += dur + float(sec.get("pad", 0.8)) * sc
    total += max(1.2, float(ring)) + 1.4
    return {"sections": parts, "total": round(total, 2)}


def _render_layer(tracks, layer, start, tmp, tag, sc, on_note=None):
    """从 start 秒起渲染一个 layer，把 (时刻, 音频) 追加到 tracks，返回结束时刻。"""
    src = _resolve_source(layer.get("timbre", "erhu"))
    kind = layer.get("kind", "piece")
    gain = float(layer.get("gain", 1.0))
    cur = start

    if kind == "note":
        count = max(1, int(layer.get("count", 1)))
        gap = float(layer.get("gap", 1.9))
        dur = float(layer.get("dur", 2.5))
        midi = int(layer.get("midi", 72))
        for k in range(count):
            sig = _note_audio(src, midi, dur, f"{tag}_{k}", tmp) * gain
            tracks.append((cur, sig))
            cur += gap * sc
            if on_note:
                on_note()
        return cur

    if kind == "notes":
        raw = layer.get("notes", [])
        # 三元组 [midi, dur, start] 用谱面绝对时间定位（乐谱导入走这条，休止不再被压平）；
        # 二元组 [midi, dur] 保持旧的顺序累加，兼容手工编排与历史数据。
        if raw and len(raw[0]) >= 3:
            end = start
            for k, n in enumerate(raw):
                m, d, st = int(n[0]), float(n[1]), float(n[2])
                sig = _note_audio(src, m, max(0.9, d * 1.9), f"{tag}_{k}", tmp) * gain
                tracks.append((start + st * sc, sig))
                end = max(end, start + (st + d) * sc)
                if on_note:
                    on_note()
            return end
        notes = [(int(n[0]), float(n[1])) for n in raw]
    else:
        notes = piece_notes(layer.get("piece", "molihua"))
    if not notes:
        raise KeyError(f"曲目为空或未知：{layer.get('piece') or 'notes'}")

    for k, (m, d) in enumerate(notes):
        sig = _note_audio(src, m, max(0.9, d * 1.9), f"{tag}_{k}", tmp) * gain
        tracks.append((cur, sig))
        cur += (d + 0.06) * sc
        if on_note:
            on_note()
    return cur


def render_sections(sections, tempo=1.0, ring=2.0, on_progress=None):
    """按数据化编排表渲染（支持多轨叠加）。

    sections 每项：
      kind=note   {timbre, midi, count, gap, dur, gain}
      kind=piece  {timbre, piece, gain}
      kind=notes  {timbre, notes:[[midi,dur],...], gain}
      kind=stack  {layers:[上述任一], gain}   ← 多轨：所有 layer 从同一时刻开始
    所有类型都可带 pad（段后留白秒数，默认 0.8）。
    """
    _ensure_dirs()
    if not sections:
        raise ValueError("编排为空")
    tmp = os.path.join(OUT_DIR, "_sec")
    os.makedirs(tmp, exist_ok=True)
    sc = 1.0 / tempo

    def count_sec(s):
        if s.get("kind") == "stack":
            return sum(_layer_note_count(l) for l in s.get("layers", []))
        return _layer_note_count(s)

    total_notes = sum(count_sec(s) for s in sections) or 1
    done = [0]

    def tick():
        done[0] += 1
        if on_progress:
            on_progress(min(95, int(done[0] / total_notes * 95)))

    tracks = []
    cur = 0.0

    for idx, sec in enumerate(sections):
        if sec.get("kind") == "stack":
            start = cur
            end = start
            for j, layer in enumerate(sec.get("layers", [])):
                layer_end = _render_layer(tracks, layer, start, tmp, f"st{idx}_{j}", sc, tick)
                end = max(end, layer_end)
            cur = end + float(sec.get("pad", 0.8)) * sc
        else:
            cur = _render_layer(tracks, sec, cur, tmp, f"s{idx}", sc, tick)
            cur += float(sec.get("pad", 0.8)) * sc

    total = cur + max(1.2, ring) + 0.4
    buf = np.zeros(int(total * SR) + SR, dtype=np.float64)
    for start, sig in tracks:
        i0 = int(start * SR)
        i1 = min(i0 + sig.size, buf.size)
        if i0 < buf.size:
            buf[i0:i1] += sig[:i1 - i0]

    ntail = int(SR * 1.5)
    if buf.size > ntail:
        buf[-ntail:] *= np.linspace(1.0, 0.0, ntail)
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf *= 0.85 / peak
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)

    name = _out_name("studio-custom", tempo)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    for f in os.listdir(tmp):
        os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    if on_progress:
        on_progress(100)
    return path, len(pcm) / SR


def make_video(wav_path, out_name=None, title="432 Hz 工作室", subtitle="432 Hz 基准"):
    """调用频谱视频渲染器，把 wav 变成 mp4。"""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import render_spectrum_video as RSV
    except Exception as e:
        return None, f"视频模块不可用: {e}"
    if not out_name:
        out_name = os.path.splitext(os.path.basename(wav_path))[0] + ".mp4"
    dst = os.path.join(OUT_DIR, out_name)
    try:
        ok, frames = RSV.render(wav_path, dst, title, subtitle)
    except Exception as e:
        return None, f"渲染失败: {str(e)[:150]}"
    if not ok:
        return None, "ffmpeg 编码失败"
    return os.path.basename(dst), None


if __name__ == "__main__":
    p, d = render_piece("erhu", "molihua", tempo=1.0, ring=2.0)
    print(p, f"{d:.2f}s")
