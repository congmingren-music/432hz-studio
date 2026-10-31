# -*- coding: utf-8 -*-
"""MusicXML 解析：把打谱软件（Sibelius / MuseScore / Finale）导出的谱面转成音符序列。

支持多 part（每 part 一条轨）与 part 内的多声部时间轴：
  - <divisions>        每四分音符被分成几份
  - <backup>           游标回退（同一声部写另一层）
  - <forward>          游标前进（跳过空白）
  - <tempo>            速度（可选，默认 120）
  - <note>             音高 / 时值 / 休止 / 连音线 / 和弦标记

输出统一为「绝对时间」：每个音带 start（秒）与 dur（秒）。
"""
import xml.etree.ElementTree as ET

STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _text(el, tag, default=None):
    n = el.find(tag)
    return n.text if (n is not None and n.text is not None) else default


def _title(root):
    for w in root.iter("work-title"):
        t = (w.text or "").strip()
        if t:
            return t
    for mv in root.iter("movement-title"):
        t = (mv.text or "").strip()
        if t:
            return t
    return ""


def _part_names(root):
    names = {}
    for sp in root.iter("score-part"):
        pid = sp.get("id")
        pn = sp.find("part-name")
        if pid and pn is not None and pn.text:
            names[pid] = pn.text.strip()
    return names


def parse_musicxml_tracks(path):
    """解析 MusicXML，返回 (tracks, meta)。

    tracks: [{"part": id, "name": 名称, "notes": [{"midi","start","dur"}]}]
    meta:   {"title","divisions","tempo","parts"}
    """
    root = ET.parse(path).getroot()
    parts = root.findall("part")
    if not parts:
        raise ValueError("找不到 <part>")

    names = _part_names(root)
    divisions = 1
    tempo = 120.0
    tracks = []

    for pi, part in enumerate(parts):
        pid = part.get("id") or f"P{pi + 1}"
        cursor = 0            # 以 divisions 为单位的绝对位置
        notes = []            # [{"midi","start_t","dur_t"}]

        for measure in part.findall("measure"):
            attrs = measure.find("attributes")
            if attrs is not None:
                div = _text(attrs, "divisions")
                if div:
                    try:
                        divisions = max(1, int(float(div)))
                    except ValueError:
                        pass
                for snd in attrs.iter("sound"):
                    t = snd.get("tempo")
                    if t:
                        try:
                            tempo = float(t)
                        except ValueError:
                            pass

            for direction in measure.findall("direction"):
                for snd in direction.iter("sound"):
                    t = snd.get("tempo")
                    if t:
                        try:
                            tempo = float(t)
                        except ValueError:
                            pass

            for child in measure:
                tag = child.tag

                # 游标回退 / 前进
                if tag in ("backup", "forward"):
                    d = _text(child, "duration")
                    if d:
                        try:
                            delta = int(float(d))
                        except ValueError:
                            delta = 0
                        cursor = max(0, cursor - delta) if tag == "backup" else cursor + delta
                    continue

                if tag != "note":
                    continue

                dur_raw = _text(child, "duration")
                if not dur_raw:
                    continue
                try:
                    dur = int(float(dur_raw))
                except ValueError:
                    continue

                # 和弦：不推进游标，且只留首音（单轨渲染不做和声）
                if child.find("chord") is not None:
                    continue

                # 休止：推进游标
                if child.find("rest") is not None:
                    cursor += dur
                    continue

                pitch = child.find("pitch")
                if pitch is None:
                    cursor += dur
                    continue

                step = _text(pitch, "step", "C").upper()
                alter = float(_text(pitch, "alter", 0) or 0)
                octave = int(_text(pitch, "octave", 4))
                midi = (octave + 1) * 12 + STEP_SEMITONE.get(step, 0) + int(alter)

                # 连音线 stop：把时长并入前一个音，不新起
                tie = child.find("tie")
                if tie is not None and tie.get("type") == "stop" and notes:
                    notes[-1]["dur_t"] += dur
                    cursor += dur
                    continue

                notes.append({"midi": midi, "start_t": cursor, "dur_t": dur})
                cursor += dur

        tracks.append({"part": pid, "name": names.get(pid, pid), "notes": notes})

    sec_per_tick = (60.0 / tempo) / divisions
    for t in tracks:
        for n in t["notes"]:
            n["start"] = round(n["start_t"] * sec_per_tick, 4)
            n["dur"] = round(n["dur_t"] * sec_per_tick, 4)
        t["notes"].sort(key=lambda n: n["start"])

    meta = {
        "title": _title(root),
        "divisions": divisions,
        "tempo": tempo,
        "parts": len(tracks),
    }
    return tracks, meta


def pick_main_track(tracks):
    """挑音符最多的那条轨（简单启发式，与 midi.py 保持一致）。"""
    if not tracks:
        return None
    return max(tracks, key=lambda t: len(t["notes"]))


def parse_musicxml(path, voice_pick=None):
    """兼容旧接口：返回 (notes, meta)。

    notes 是主轨的音符（[{"midi","dur","start"}]）。
    """
    tracks, meta = parse_musicxml_tracks(path)
    main = pick_main_track(tracks)
    notes = main["notes"] if main else []
    return notes, meta
