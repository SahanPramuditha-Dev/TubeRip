from dataclasses import dataclass, field
from typing import Optional, List, Any, Dict
from enum import Enum
import time
import uuid


class JobStatus(Enum):
    QUEUED      = "queued"
    ANALYZING   = "analyzing"
    DOWNLOADING = "downloading"
    MERGING     = "merging"
    TAGGING     = "tagging"      # New state for metadata writing
    DONE        = "done"
    FAILED      = "failed"
    PAUSED      = "paused"
    CANCELLED   = "cancelled"


class DownloadMode(Enum):
    VIDEO    = "video"
    AUDIO    = "audio"
    PLAYLIST = "playlist"


@dataclass
class VideoMetadata:
    title: str          = ""
    thumbnail_url: str  = ""
    duration: int       = 0          
    channel: str        = ""
    views: int          = 0
    upload_date: str    = ""
    description: str    = ""
    video_id: str       = ""
    formats: list       = field(default_factory=list)
    filesize_approx: int = 0
    like_count: int     = 0
    comment_count: int  = 0
    categories: list    = field(default_factory=list)
    tags: list          = field(default_factory=list)
    # Subtitles
    subtitles: Dict[str, Any] = field(default_factory=dict)
    # Playlist
    is_playlist: bool              = False
    playlist_entries: list         = field(default_factory=list)


@dataclass
class DownloadJob:
    url: str
    mode: DownloadMode  = DownloadMode.VIDEO
    output_format: str  = "mp4"
    audio_bitrate: str  = "192k"
    quality_label: str  = "best"
    format_id: str      = "bestvideo+bestaudio/best"
    speed_limit_kbps: int = 0
    priority: int       = 5          

    # Power User Options
    use_gpu: bool       = False
    embed_subs: bool    = False
    embed_thumb: bool   = True
    write_metadata: bool = True
    subtitle_lang: str  = "en"

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: JobStatus     = JobStatus.QUEUED
    progress: float       = 0.0          
    speed_bps: float      = 0.0
    eta_seconds: int      = 0
    downloaded_bytes: int = 0
    total_bytes: int      = 0
    output_path: str      = ""
    error_msg: str        = ""
    created_at: float     = field(default_factory=time.time)
    started_at: float     = 0.0
    finished_at: float    = 0.0
    retries: int          = 0

    metadata: VideoMetadata = field(default_factory=VideoMetadata)

    @property
    def elapsed(self) -> float:
        if self.started_at:
            end = self.finished_at or time.time()
            return end - self.started_at
        return 0.0

    @property
    def speed_human(self) -> str:
        return self._fmt_bps(self.speed_bps)

    @property
    def size_human(self) -> str:
        b = self.total_bytes
        if b >= 1_073_741_824: return f"{b/1_073_741_824:.2f} GB"
        if b >= 1_048_576:     return f"{b/1_048_576:.1f} MB"
        if b >= 1024:          return f"{b/1024:.0f} KB"
        return f"{b} B"

    @property
    def avg_speed_human(self) -> str:
        if self.elapsed > 0 and self.total_bytes > 0:
            return self._fmt_bps(self.total_bytes / self.elapsed)
        return ""

    @staticmethod
    def _fmt_bps(s: float) -> str:
        if s >= 1_000_000: return f"{s/1_000_000:.1f} MB/s"
        if s >= 1_000:     return f"{s/1_000:.0f} KB/s"
        return f"{s:.0f} B/s"
