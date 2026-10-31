# -*- coding: utf-8 -*-
"""MusicXML 解析：把打谱软件（Sibelius / MuseScore / Finale）导出的谱面转成音符序列。

只处理单声部主旋律所需的最小集合：
  - <divisions>        每四分音符被分成几份
  - <tempo>            速度（可选，默认 120）
  - <note>             音高 / 时值 / 休止 / 连音线 / 和弦标记
  - <backup><forward>  多声部推进
输出：[{midi, dur(秒)}]，休止用 midi=None 表示。
"""
import xml.etree.ElementTree as ET

STEP_SEMITONE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _text(el, tag, default=None):
    n = el.find(tag)
    return n.text if (n is not None and n.text is not None) else default


def parse_musicxml(path, voice_pick=None):
    """解析 MusicXML，返回 (notes, meta)。

    notes: [{"midi": int|None, "dur": float, "rest": bool}]
    meta : {"divisions": int, "tempo": float, "title": str, "voices": int}
    voice_pick: 只取某个声部（1 起）；None 表示合并全部声部（可能重叠）。
    """
    tree = ET.parse(path)
    root = tree.getroot()
    title = ""
    for w in root.iter("work-title"):
        title = (w.text or "").strip()
        break
    if not title:
        for mv in root.iter("movement-title"):
            title = (mv.text or "").strip()
            break

    part = root.find("part")
    if part is None:
        raise ValueError("找不到 <part>")

    divisions = 1
    tempo = 120.0
    notes = []
    voices = set()

    for measure in part.findall("measure"):
        # 属性更新
        attrs = measure.find("attributes")
        if attrs is not None:
            div = _text(attrs, "divisions")
            if div:
                divisions = max(1, int(float(div)))
            for snd in attrs.iter("sound"):
                t = snd.get("tempo")
                if t:
                    try:
                        tempo = float(t)
                    except ValueError:
                        pass

        # 方向里的 tempo
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

            if tag == "backup":
                continue   # 时间轴以音符累加为准，backup 只影响声部对齐，简化忽略
            if tag == "forward":
                d = _text(child, "duration")
                if d and divisions:
                    notes.append({"midi": None, "dur": int(float(d)) / divisions,
                                  "rest": True, "forward": True})
                continue

            if tag != "note":
                continue

            v = _text(child, "voice")
            if v:
                voices.add(v)
                if voice_pick is not None and v != str(voice_pick):
                    continue

            if child.find("chord") is not None:
                continue   # 和弦只取第一个音（单旋律渲染）

            dur_raw = _text(child, "duration")
            if not dur_raw:
                continue
            beats = int(float(dur_raw)) / divisions        # 以四分音符为 1

            is_rest = child.find("rest") is not None
            if is_rest:
                notes.append({"midi": None, "dur": beats, "rest": True})
                continue

            pitch = child.find("pitch")
            if pitch is None:
                continue
            step = _text(pitch, "step", "C").upper()
            alter = float(_text(pitch, "alter", 0) or 0)
            octave = int(_text(pitch, "octave", 4))
            midi = (octave + 1) * 12 + STEP_SEMITONE.get(step, 0) + int(alter)

            # 连音线：<tie type="stop"> 表示这是延续，不重新起音
            tied = False
            tie = child.find("tie")
            if tie is not None and tie.get("type") == "stop":
                tied = True
                # 把时长并到上一个音
                for i in range(len(notes) - 1, -1, -1):
                    if notes[i].get("midi") is not None:
                        notes[i]["dur"] += beats
                        break
                continue

            notes.append({"midi": midi, "dur": beats, "rest": False})

    sec_per_beat = 60.0 / tempo
    for n in notes:
        n["dur"] = round(n["dur"] * sec_per_beat, 4)

    meta = {
        "title": title,
        "divisions": divisions,
        "tempo": tempo,
        "voices": len(voices),
        "count": len([n for n in notes if not n["rest"]]),
    }
    return notes, meta
