# -*- coding: utf-8 -*-
"""432Hz 工作室 · 渲染引擎

参数化的采样渲染核心，供 HTTP 服务调用。
支持：内置音源（二胡/编钟/长笛/钢琴）+ 用户上传采样；曲目与速度可调。
"""
import datetime
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
            "label": builtin["label"],
            "dir": builtin["dir"],
            "pattern": builtin["pattern"],
            "seek": builtin["seek"],
            "samples": [{"key": k, "hz": v} for k, v in builtin["hz"].items()],
        }
    users = user_sources()
    if timbre in users:
        u = users[timbre]
        return {
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


def _nearest(samples, midi):
    best = None
    for s in samples:
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


def render_piece(timbre, piece, tempo=1.0, ring=2.0, on_progress=None):
    _ensure_dirs()
    src = _resolve_source(timbre)
    notes = piece_notes(piece)
    if not notes:
        raise KeyError(f"未知曲目 {piece}")

    tmp_dir = os.path.join(OUT_DIR, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # 二元组 [midi, dur] 顺序累加；三元组 [midi, dur, start] 按谱面绝对时间定位（古琴曲库走这条）
    has_start = bool(notes) and len(notes[0]) >= 3
    sc = 1.0 / tempo
    if has_start:
        span = max(float(n[2]) + float(n[1]) for n in notes)
        total = span * sc + ring + 2.0
    else:
        total = sum(float(n[1]) for n in notes) * sc + 2.0
    buf = np.zeros(int(total * SR) + SR * 4, dtype=np.float64)

    cursor = 0.0
    for i, n in enumerate(notes):
        midi, dur = int(n[0]), float(n[1])
        start_t = float(n[2]) if has_start else cursor
        s = _nearest(src["samples"], midi)
        target = 432.0 * 2 ** ((midi - 69) / 12.0)
        rate = target / s["hz"]
        seg_dur = max(0.9, dur * 1.7) * (1.0 / tempo) + ring * 0.35

        f = _find_file(src["dir"], src["pattern"], s["key"])
        if not f:
            raise FileNotFoundError(s["key"])
        out = os.path.join(tmp_dir, f"n{i}.wav")
        fade = min(0.6, seg_dur * 0.5)
        af = (
            f"aresample={SR},asetrate={int(round(SR * rate))},aresample={SR},"
            f"atrim=0:{seg_dur:.3f},"
            f"afade=t=out:st={max(0.0, seg_dur - fade):.3f}:d={fade:.3f}"
        )
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
        if src["seek"]:
            cmd += ["-ss", str(src["seek"])]
        cmd += ["-i", f, "-af", af, "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", out]
        subprocess.run(cmd, check=True, capture_output=True)
        _, sig = read_wav(out)
        os.remove(out)

        i0 = int(start_t * sc * SR)
        i1 = min(i0 + sig.size, buf.size)
        buf[i0:i1] += sig[:i1 - i0]
        if not has_start:
            cursor += dur * sc + 0.03
        if on_progress:
            on_progress(int((i + 1) / len(notes) * 100))

    end_t = (max(float(n[2]) + float(n[1]) for n in notes) * sc) if has_start else cursor
    used = int((end_t + ring + 0.8) * SR)
    buf = buf[:min(used, buf.size)]
    ntail = int(SR * 1.2)
    if buf.size > ntail:
        buf[-ntail:] *= np.linspace(1.0, 0.0, ntail)
    peak = float(np.max(np.abs(buf))) if buf.size else 0.0
    if peak > 0:
        buf *= 0.85 / peak
    pcm = (np.clip(buf, -1, 1) * 32767).astype(np.int16)

    name = _out_name(f"studio-{timbre}-{piece}", tempo)
    path = os.path.join(OUT_DIR, name)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path, len(pcm) / SR


def _note_audio(src, midi, dur, idx, tmp_dir):
    """渲染单个音，返回 numpy 片段。"""
    s = _nearest(src["samples"], midi)
    target = 432.0 * 2 ** ((midi - 69) / 12.0)
    rate = target / s["hz"]
    f = _find_file(src["dir"], src["pattern"], s["key"])
    if not f:
        raise FileNotFoundError(s["key"])
    out = os.path.join(tmp_dir, f"n{idx}.wav")
    fade = min(0.6, dur * 0.5)
    af = (
        f"aresample={SR},asetrate={int(round(SR * rate))},aresample={SR},"
        f"atrim=0:{dur:.3f},"
        f"afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}"
    )
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    if src["seek"]:
        cmd += ["-ss", str(src["seek"])]
    cmd += ["-i", f, "-af", af, "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", out]
    subprocess.run(cmd, check=True, capture_output=True)
    _, sig = read_wav(out)
    os.remove(out)
    return sig


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
