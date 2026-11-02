# -*- coding: utf-8 -*-
"""432Hz 工作室 · 本地 HTTP 服务

接口：
  GET  /                     页面
  GET  /api/sources          可用音源（内置 + 用户上传）
  POST /api/render           提交渲染任务 {timbre, piece, tempo, ring}
  GET  /api/job/<id>         查询任务进度 / 结果
  POST /api/upload           上传用户采样包 {name, label, files:[{name, data(base64)}]}
  GET  /files/<name>         下载渲染结果
"""
import base64
import json
import os
import re
import shutil
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_api as R  # noqa: E402
import musicxml  # noqa: E402
import midi  # noqa: E402

PORT = int(os.environ.get("STUDIO_PORT", "8770"))
TOKEN = os.environ.get("ACCESS_TOKEN", "").strip()
HERE = os.path.dirname(os.path.abspath(__file__))
JOBS = {}
LOCK = threading.Lock()


def _out_wavs():
    """out/ 下的 wav，按修改时间新→旧。"""
    if not os.path.isdir(R.OUT_DIR):
        return []
    items = [
        (os.path.getmtime(os.path.join(R.OUT_DIR, n)), n)
        for n in os.listdir(R.OUT_DIR)
        if n.lower().endswith(".wav")
    ]
    items.sort(reverse=True)
    return items


def out_info():
    items = _out_wavs()
    total = sum(os.path.getsize(os.path.join(R.OUT_DIR, n)) for _t, n in items)
    return {
        "count": len(items),
        "mb": round(total / 1024 / 1024, 1),
        "newest": [n for _t, n in items[:5]],
    }


def run_job(job_id, timbre, piece, tempo, ring, want_video, sections=None):
    try:
        def prog(p):
            with LOCK:
                JOBS[job_id]["progress"] = p

        stages = None
        if sections:
            path, dur = R.render_sections(sections, tempo, ring, on_progress=prog)
        elif piece == "quartet":
            path, dur, stages = R.render_quartet(tempo, ring, on_progress=prog)
        else:
            path, dur = R.render_piece(timbre, piece, tempo, ring, on_progress=prog)

        result = {
            "status": "done",
            "progress": 100,
            "file": os.path.basename(path),
            "duration": round(dur, 2),
        }
        if stages:
            result["stages"] = stages

        if want_video:
            with LOCK:
                JOBS[job_id]["progress"] = 99
                JOBS[job_id]["stage"] = "编码视频"
            vid, err = R.make_video(path, title="432 Hz 工作室", subtitle="生成结果 · 432 Hz 基准")
            if vid:
                result["video"] = vid
            else:
                result["videoError"] = err

        with LOCK:
            JOBS[job_id].update(result)
    except Exception as e:
        with LOCK:
            JOBS[job_id].update({"status": "error", "error": str(e)[:300]})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _allowed(self):
        """设了 ACCESS_TOKEN 环境变量才启用校验（本地使用不受影响）。"""
        if not TOKEN:
            return True
        q = parse_qs(urlparse(self.path).query)
        if q.get("token", [None])[0] == TOKEN:
            return True
        return self.headers.get("X-Access-Token") == TOKEN

    def _deny(self):
        self._json({"error": "需要访问令牌（?token=... 或 X-Access-Token 头）"}, 401)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype="audio/wav"):
        if not os.path.exists(path):
            self._json({"error": "not found"}, 404)
            return
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._allowed():
            return self._deny()
        p = urlparse(self.path).path

        if p in ("/", "/index.html"):
            return self._file(os.path.join(HERE, "studio.html"), "text/html; charset=utf-8")

        if p == "/api/sources":
            builtin = [{"id": k, "label": v["label"]} for k, v in R.BUILTIN.items()]
            users = [{"id": k, "label": v.get("label", k), "count": len(v.get("samples", []))}
                     for k, v in R.user_sources().items()]
            return self._json({"builtin": builtin, "user": users})

        if p == "/api/pieces":
            return self._json({"pieces": R.all_pieces()})

        if p == "/api/out_info":
            return self._json(out_info())

        if p == "/api/style":
            return self._json({
                "presets": R.STYLE_PRESETS,
                "beat": dict(R.BEAT),
                "comb": dict(R.COMB),
                "tail": dict(R.TAIL),
                "tail_by": {k: dict(v) for k, v in R.TAIL_BY.items()},
                "gain": {"output_db": R.OUTPUT_GAIN_DB, "by": dict(R.GAIN_BY)},
            })

        if p == "/api/debug":
            # 调试面板：当前全部参数 + 指定曲目的诊断
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            pid = (q.get("piece") or [""])[0]
            info = {
                "params": {
                    "TAIL": dict(R.TAIL),
                    "TAIL_BY": {k: dict(v) for k, v in R.TAIL_BY.items()},
                    "GAIN_BY": dict(R.GAIN_BY),
                    "OUTPUT_GAIN_DB": R.OUTPUT_GAIN_DB,
                    "LIMIT_THRESHOLD": R.LIMIT_THRESHOLD,
                    "BEAT": dict(R.BEAT),
                    "COMB": dict(R.COMB),
                    "TONE_BY": sorted(R.TONE_BY),
                    "TONE": dict(R.TONE),
                    "DUAL": dict(R.DUAL),
                    "DUAL_BY": sorted(R.DUAL_BY),
                    "SPLIT_DEFAULT": R.SPLIT_DEFAULT,
                    "NOTCH": dict(R.NOTCH),
                },
                "sources": [],
            }
            for tid, cfg in R.BUILTIN.items():
                tl = R._tail_cfg(tid)
                info["sources"].append({
                    "id": tid, "label": cfg.get("label", tid),
                    "samples": len(cfg.get("hz") or {}),
                    "gain": R.GAIN_BY.get(tid, 1.0),
                    "tail": {k: tl.get(k) for k in ("low_keep", "mid_keep", "high_keep")},
                })
            if pid:
                try:
                    notes = R.piece_notes(pid)
                    ms = [int(n[0]) for n in notes]
                    span = max(float(n[2]) + float(n[1]) for n in notes)
                    # 按音域分工看每个音由谁演奏
                    per = {}
                    for m in ms:
                        who = R.SPLIT_DEFAULT[0][0]
                        for t, lo, hi in R.SPLIT_DEFAULT:
                            if lo <= m < hi:
                                who = t
                                break
                        per[who] = per.get(who, 0) + 1
                    info["piece"] = {
                        "id": pid, "notes": len(notes), "span": round(span, 1),
                        "low": min(ms), "high": max(ms),
                        "by_source": per,
                    }
                except Exception as e:
                    info["piece"] = {"error": f"{type(e).__name__}: {e}"}
            return self._json(info)

        if p.startswith("/api/job/"):
            jid = p.rsplit("/", 1)[-1]
            with LOCK:
                job = dict(JOBS.get(jid, {"status": "unknown"}))
            return self._json(job)

        if p.startswith("/files/"):
            name = unquote(p.rsplit("/", 1)[-1])
            if not re.fullmatch(r"[\w\-.]+\.wav", name):
                return self._json({"error": "bad name"}, 400)
            return self._file(os.path.join(R.OUT_DIR, name))

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._allowed():
            return self._deny()
        p = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            return self._json({"error": "bad json"}, 400)

        if p == "/api/style":
            # 切换驻波方案 / 调参。body: {style?} 或 {beat:{...}, comb:{...}}
            out = {}
            st = body.get("style")
            if st:
                try:
                    out["applied"] = R.set_style(st)
                except KeyError as e:
                    return self._json({"error": str(e)}, 400)
            for k, cfg in (("beat", R.BEAT), ("comb", R.COMB)):
                patch = body.get(k) or {}
                for key in ("cents", "layers", "level", "delay_ms"):
                    if key in patch:
                        try:
                            cfg[key] = float(patch[key])
                        except (TypeError, ValueError):
                            pass
                if "on" in patch:
                    cfg["on"] = bool(patch["on"])
            # 余音参数（低/中/高音区各自保留多久 + 淡出长度）
            tp = body.get("tail") or {}
            for key in ("min_keep", "low_keep", "mid_keep", "high_keep", "tail_fade"):
                if key in tp:
                    try:
                        R.TAIL[key] = max(0.2, min(12.0, float(tp[key])))
                    except (TypeError, ValueError):
                        pass
            for key in ("on", "dynamic"):
                if key in tp:
                    R.TAIL[key] = bool(tp[key])
            for key in ("low_midi", "high_midi"):
                if key in tp:
                    try:
                        R.TAIL[key] = int(tp[key])
                    except (TypeError, ValueError):
                        pass
            # 按音源覆盖余音：body.tail_by = {"bell": {"high_keep": 7.0}, ...}
            tb = body.get("tail_by") or {}
            if isinstance(tb, dict):
                for tid, patch in tb.items():
                    if not isinstance(patch, dict):
                        continue
                    slot = R.TAIL_BY.setdefault(str(tid), {})
                    for key in ("min_keep", "low_keep", "mid_keep", "high_keep", "tail_fade"):
                        if key in patch:
                            try:
                                slot[key] = max(0.2, min(12.0, float(patch[key])))
                            except (TypeError, ValueError):
                                pass
            out.update({"beat": dict(R.BEAT), "comb": dict(R.COMB),
                        "tail": dict(R.TAIL),
                        "tail_by": {k: dict(v) for k, v in R.TAIL_BY.items()},
                        "presets": R.STYLE_PRESETS})
            return self._json(out)

        if p == "/api/estimate":
            sections = body.get("sections") or []
            try:
                tempo = max(0.5, min(2.0, float(body.get("tempo", 1.0))))
            except (TypeError, ValueError):
                tempo = 1.0
            try:
                ring = max(0.5, min(6.0, float(body.get("ring", 2.0))))
            except (TypeError, ValueError):
                ring = 2.0
            return self._json(R.estimate_sections(sections, tempo, ring))

        if p == "/api/out_clean":
            try:
                keep = max(1, int(body.get("keep", 10)))
            except (TypeError, ValueError):
                keep = 10
            items = _out_wavs()
            removed = []
            for _t, n in items[keep:]:
                try:
                    os.remove(os.path.join(R.OUT_DIR, n))
                    removed.append(n)
                except OSError:
                    pass
            return self._json({"ok": True, "removed": len(removed), "kept": min(keep, len(items))})

        if p == "/api/render":
            timbre = str(body.get("timbre", "erhu"))
            piece = str(body.get("piece", "molihua"))
            tempo = float(body.get("tempo", 1.0))
            want_video = bool(body.get("video", False))
            sections = body.get("sections")
            ring = float(body.get("ring", 2.0))
            tempo = max(0.5, min(2.0, tempo))
            ring = max(0.5, min(6.0, ring))
            jid = uuid.uuid4().hex[:12]
            with LOCK:
                JOBS[jid] = {"status": "running", "progress": 0}
            threading.Thread(target=run_job, args=(jid, timbre, piece, tempo, ring, want_video, sections), daemon=True).start()
            return self._json({"job": jid})

        if p == "/api/upload":
            name = re.sub(r"[^\w\-]", "_", str(body.get("name", "user")))
            label = str(body.get("label", name))[:40]
            files = body.get("files") or []
            if not files:
                return self._json({"error": "没有文件"}, 400)
            d = os.path.join(R.USER_DIR, name)
            os.makedirs(d, exist_ok=True)
            samples = []
            errors = []
            for f in files:
                fn = re.sub(r"[^\w\-.]", "_", str(f.get("name", "s.wav")))
                if not fn.lower().endswith((".wav", ".flac", ".mp3", ".ogg", ".m4a")):
                    errors.append(f"{fn}: 不支持的格式")
                    continue
                raw = base64.b64decode(str(f.get("data", "")))
                dst = os.path.join(d, fn)
                with open(dst, "wb") as out:
                    out.write(raw)
                try:
                    hz, midi_no = R.analyze_upload(dst)
                    samples.append({"file": fn, "hz": round(hz, 2), "midi": midi_no})
                except Exception as e:
                    errors.append(f"{fn}: {str(e)[:60]}")
            if not samples:
                return self._json({"error": "没有可用采样", "detail": errors}, 400)
            meta = {"label": label, "samples": samples}
            with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            return self._json({"id": name, "count": len(samples), "errors": errors,
                               "samples": samples})

        if p == "/api/score_parse":
            raw_b64 = str(body.get("data", ""))
            if not raw_b64:
                return self._json({"error": "缺少文件内容"}, 400)
            try:
                raw = base64.b64decode(raw_b64)
            except Exception:
                return self._json({"error": "文件内容解码失败"}, 400)

            fname = str(body.get("name", "")).lower()
            track_info = []
            is_midi = raw[:4] == b"MThd" or fname.endswith((".mid", ".midi"))
            tmp = os.path.join(R.OUT_DIR, "_score_import.mid" if is_midi else "_score_import.xml")

            try:
                with open(tmp, "wb") as f:
                    f.write(raw)
                if is_midi:
                    tracks, meta = midi.parse_midi(tmp)
                    main = midi.pick_main_track(tracks)
                    if not main:
                        return self._json({"error": "MIDI 里没有音符"}, 400)
                    seq = [[n["midi"], n["dur"], n.get("start", 0)] for n in main["notes"]]
                    meta["kind"] = "midi"
                    meta["tracks"] = len(tracks)
                    meta["main"] = tracks.index(main)
                    track_info = [
                        {"name": f"轨道 {i+1}", "count": len(t["notes"]),
                         "notes": [[n["midi"], n["dur"], n.get("start", 0)] for n in t["notes"]]}
                        for i, t in enumerate(tracks)
                    ]
                else:
                    tracks, meta = musicxml.parse_musicxml_tracks(tmp)
                    main = musicxml.pick_main_track(tracks)
                    if not main:
                        return self._json({"error": "谱面里没有音符"}, 400)
                    seq = [[n["midi"], n["dur"], n.get("start", 0)] for n in main["notes"]]
                    meta["kind"] = "musicxml"
                    meta["tracks"] = len(tracks)
                    meta["main"] = tracks.index(main)
                    track_info = [
                        {"name": t["name"], "count": len(t["notes"]),
                         "notes": [[n["midi"], n["dur"], n.get("start", 0)] for n in t["notes"]]}
                        for t in tracks
                    ]
            except Exception as e:
                return self._json({"error": f"解析失败：{str(e)[:160]}"}, 400)
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)

            if not seq:
                return self._json({"error": "解析不出音符（可能是休止或格式不支持）"}, 400)
            return self._json({"notes": seq, "meta": meta,
                               "tracks": track_info})

        if p == "/api/pack_remove":
            name = re.sub(r"[^\w\-]", "_", str(body.get("id", "")))
            if not name:
                return self._json({"error": "缺少 id"}, 400)
            d = os.path.join(R.USER_DIR, name)
            if not os.path.isdir(d):
                return self._json({"error": "采样包不存在"}, 404)
            try:
                shutil.rmtree(d)
            except Exception as e:
                return self._json({"error": str(e)[:120]}, 500)
            return self._json({"ok": True, "removed": name})

        if p == "/api/pack_rename":
            name = re.sub(r"[^\w\-]", "_", str(body.get("id", "")))
            label = str(body.get("label", "")).strip()[:40]
            if not name or not label:
                return self._json({"error": "缺少参数"}, 400)
            meta_path = os.path.join(R.USER_DIR, name, "meta.json")
            if not os.path.exists(meta_path):
                return self._json({"error": "采样包不存在"}, 404)
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                meta["label"] = label
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception as e:
                return self._json({"error": str(e)[:120]}, 500)
            return self._json({"ok": True, "id": name, "label": label})

        if p == "/api/pack_update":
            name = re.sub(r"[^\w\-]", "_", str(body.get("id", "")))
            meta_path = os.path.join(R.USER_DIR, name, "meta.json")
            if not name or not os.path.exists(meta_path):
                return self._json({"error": "采样包不存在"}, 404)
            updates = body.get("samples") or []
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                by_file = {s.get("file"): s for s in meta.get("samples", [])}
                changed = 0
                for u in updates:
                    s = by_file.get(str(u.get("file", "")))
                    if not s:
                        continue
                    try:
                        hz = float(u.get("hz"))
                    except (TypeError, ValueError):
                        continue
                    if not (20.0 <= hz <= 20000.0):
                        continue
                    s["hz"] = round(hz, 2)
                    s["midi"] = int(round(R.midi_of(hz)))
                    changed += 1
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception as e:
                return self._json({"error": str(e)[:120]}, 500)
            return self._json({"ok": True, "changed": changed, "samples": meta.get("samples", [])})

        return self._json({"error": "not found"}, 404)


def main():
    R._ensure_dirs()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"432Hz studio on http://127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
