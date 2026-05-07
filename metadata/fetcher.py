import yt_dlp
from models.job import VideoMetadata
from typing import Dict, Any

def fetch_metadata(url: str, flat_playlist: bool = True) -> VideoMetadata:
    """Extract metadata. flat_playlist=True for fast playlist summary."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": flat_playlist,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        entries = []
        for e in (info.get("entries") or []):
            if not e: continue
            entries.append({
                "url": e.get("url") or e.get("webpage_url", ""),
                "title": e.get("title", "Unknown"),
                "duration": e.get("duration", 0),
                "thumbnail": e.get("thumbnail", ""),
                "id": e.get("id", ""),
                "uploader": e.get("uploader", ""),
            })
        return VideoMetadata(
            title=info.get("title", "Playlist"),
            channel=info.get("uploader") or info.get("channel", ""),
            video_id=info.get("id", ""),
            playlist_entries=entries,
            is_playlist=True,
        )

    # Video details
    formats = _extract_formats(info)
    subs = info.get("subtitles", {})
    auto_subs = info.get("automatic_captions", {})

    return VideoMetadata(
        title=info.get("title", "Unknown"),
        thumbnail_url=info.get("thumbnail", ""),
        duration=info.get("duration", 0),
        channel=info.get("uploader") or info.get("channel", ""),
        views=info.get("view_count", 0),
        upload_date=info.get("upload_date", ""),
        description=info.get("description", "")[:600],
        video_id=info.get("id", ""),
        formats=formats,
        filesize_approx=info.get("filesize_approx", 0),
        like_count=info.get("like_count", 0),
        subtitles={"manual": list(subs.keys()), "auto": list(auto_subs.keys())},
        categories=info.get("categories") or [],
        tags=info.get("tags") or [],
    )

def _extract_formats(info: dict) -> list:
    formats = []
    seen = set()
    for f in (info.get("formats") or []):
        # Video streams
        res = f.get("height")
        vcodec = f.get("vcodec", "none")
        acodec = f.get("acodec", "none")
        ext = f.get("ext", "")
        
        if res and vcodec != "none":
            fps = f.get("fps") or 30
            label = f"{res}p"
            if fps > 30: label += f" {int(fps)}fps"
            key = (res, int(fps), ext)
            if key in seen: continue
            seen.add(key)
            formats.append({
                "type": "video",
                "label": label, "resolution": res, "fps": fps,
                "format_id": f.get("format_id", ""),
                "filesize": f.get("filesize") or f.get("filesize_approx") or 0,
                "ext": ext,
            })
        elif vcodec == "none" and acodec != "none":
            # Audio streams
            abr = f.get("abr") or 0
            label = f"{int(abr)}k" if abr else "audio"
            key = (label, ext)
            if key in seen: continue
            seen.add(key)
            formats.append({
                "type": "audio",
                "label": label, "resolution": 0, "fps": 0, "abr": abr,
                "format_id": f.get("format_id", ""),
                "filesize": f.get("filesize") or f.get("filesize_approx") or 0,
                "ext": ext,
            })

    formats.sort(key=lambda x: (x["type"] == "video", x["resolution"], x.get("abr", 0)), reverse=True)
    return formats

def format_duration(seconds: int) -> str:
    if not seconds: return "0:00"
    h, m = divmod(seconds, 3600)
    m, s = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def format_views(n: int) -> str:
    if n >= 1_000_000_000: return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.0f}K"
    return str(n)

def size_human(b: int) -> str:
    if b >= 1_073_741_824: return f"{b/1_073_741_824:.1f} GB"
    if b >= 1_048_576: return f"{b/1_048_576:.0f} MB"
    if b >= 1024: return f"{b/1024:.0f} KB"
    return f"{b} B"
