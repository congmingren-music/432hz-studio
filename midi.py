# -*- coding: utf-8 -*-
"""MIDI 解析：把标准 MIDI 文件转成音符序列（可多轨）。

处理范围（够用即可，不追求完整 MIDI 规范）：
  - MThd / MTrk chunk
  - VLQ 变长 delta-time
  - note on / note off 配对（velocity 0 的 note on 视同 note off）
  - tempo meta 事件（可变速，按时间轴分段换算）
  - 多轨：每轨独立成一条 track

不处理：SMPTE 时间格式、sysex、pitch bend、controller 细节。
"""
import struct


def read_vlq(data, pos):
    """读变长数量（VLQ），返回 (值, 新位置)。"""
    value = 0
    while True:
        if pos >= len(data):
            raise ValueError("VLQ 越界")
        b = data[pos]
        pos += 1
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            return value, pos


def parse_header(data):
    if data[0:4] != b"MThd":
        raise ValueError("不是 MIDI 文件（缺 MThd）")
    hlen = struct.unpack(">I", data[4:8])[0]
    fmt, ntrks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError("SMPTE 时间格式暂不支持")
    return fmt, ntrks, division, 8 + hlen


def parse_track(data):
    """解析一条 MTrk，返回 (events, tempos)。

    events: [{"tick":int, "midi":int, "dur_ticks":int, "ch":int}]
    tempos: [{"tick":int, "us_per_beat":int}]
    """
    pos = 0
    tick = 0
    running = None          # running status
    active = {}             # (ch, note) -> 起始 tick
    events = []
    tempos = []

    while pos < len(data):
        delta, pos = read_vlq(data, pos)
        tick += delta
        if pos >= len(data):
            break

        status = data[pos]

        # meta 事件
        if status == 0xFF:
            pos += 1
            if pos >= len(data):
                break
            mtype = data[pos]
            pos += 1
            length, pos = read_vlq(data, pos)
            payload = data[pos:pos + length]
            pos += length
            if mtype == 0x51 and length == 3:
                tempos.append({"tick": tick, "us_per_beat": int.from_bytes(payload, "big")})
            elif mtype == 0x2F:
                break
            running = None
            continue

        # sysex
        if status in (0xF0, 0xF7):
            pos += 1
            length, pos = read_vlq(data, pos)
            pos += length
            running = None
            continue

        # 通道事件
        if status & 0x80:
            pos += 1
            running = status
        elif running is not None:
            status = running
        else:
            raise ValueError("无效的事件流")

        etype = status & 0xF0
        ch = status & 0x0F

        if etype in (0x80, 0x90):          # note off / note on
            if pos + 1 >= len(data):
                break
            note = data[pos]
            vel = data[pos + 1]
            pos += 2
            key = (ch, note)
            if etype == 0x90 and vel > 0:
                active[key] = tick
            else:
                if key in active:
                    start = active.pop(key)
                    events.append({
                        "tick": start,
                        "midi": note,
                        "dur_ticks": tick - start,
                        "ch": ch,
                    })
        elif etype in (0xA0, 0xB0, 0xE0):   # 2 字节数据
            pos += 2
        elif etype in (0xC0, 0xD0):         # 1 字节数据
            pos += 1
        else:
            break

    # 收尾：没关闭的音按到结束
    for (ch, note), start in active.items():
        events.append({"tick": start, "midi": note, "dur_ticks": max(1, tick - start), "ch": ch})

    events.sort(key=lambda e: e["tick"])
    return events, tempos


def tick_to_seconds(target_tick, tempos, division):
    """把绝对 tick 换算成秒，遵守 tempo 变化。"""
    if not tempos:
        return target_tick / division * 0.5      # 默认 120 BPM

    segs = sorted(tempos, key=lambda t: t["tick"])
    if segs[0]["tick"] > 0:
        segs.insert(0, {"tick": 0, "us_per_beat": 500000})

    seconds = 0.0
    for i, seg in enumerate(segs):
        seg_start = seg["tick"]
        seg_end = segs[i + 1]["tick"] if i + 1 < len(segs) else float("inf")
        if target_tick <= seg_start:
            break
        span_end = min(target_tick, seg_end)
        beats = (span_end - seg_start) / division
        seconds += beats * (seg["us_per_beat"] / 1_000_000.0)
        if target_tick <= seg_end:
            break
    return seconds


def parse_midi(path):
    """解析 MIDI 文件。

    返回 (tracks, meta)：
      tracks: [{"notes": [{"midi","dur","start"}], "events": 原始数}]
      meta:   {"format","division","track_count","tempo_events"}
    """
    with open(path, "rb") as f:
        data = f.read()

    fmt, ntrks, division, pos = parse_header(data)

    raw_tracks = []
    while pos < len(data) and len(raw_tracks) < ntrks:
        if data[pos:pos + 4] != b"MTrk":
            break
        tlen = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        raw_tracks.append(data[pos + 8:pos + 8 + tlen])
        pos += 8 + tlen

    all_tempos = []
    parsed = []
    for tdata in raw_tracks:
        try:
            events, tempos = parse_track(tdata)
        except Exception:
            events, tempos = [], []
        parsed.append(events)
        all_tempos.extend(tempos)

    tracks = []
    for events in parsed:
        if not events:
            continue
        notes = []
        for e in events:
            start = tick_to_seconds(e["tick"], all_tempos, division)
            end = tick_to_seconds(e["tick"] + e["dur_ticks"], all_tempos, division)
            dur = max(0.05, end - start)
            notes.append({"midi": e["midi"], "dur": round(dur, 4), "start": round(start, 4)})
        notes.sort(key=lambda n: n["start"])
        tracks.append({"notes": notes, "raw": len(events)})

    meta = {
        "format": fmt,
        "division": division,
        "track_count": len(tracks),
        "tempo_events": len(all_tempos),
    }
    return tracks, meta


def pick_main_track(tracks):
    """挑音符最多的那条轨当主旋律（简单启发式）。"""
    if not tracks:
        return None
    return max(tracks, key=lambda t: len(t["notes"]))


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else None
    if not p:
        print("用法: python midi.py <文件.mid>")
        raise SystemExit(1)
    tr, meta = parse_midi(p)
    print("meta:", meta)
    main = pick_main_track(tr)
    if main:
        print(f"主轨音符数: {len(main['notes'])}")
        for n in main["notes"][:8]:
            print(f"  MIDI {n['midi']:>3}  {n['dur']:.2f}s  @{n['start']:.2f}s")
