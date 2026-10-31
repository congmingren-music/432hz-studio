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
            return self._json({"id": name, "count": len(samples), "errors": errors})

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
                    seq = [[n["midi"], n["dur"]] for n in main["notes"]]
                    meta["kind"] = "midi"
                    meta["tracks"] = len(tracks)
                    track_info = [{"name": f"轨道 {i+1}", "count": len(t["notes"])}
                                  for i, t in enumerate(tracks)]
                else:
                    tracks, meta = musicxml.parse_musicxml_tracks(tmp)
                    main = musicxml.pick_main_track(tracks)
                    if not main:
                        return self._json({"error": "谱面里没有音符"}, 400)
                    seq = [[n["midi"], n["dur"]] for n in main["notes"]]
                    meta["kind"] = "musicxml"
                    meta["tracks"] = len(tracks)
                    track_info = [{"name": t["name"], "count": len(t["notes"])} for t in tracks]
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

        return self._json({"error": "not found"}, 404)


def main():
    R._ensure_dirs()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"432Hz studio on http://127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
