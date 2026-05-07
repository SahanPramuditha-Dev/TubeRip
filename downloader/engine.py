import os
import time
import threading
import heapq
import subprocess
import sys
import json
from pathlib import Path
from typing import Callable, Optional
from http.server import BaseHTTPRequestHandler, HTTPServer
import yt_dlp

from models.job import DownloadJob, JobStatus, DownloadMode
from database.db import (
    save_history, save_resume_state, delete_resume_state,
    get_pending_scheduled_jobs, mark_scheduled_done, get_setting
)

# ── Smart Folder Logic ────────────────────────────────────────────────────

def get_output_path(base_dir: Path, job: DownloadJob) -> Path:
    """Calculates path based on 'Smart Folders' setting."""
    mode_folder = "Audio" if job.mode == DownloadMode.AUDIO else "Videos"
    folder = base_dir / mode_folder
    
    smart_type = get_setting("smart_folder_type", "none") # none, channel, year
    
    if smart_type == "channel" and job.metadata.channel:
        folder = folder / job.metadata.channel
    elif smart_type == "year" and job.metadata.upload_date:
        # upload_date is usually YYYYMMDD
        year = job.metadata.upload_date[:4]
        folder = folder / year
        
    folder.mkdir(parents=True, exist_ok=True)
    return folder

# ── Web API Handler ───────────────────────────────────────────────────────

class TubeRipAPIHandler(BaseHTTPRequestHandler):
    """Simple API to receive URLs from phone/browser."""
    engine = None
    def do_POST(self):
        if self.path == "/add":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data)
                url = data.get("url")
                if url and TubeRipAPIHandler.engine:
                    job = DownloadJob(url=url)
                    TubeRipAPIHandler.engine.enqueue(job)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"status":"added"}')
                    return
            except: pass
        self.send_response(400)
        self.end_headers()

# ══════════════════════════════════════════════════════════════════════════
#  DownloadEngine
# ══════════════════════════════════════════════════════════════════════════

class DownloadEngine:
    MAX_CONCURRENT: int = 3
    GLOBAL_SPEED_LIMIT_KBPS: int = 0
    USE_GPU_ACCEL: bool = False
    PROXY_URL: Optional[str] = None

    def __init__(self, base_dir: str, on_update: Optional[Callable] = None, enable_api: bool = False, enable_scheduler: bool = False):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.on_update = on_update

        self._heap: list = []
        self._heap_lock = threading.Lock()
        self._active: dict = {}
        self._lock = threading.Lock()
        self._stop_flags: dict = {}
        self._pause_flags: dict = {}

        self._job_index: dict = {}

        if enable_scheduler:
            threading.Thread(target=self._scheduler_loop, daemon=True).start()
        if enable_api:
            TubeRipAPIHandler.engine = self
            threading.Thread(target=self._start_api, daemon=True).start()

    def enqueue(self, job: DownloadJob, priority: int = 5):
        with self._heap_lock:
            self._heap.append((priority, job))
            self._heap.sort(key=lambda x: x[0])
            self._job_index[job.id] = job
        self._dispatch()

    def get_queue(self) -> list:
        with self._heap_lock:
            return [job for _, job in self._heap]

    def get_active_jobs(self) -> list:
        with self._lock:
            return [self._job_index[job_id] for job_id in self._active.keys() if job_id in self._job_index]

    def pause_job(self, job_id: str) -> bool:
        flag = self._pause_flags.get(job_id)
        if not flag:
            return False
        flag.set()
        job = self._job_index.get(job_id)
        if job:
            job.status = JobStatus.PAUSED
            self._notify(job)
        return True

    def resume_job(self, job_id: str) -> bool:
        flag = self._pause_flags.get(job_id)
        if not flag:
            return False
        flag.clear()
        job = self._job_index.get(job_id)
        if job and job.status == JobStatus.PAUSED:
            job.status = JobStatus.DOWNLOADING
            self._notify(job)
        return True

    def cancel_job(self, job_id: str) -> bool:
        stop_flag = self._stop_flags.get(job_id)
        if stop_flag:
            stop_flag.set()
            return True
        with self._heap_lock:
            for idx, (_, job) in enumerate(self._heap):
                if job.id == job_id:
                    job.status = JobStatus.CANCELLED
                    self._heap.pop(idx)
                    self._job_index.pop(job_id, None)
                    self._notify(job)
                    return True
        return False

    def wait_for_all(self):
        while True:
            with self._lock, self._heap_lock:
                if not self._active and not self._heap:
                    return
            time.sleep(0.2)

    def _start_api(self):
        try:
            server = HTTPServer(('0.0.0.0', 8080), TubeRipAPIHandler)
            server.serve_forever()
        except: pass

    def enqueue(self, job: DownloadJob, priority: int = 5):
        with self._heap_lock:
            # We use a simple list since heapq doesn't support the custom object directly easily
            self._heap.append((priority, job))
            self._heap.sort(key=lambda x: x[0])
        self._dispatch()

    def _dispatch(self):
        with self._lock:
            while len(self._active) < self.MAX_CONCURRENT and self._heap:
                priority, job = self._heap.pop(0)
                stop_flag = threading.Event()
                pause_flag = threading.Event()
                self._stop_flags[job.id] = stop_flag
                self._pause_flags[job.id] = pause_flag
                t = threading.Thread(target=self._run_job, args=(job, stop_flag, pause_flag), daemon=True)
                self._active[job.id] = t
                t.start()

    def _run_job(self, job: DownloadJob, stop_flag: threading.Event, pause_flag: threading.Event):
        job.started_at = time.time()
        job.status = JobStatus.ANALYZING
        self._notify(job)

        try:
            self._do_download(job, stop_flag, pause_flag)
            if job.status == JobStatus.DONE:
                save_history(job)
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_msg = str(e)
            self._notify(job)

        with self._lock:
            self._active.pop(job.id, None)
        self._dispatch()

    def _do_download(self, job: DownloadJob, stop_flag: threading.Event, pause_flag: threading.Event):
        out_dir = get_output_path(self.base_dir, job)
        outtmpl = str(out_dir / "%(title).100s.%(ext)s")

        def progress_hook(d):
            if stop_flag.is_set():
                raise Exception("Cancelled")
            while pause_flag.is_set():
                job.status = JobStatus.PAUSED
                self._notify(job)
                time.sleep(0.5)
                if stop_flag.is_set():
                    raise Exception("Cancelled")

            if d["status"] == "downloading":
                job.status = JobStatus.DOWNLOADING
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                dl = d.get("downloaded_bytes", 0)
                
                # Save state periodically (every 5MB or so, or if progress jumped significantly)
                if dl - getattr(job, "_last_saved_dl", 0) > 5_000_000:
                    job.total_bytes, job.downloaded_bytes = total, dl
                    save_resume_state(job)
                    job._last_saved_dl = dl

                job.total_bytes, job.downloaded_bytes = total, dl
                job.progress = min((dl / total) * 100, 99.9)
                job.speed_bps, job.eta_seconds = d.get("speed") or 0, d.get("eta") or 0
                self._notify(job)

        # Build options
        ydl_opts = {
            "format": job.format_id,
            "outtmpl": outtmpl,
            "progress_hooks": [progress_hook],
            "postprocessors": [{"key": "FFmpegMetadata", "add_metadata": True}, {"key": "EmbedThumbnail"}],
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "proxy": self.PROXY_URL or get_setting("proxy_url", ""),
            "concurrent_fragment_downloads": 8,
            "writethumbnail": True,
            "continuedl": True,
            "retries": 5,
        }

        if job.speed_limit_kbps > 0:
            ydl_opts["ratelimit"] = int(job.speed_limit_kbps) * 1024

        if job.mode == DownloadMode.AUDIO:
            ydl_opts["postprocessors"].insert(0, {
                "key": "FFmpegExtractAudio",
                "preferredcodec": job.output_format,
                "preferredquality": job.audio_bitrate.replace("k", ""),
            })

        supported_thumb_exts = {"mp3", "mkv", "mka", "ogg", "opus", "flac", "m4a", "mp4", "m4v", "mov"}
        if job.output_format.lower() not in supported_thumb_exts:
            ydl_opts["postprocessors"] = [p for p in ydl_opts["postprocessors"] if p.get("key") != "EmbedThumbnail"]

        if job.use_gpu:
            # Add hardware acceleration flags to FFmpeg
            ydl_opts["postprocessor_args"] = [
                "-hwaccel", "auto",
                "-c:v", "h264_nvenc", # Defaulting to NVENC, can be made dynamic
            ]
            # Some formats might not support NVENC, but it's a good default for 'GPU support'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Initial save
            save_resume_state(job)
            ydl.download([job.url])

        job.status = JobStatus.DONE
        job.progress = 100.0
        job.finished_at = time.time()
        job.output_path = str(out_dir)
        delete_resume_state(job.id)
        self._notify(job)

    def _notify(self, job):
        if self.on_update: self.on_update(job)

    def _scheduler_loop(self):
        while True:
            try:
                pending = get_pending_scheduled_jobs()
                for row in pending:
                    # Enqueue scheduled jobs
                    pass
            except: pass
            time.sleep(60)
