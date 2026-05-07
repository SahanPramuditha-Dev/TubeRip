"""TubeRip CLI — command line interface for media downloading and management."""

import argparse
import shlex
import time
from pathlib import Path
from typing import Dict, List, Optional

import yt_dlp

from database.db import (
    delete_profile,
    get_all_scheduled,
    get_history,
    get_profiles,
    get_setting,
    get_stats,
    init_db,
    save_profile,
    save_scheduled_job,
    set_setting,
)
from downloader.engine import DownloadEngine
from metadata.fetcher import (
    fetch_metadata,
    format_duration,
    format_views,
    size_human,
)
from models.job import DownloadJob, DownloadMode, VideoMetadata


# ANSI Colors
CLR_RESET = "\033[0m"
CLR_BOLD = "\033[1m"
CLR_CYAN = "\033[36m"
CLR_GREEN = "\033[32m"
CLR_YELLOW = "\033[33m"
CLR_RED = "\033[31m"
CLR_BLUE = "\033[34m"
CLR_MAGENTA = "\033[35m"
CLR_WHITE = "\033[37m"


def print_header(title: str, color: str = CLR_CYAN):
    print(f"\n{CLR_BOLD}{color}{title}{CLR_RESET}")
    print(f"{color}{'=' * len(title)}{CLR_RESET}")


def choose_format(format_id: Optional[str], mode: DownloadMode) -> str:
    if format_id:
        return format_id
    if mode == DownloadMode.AUDIO:
        return "bestaudio/best"
    return "bestvideo+bestaudio/best"


def print_metadata(meta: VideoMetadata):
    print_header("Metadata", CLR_MAGENTA)
    print(f"{CLR_BOLD}{CLR_CYAN}{'Title:':<15}{CLR_RESET} {meta.title}")
    print(f"{CLR_BOLD}{CLR_CYAN}{'Channel:':<15}{CLR_RESET} {meta.channel}")
    print(f"{CLR_BOLD}{CLR_CYAN}{'Duration:':<15}{CLR_RESET} {format_duration(meta.duration)}")
    print(f"{CLR_BOLD}{CLR_CYAN}{'Views:':<15}{CLR_RESET} {format_views(meta.views)}")
    print(f"{CLR_BOLD}{CLR_CYAN}{'Date:':<15}{CLR_RESET} {meta.upload_date}")
    print(f"{CLR_BOLD}{CLR_CYAN}{'ID:':<15}{CLR_RESET} {meta.video_id}")
    if meta.is_playlist:
        print(f"{CLR_BOLD}{CLR_CYAN}{'Playlist:':<15}{CLR_RESET} {CLR_GREEN}YES{CLR_RESET} ({len(meta.playlist_entries)} items)")
    if meta.tags:
        print(f"{CLR_BOLD}{CLR_CYAN}{'Tags:':<15}{CLR_RESET} {', '.join(meta.tags[:8])}...")


def print_formats(meta: VideoMetadata):
    if meta.is_playlist:
        print(f"\n{CLR_YELLOW}Playlist detected. Use --playlist to queue entries or analyze an individual video URL.{CLR_RESET}")
        return

    if not meta.formats:
        print(f"\n{CLR_RED}No formats available.{CLR_RESET}")
        return

    counter = 1
    # Video Formats
    video_fmts = [f for f in meta.formats if f.get("type") == "video"]
    if video_fmts:
        print_header("Video Formats", CLR_GREEN)
        header = f"{'#':<3} {'format_id':<14} {'ext':<6} {'resolution':<12} {'size':<10}"
        print(f"{CLR_BOLD}{header}{CLR_RESET}")
        print("-" * len(header))
        for fmt in video_fmts:
            size = size_human(fmt.get("filesize", 0))
            print(f"{CLR_WHITE}{counter:<3}{CLR_RESET} {CLR_CYAN}{fmt['format_id']:<14}{CLR_RESET} {fmt['ext']:<6} {CLR_YELLOW}{fmt['label']:<12}{CLR_RESET} {size:<10}")
            fmt["selection_idx"] = str(counter)
            counter += 1

    # Audio Formats
    audio_fmts = [f for f in meta.formats if f.get("type") == "audio"]
    if audio_fmts:
        print_header("Audio Formats (MP3/M4A)", CLR_YELLOW)
        header = f"{'#':<3} {'format_id':<14} {'ext':<6} {'bitrate':<12} {'size':<10}"
        print(f"{CLR_BOLD}{header}{CLR_RESET}")
        print("-" * len(header))
        for fmt in audio_fmts:
            size = size_human(fmt.get("filesize", 0))
            print(f"{CLR_WHITE}{counter:<3}{CLR_RESET} {CLR_CYAN}{fmt['format_id']:<14}{CLR_RESET} {fmt['ext']:<6} {CLR_GREEN}{fmt['label']:<12}{CLR_RESET} {size:<10}")
            fmt["selection_idx"] = str(counter)
            counter += 1


def extract_direct_url(url: str, format_id: Optional[str] = None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        print("Direct URL extraction is not supported for playlists. Provide a single video URL.")
        return

    formats = info.get("formats", [])
    if not formats:
        print("No formats found.")
        return

    if format_id:
        fmt = next((f for f in formats if f.get("format_id") == format_id), None)
    else:
        fmt = max(formats, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0, f.get("fps") or 0))

    if not fmt:
        print(f"Format ID {format_id} not found.")
        return

    print_header("Direct Stream URL")
    print(f"format_id: {fmt.get('format_id')}")
    print(f"type: {fmt.get('ext')} / {fmt.get('acodec')}/{fmt.get('vcodec')}")
    print(f"resolution: {fmt.get('resolution') or fmt.get('format_note')}")
    print(f"filesize: {size_human(fmt.get('filesize') or fmt.get('filesize_approx') or 0)}")
    print(f"url: {fmt.get('url')}")


def build_metadata_from_entry(entry: dict, playlist_meta: VideoMetadata) -> VideoMetadata:
    return VideoMetadata(
        title=entry.get("title", "Unknown"),
        duration=entry.get("duration", 0) or 0,
        thumbnail_url=entry.get("thumbnail", ""),
        channel=playlist_meta.channel,
        video_id=entry.get("id", ""),
    )


def build_job(args: argparse.Namespace, url: str, metadata: Optional[VideoMetadata] = None) -> DownloadJob:
    job = DownloadJob(url=url)
    profile_name = getattr(args, "profile", None)
    if profile_name:
        profile = load_profile(profile_name)
        if not profile:
            raise ValueError(f"Profile '{profile_name}' not found.")
        job.mode = DownloadMode(profile["mode"])
        job.output_format = profile["output_format"]
        job.audio_bitrate = profile["audio_bitrate"]
        job.quality_label = profile["quality_label"]
        job.format_id = profile["quality_label"]
    else:
        job.mode = DownloadMode(getattr(args, "mode", "video"))
        job.output_format = getattr(args, "output_format", "mp4")
        job.audio_bitrate = getattr(args, "audio_bitrate", "192k")
        job.format_id = choose_format(getattr(args, "format_id", None), job.mode)
        job.quality_label = getattr(args, "format_id", None) or job.format_id

    if metadata and job.format_id:
        selected = next((f for f in metadata.formats if f.get("format_id") == job.format_id), None)
        if selected and selected.get("type") == "audio":
            job.mode = DownloadMode.AUDIO
            # Prefer preserving the selected audio codec if no explicit output format was configured.
            job.output_format = selected.get("ext", job.output_format)

    job.speed_limit_kbps = getattr(args, "speed_limit", 0)
    job.use_gpu = getattr(args, "gpu", False)
    job.metadata = metadata or VideoMetadata(title=url)
    return job


def load_profile(name: str) -> Optional[Dict]:
    for profile in get_profiles():
        if profile["name"].lower() == name.lower():
            return profile
    return None


def smart_recommend_format(meta: VideoMetadata) -> Optional[str]:
    """Recommends a format based on quality/size balance (target 1080p)."""
    if not meta.formats:
        return None
    # Filter for mp4/mkv and resolution <= 1080
    candidates = [f for f in meta.formats if f.get("resolution", 0) <= 1080]
    if not candidates:
        candidates = meta.formats
    # Pick the one closest to 1080p
    recommended = max(candidates, key=lambda f: f.get("resolution", 0))
    return recommended.get("format_id")


def print_job_update(job: DownloadJob):
    title = job.metadata.title or job.url
    pct = job.progress or 0.0
    progress_text = f"{pct:.1f}%"
    speed_text = job.speed_human if job.speed_bps else "0 B/s"
    eta_text = format_duration(job.eta_seconds) if job.eta_seconds else "--:--"
    
    # Modern Bar with Gradient Look (using colored blocks)
    bar_width = 30
    filled = int(bar_width * pct / 100)
    
    # Gradient simulation with Green/Cyan
    if pct < 30:
        bar_color = CLR_CYAN
    elif pct < 70:
        bar_color = CLR_GREEN
    else:
        bar_color = CLR_BLUE
        
    bar = f"{bar_color}{'█' * filled}{CLR_RESET}{CLR_WHITE}{'░' * (bar_width - filled)}{CLR_RESET}"
    
    status_clr = CLR_YELLOW
    status_icon = "◌"
    status_label = job.status.value.upper()
    
    if job.status.value == "done":
        status_clr = CLR_GREEN
        status_icon = "●"
    elif job.status.value == "failed":
        status_clr = CLR_RED
        status_icon = "×"
    elif job.status.value == "downloading":
        status_clr = CLR_CYAN
        status_icon = "↓"
    elif job.status.value == "analyzing":
        status_clr = CLR_MAGENTA
        status_icon = "¤"
    elif job.status.value == "paused":
        status_clr = CLR_WHITE
        status_icon = "‖"

    # Dash-style layout
    # [↓ DOWNLOADING] Title | Bar | 45% | Speed | ETA
    
    prefix = f"{CLR_BOLD}{status_clr}{status_icon} {status_label:<11}{CLR_RESET}"
    header = f"{CLR_BOLD}{CLR_WHITE}{title[:35]:<35}{CLR_RESET}"
    
    # \x1b[2K clears the line, \r moves to start
    line = f"\r\x1b[2K  {prefix} {header} │ {bar} │ {CLR_BOLD}{progress_text:>6}{CLR_RESET} │ {CLR_YELLOW}{speed_text:>9}{CLR_RESET} │ {CLR_MAGENTA}{eta_text}{CLR_RESET}"
    
    print(line, end="", flush=True)
    
    if job.status.value == "done":
        # Clear the progress line and print the final success card
        print(f"\r\x1b[2K  {CLR_GREEN}● COMPLETED  {CLR_RESET} {CLR_BOLD}{title[:50]}{CLR_RESET}")
        print(f"    ╰─ {CLR_CYAN}Size:{CLR_RESET} {job.size_human:<10} │ {CLR_CYAN}Speed:{CLR_RESET} {job.avg_speed_human:<10} │ {CLR_CYAN}Time:{CLR_RESET} {job.elapsed:.1f}s")
    elif job.status.value in ("failed", "cancelled"):
        print()
        if job.error_msg:
            print(f"    ╰─ {CLR_RED}Error: {job.error_msg}{CLR_RESET}")


def init_engine(download_dir: Optional[str] = None, enable_api: bool = False, enable_scheduler: bool = False) -> DownloadEngine:
    base_dir = Path(download_dir or get_setting("download_dir", str(Path.home() / "Downloads" / "TubeRip")))
    base_dir.mkdir(parents=True, exist_ok=True)
    return DownloadEngine(str(base_dir), on_update=print_job_update, enable_api=enable_api, enable_scheduler=enable_scheduler)


def enqueue_downloads(engine: DownloadEngine, args: argparse.Namespace, urls: List[str]):
    for url in urls:
        try:
            meta = fetch_metadata(url)
        except Exception as exc:
            print(f"Failed to analyze URL {url}: {exc}")
            continue

        if meta.is_playlist:
            if not args.playlist:
                print(f"Playlist URL detected for {url}. Use --playlist to enqueue playlist entries.")
                continue
            print(f"Queuing playlist '{meta.title}' ({len(meta.playlist_entries)} items)...")
            for entry in meta.playlist_entries:
                entry_meta = build_metadata_from_entry(entry, meta)
                job = build_job(args, entry["url"], metadata=entry_meta)
                engine.enqueue(job)
                print(f"  queued: {entry_meta.title}")
        else:
            job = build_job(args, url, metadata=meta)
            engine.enqueue(job)
            print(f"Queued: {meta.title}")


def command_analyze(args: argparse.Namespace):
    meta = fetch_metadata(args.url)
    print_metadata(meta)
    if meta.is_playlist:
        print(f"\n{CLR_BOLD}Playlist Summary:{CLR_RESET}")
        print(f"  {CLR_CYAN}Total Videos:{CLR_RESET} {len(meta.playlist_entries)}")
        print(f"  {CLR_YELLOW}Use 'download {args.url} --playlist' to queue all videos.{CLR_RESET}")
    else:
        print_formats(meta)


def command_formats(args: argparse.Namespace):
    meta = fetch_metadata(args.url)
    print_formats(meta)


def command_direct_url(args: argparse.Namespace):
    extract_direct_url(args.url, args.format_id)


def command_download(args: argparse.Namespace):
    engine = init_engine(getattr(args, "download_dir", None))
    
    if args.interactive and len(args.urls) == 1:
        url = args.urls[0]
        meta = fetch_metadata(url)
        print_metadata(meta)
        print_formats(meta)
        
        rec_id = smart_recommend_format(meta)
        rec_idx = None
        if rec_id:
            for f in meta.formats:
                if f.get("format_id") == rec_id:
                    rec_idx = f.get("selection_idx")
                    break
                    
        prompt = f"\n{CLR_BOLD}Enter Selection # or Format ID"
        if rec_idx:
            prompt += f" {CLR_CYAN}(Recommended: {rec_idx}){CLR_RESET}{CLR_BOLD}"
        elif rec_id:
            prompt += f" {CLR_CYAN}(Recommended: {rec_id}){CLR_RESET}{CLR_BOLD}"
        prompt += " or press Enter for default: "
        
        fmt_id = input(f"{prompt}{CLR_RESET}").strip()
        if fmt_id:
            # Check if user entered a selection index instead of format_id
            for f in meta.formats:
                if f.get("selection_idx") == fmt_id:
                    fmt_id = f["format_id"]
                    break
            args.format_id = fmt_id
            selected_fmt = next((f for f in meta.formats if f.get("format_id") == fmt_id), None)
            if selected_fmt and selected_fmt.get("type") == "audio":
                print(f"\n{CLR_YELLOW}Note: you've selected an audio-only stream. This download will be saved as audio and thumbnails may only embed for supported audio containers.{CLR_RESET}")

    enqueue_downloads(engine, args, args.urls)
    print(f"\n{CLR_YELLOW}Waiting for all downloads to complete...{CLR_RESET}")
    engine.wait_for_all()
    print(f"{CLR_GREEN}{CLR_BOLD}Downloads finished.{CLR_RESET}")


def command_search(args: argparse.Namespace):
    print(f"{CLR_YELLOW}Searching for: {CLR_BOLD}{args.query}{CLR_RESET}...")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
    }
    search_url = f"ytsearch{args.limit}:{args.query}"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(search_url, download=False)
    
    entries = info.get("entries", [])
    if not entries:
        print(f"{CLR_RED}No results found.{CLR_RESET}")
        return

    print_header(f"Search Results for '{args.query}'", CLR_BLUE)
    for i, entry in enumerate(entries, 1):
        title = entry.get("title", "Unknown")
        uploader = entry.get("uploader", "Unknown")
        duration = format_duration(entry.get("duration", 0))
        url = entry.get("url") or entry.get("webpage_url")
        print(f"{CLR_BOLD}{i}. {CLR_RESET}{title[:60]:<60} | {CLR_GREEN}{uploader:<20}{CLR_RESET} | {CLR_YELLOW}{duration}{CLR_RESET}")
        print(f"   {CLR_CYAN}{url}{CLR_RESET}\n")

    if entries:
        choice = input(f"{CLR_BOLD}Enter number to download (or press Enter to skip): {CLR_RESET}").strip()
        if choice:
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(entries):
                    target = entries[idx]
                    engine = init_engine()
                    # Re-analyze to get full formats for the specific video
                    meta = fetch_metadata(target["url"])
                    job = build_job(args, target["url"], metadata=meta)
                    engine.enqueue(job)
                    print(f"{CLR_GREEN}Queued: {meta.title}{CLR_RESET}")
                    engine.wait_for_all()
            except ValueError:
                print(f"{CLR_RED}Invalid choice.{CLR_RESET}")


def command_resume(args: argparse.Namespace):
    from database.db import get_resume_states
    states = get_resume_states()
    if not states:
        print(f"{CLR_YELLOW}No interrupted downloads found.{CLR_RESET}")
        return

    print_header("Interrupted Downloads", CLR_YELLOW)
    for i, s in enumerate(states, 1):
        import json
        meta = json.loads(s.get("metadata_json", "{}"))
        title = meta.get("title", s["url"])
        progress = (s["downloaded_bytes"] / s["total_bytes"] * 100) if s["total_bytes"] else 0
        print(f"{CLR_BOLD}{i}. {CLR_RESET}{title[:60]:<60} | {progress:.1f}% | {s['id']}")

    idx_str = input(f"\n{CLR_BOLD}Enter number to resume (or 'all', or press Enter to cancel): {CLR_RESET}").strip()
    if not idx_str:
        return

    engine = init_engine()
    to_resume = []
    if idx_str.lower() == "all":
        to_resume = states
    else:
        try:
            idx = int(idx_str) - 1
            if 0 <= idx < len(states):
                to_resume = [states[idx]]
        except ValueError:
            print(f"{CLR_RED}Invalid input.{CLR_RESET}")
            return

    for s in to_resume:
        # Reconstruct job from state
        from models.job import DownloadJob, DownloadMode, VideoMetadata
        import json
        meta_data = json.loads(s.get("metadata_json", "{}"))
        job = DownloadJob(
            url=s["url"],
            mode=DownloadMode(s["mode"]),
            output_format=s["output_format"],
            audio_bitrate=s["audio_bitrate"],
            quality_label=s["quality_label"],
            format_id=s["format_id"],
            id=s["id"]
        )
        job.metadata = VideoMetadata(
            title=meta_data.get("title", ""),
            duration=meta_data.get("duration", 0),
            channel=meta_data.get("channel", "")
        )
        job.downloaded_bytes = s["downloaded_bytes"]
        job.total_bytes = s["total_bytes"]
        engine.enqueue(job)
        print(f"{CLR_GREEN}Resumed: {job.metadata.title}{CLR_RESET}")

    engine.wait_for_all()


def format_bps(bps: float) -> str:
    if bps >= 1_000_000:
        return f"{bps/1_000_000:.1f} MB/s"
    if bps >= 1_000:
        return f"{bps/1_000:.0f} KB/s"
    return f"{bps:.0f} B/s"


def command_history(args: argparse.Namespace):
    items = get_history(limit=args.limit, search=args.search, status_filter=getattr(args, "status", ""))
    if not items:
        print("No history records found.")
        return
    print_header("History")
    print(f"  {'Status':<10} {'Finished':<16} {'Channel':<20} {'Title':<35} {'Fmt':<4} {'Dur':<7} {'Size':<10} {'Speed':<10}")
    print("  " + "-" * 120)
    for item in items:
        finished = time.strftime("%Y-%m-%d %H:%M", time.localtime(item["finished_at"])) if item["finished_at"] else "N/A"
        speed = format_bps(item.get("avg_speed_bps") or 0)
        fmt = item.get('output_format') or "?"
        title = item.get('title') or "Unknown"
        channel = item.get('channel') or "Unknown"
        print(
            f"  {item['status']:<10} {finished:<16} {channel[:20]:<20} "
            f"{title[:35]:<35} {fmt:<4} {format_duration(item.get('duration', 0)):<7} "
            f"{size_human(item.get('total_bytes', 0)):<10} {speed:<10}"
        )


def command_analytics(args: argparse.Namespace):
    stats = get_stats()
    print_header("Analytics Dashboard", CLR_MAGENTA)
    
    print(f"{CLR_BOLD}Overview:{CLR_RESET}")
    print(f"  {CLR_CYAN}Total Downloads:{CLR_RESET} {stats['total_downloads']:<10} | {CLR_CYAN}Total Data:{CLR_RESET} {size_human(stats['total_bytes'])}")
    print(f"  {CLR_CYAN}Success Rate:{CLR_RESET} {stats['success_rate']:.1f}% | {CLR_CYAN}Average Speed:{CLR_RESET} {format_bps(stats['avg_speed_bps'])}")
    print(f"  {CLR_CYAN}Average Duration:{CLR_RESET} {format_duration(int(stats['avg_duration']))}")

    if stats.get("status_counts"):
        print(f"\n{CLR_BOLD}Status Breakdown:{CLR_RESET}")
        for row in stats["status_counts"]:
            print(f"  {row['status']:<10} {CLR_GREEN}{row['cnt']}{CLR_RESET}")

    if stats.get("mode_counts"):
        print(f"\n{CLR_BOLD}Mode Breakdown:{CLR_RESET}")
        for row in stats["mode_counts"]:
            print(f"  {row['mode']:<8} {CLR_CYAN}{row['cnt']}{CLR_RESET}")

    print(f"\n{CLR_BOLD}Popular Formats:{CLR_RESET}")
    for ext, count in stats["formats"].items():
        bar = "█" * min(count, 30)
        print(f"  {ext:<6} {CLR_GREEN}{bar}{CLR_RESET} ({count})")

    if stats.get("quality_labels"):
        print(f"\n{CLR_BOLD}Top Quality Labels:{CLR_RESET}")
        for q in stats["quality_labels"]:
            print(f"  {q['quality_label']:<20} {CLR_YELLOW}{q['cnt']}{CLR_RESET}")

    if stats.get("channels"):
        print(f"\n{CLR_BOLD}Top Channels:{CLR_RESET}")
        for c in stats["channels"]:
            print(f"  {CLR_YELLOW}{c['cnt']:>3}x{CLR_RESET} {c['channel']}"
        )

    if stats.get("daily"):
        print(f"\n{CLR_BOLD}Last 7 Days activity:{CLR_RESET}")
        for d in stats["daily"]:
            print(f"  {d['day']}: {CLR_CYAN}{d['cnt']:>2} downloads{CLR_RESET} ({size_human(d['bytes'])})")


def command_stats(args: argparse.Namespace):
    command_analytics(args)


def command_profiles(args: argparse.Namespace):
    if args.action == "list":
        profiles = get_profiles()
        if not profiles:
            print("No profiles available.")
            return
        print_header("Profiles")
        for profile in profiles:
            print(f"{profile['name']}: {profile['mode']} / {profile['output_format']} / {profile['quality_label']} ({profile['description']})")
    elif args.action == "add":
        if not args.name:
            raise ValueError("Profile name is required for add.")
        save_profile(args.name, args.mode, args.output_format, args.audio_bitrate, args.quality_label, args.description or "")
        print(f"Saved profile '{args.name}'.")
    elif args.action == "delete":
        if not args.name:
            raise ValueError("Profile name is required for delete.")
        delete_profile(args.name)
        print(f"Deleted profile '{args.name}'.")


def command_config(args: argparse.Namespace):
    if args.action == "get":
        value = get_setting(args.key, "")
        print(value)
    elif args.action == "set":
        if args.value is None:
            raise ValueError("Value is required for config set.")
        set_setting(args.key, args.value)
        print(f"Set {args.key} = {args.value}")
    elif args.action == "list":
        from database.db import get_connection
        conn = get_connection()
        rows = conn.execute("SELECT * FROM app_settings ORDER BY key").fetchall()
        conn.close()
        print_header("App Settings", CLR_CYAN)
        for r in rows:
            print(f"  {CLR_BOLD}{r['key']:<20}{CLR_RESET} = {r['value']}")


def command_theme(args: argparse.Namespace):
    print_header("Color Palette Preview", CLR_MAGENTA)
    colors = {
        "CYAN": CLR_CYAN, "GREEN": CLR_GREEN, "YELLOW": CLR_YELLOW, 
        "RED": CLR_RED, "BLUE": CLR_BLUE, "MAGENTA": CLR_MAGENTA,
        "BOLD": CLR_BOLD
    }
    for name, code in colors.items():
        print(f"  {code}{name:<10}{CLR_RESET} -> This is {name.lower()} text.")
    print(f"\n  {CLR_BOLD}{CLR_BLUE}[{CLR_RESET}{CLR_BOLD}{CLR_YELLOW}PRO BADGE{CLR_RESET}{CLR_BOLD}{CLR_BLUE}]{CLR_RESET} example.")


def command_monitor(args: argparse.Namespace):
    import os
    try:
        import pyperclip
    except ImportError:
        print(f"{CLR_RED}Error: 'pyperclip' library is required for monitoring.{CLR_RESET}")
        print("Install it with: pip install pyperclip")
        return

    print_header("Clipboard Monitor Started", CLR_YELLOW)
    print(f"{CLR_CYAN}Listening for YouTube URLs... (Press Ctrl+C to stop){CLR_RESET}")
    engine = init_engine()
    last_url = ""
    
    try:
        while True:
            url = pyperclip.paste().strip()
            if url != last_url and ("youtube.com/watch" in url or "youtu.be/" in url):
                print(f"\n{CLR_GREEN}Detected URL:{CLR_RESET} {url}")
                try:
                    meta = fetch_metadata(url)
                    job = build_job(args, url, metadata=meta)
                    engine.enqueue(job)
                    print(f"  {CLR_GREEN}Queued:{CLR_RESET} {meta.title}")
                except Exception as e:
                    print(f"  {CLR_RED}Failed to queue:{CLR_RESET} {e}")
                last_url = url
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{CLR_YELLOW}Monitor stopped.{CLR_RESET}")


def command_schedule(args: argparse.Namespace):
    if args.action == "list":
        schedules = get_all_scheduled()
        if not schedules:
            print("No scheduled jobs.")
            return
        print_header("Scheduled Jobs")
        for item in schedules:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item["scheduled_at"]))
            print(f"{item['id']}: {item['url']} @ {when} [{item['status']}]")
    elif args.action == "add":
        if not args.when or not args.url:
            raise ValueError("--when and url are required for schedule add")
        scheduled_at = int(time.mktime(time.strptime(args.when, "%Y-%m-%d %H:%M:%S")))
        save_scheduled_job(
            args.id or str(time.time()),
            args.url,
            args.mode,
            args.output_format or "mp4",
            args.audio_bitrate or "192k",
            args.quality_label or "bestvideo+bestaudio/best",
            args.format_id or "bestvideo+bestaudio/best",
            scheduled_at,
        )
        print(f"Scheduled {args.url} for {args.when}")


def command_shell(args: argparse.Namespace):
    engine = init_engine(
        getattr(args, "download_dir", None),
        enable_api=getattr(args, "api", False),
        enable_scheduler=getattr(args, "scheduler", True)
    )
    
    badge = f"{CLR_BOLD}{CLR_BLUE}[{CLR_RESET}{CLR_BOLD}{CLR_YELLOW}PRO EDITION{CLR_RESET}{CLR_BOLD}{CLR_BLUE}]{CLR_RESET}"
    banner = r"""{CLR_CYAN}
  _____      _        _____  _       
 |_   _|    | |      |  __ \(_)      
   | | _   _| |__ ___| |__) |_ _ __  
   | || | | | '_ \ / _ \  _  /| | '_ \ 
   | || |_| | |_) |  __/ | \ \| | |_) |
   |_| \__,_|_.__/ \___|_|  \_\_| .__/ 
                                | |    
                                |_|    {CLR_RESET}
    {CLR_BOLD}TubeRip Pro{CLR_RESET} {badge}
    """
    # Escaping braces for .format()
    fmt_banner = banner.replace("{", "{{").replace("}", "}}")
    # Restore the markers for formatting
    fmt_banner = fmt_banner.replace("{{CLR_CYAN}}", "{CLR_CYAN}").replace("{{CLR_RESET}}", "{CLR_RESET}").replace("{{CLR_BOLD}}", "{CLR_BOLD}").replace("{{badge}}", "{badge}")
    print(fmt_banner.format(CLR_CYAN=CLR_CYAN, CLR_RESET=CLR_RESET, CLR_BOLD=CLR_BOLD, badge=badge))

    def show_menu():
        print_header("Main Menu", CLR_BLUE)
        print(f"  {CLR_BOLD}1.{CLR_RESET} {CLR_CYAN}Quick Download{CLR_RESET} (Interactive)")
        print(f"  {CLR_BOLD}2.{CLR_RESET} {CLR_CYAN}Search YouTube{CLR_RESET}")
        print(f"  {CLR_BOLD}3.{CLR_RESET} {CLR_CYAN}Clipboard Monitor{CLR_RESET}")
        print(f"  {CLR_BOLD}4.{CLR_RESET} {CLR_CYAN}Resume Downloads{CLR_RESET}")
        print(f"  {CLR_BOLD}5.{CLR_RESET} {CLR_CYAN}History & Analytics{CLR_RESET}")
        print(f"  {CLR_BOLD}6.{CLR_RESET} {CLR_CYAN}Settings & Config{CLR_RESET}")
        print(f"  {CLR_BOLD}0.{CLR_RESET} {CLR_YELLOW}Exit{CLR_RESET}")
        print(f"\n{CLR_GREEN}Type a number or a command (type 'help' for full list){CLR_RESET}")

    def check_resumes():
        from database.db import get_resume_states
        states = get_resume_states()
        if states:
            print(f"\n{CLR_YELLOW}🔔 {CLR_BOLD}Detected {len(states)} interrupted downloads.{CLR_RESET}")
            ans = input(f"{CLR_CYAN}Would you like to resume them now? (y/n): {CLR_RESET}").lower().strip()
            if ans == 'y':
                command_resume(argparse.Namespace())

    show_menu()
    check_resumes()
    
    while True:
        try:
            prompt = input(f"{CLR_BOLD}{CLR_BLUE}tuberip>{CLR_RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{CLR_YELLOW}Exiting shell.{CLR_RESET}")
            break
        if not prompt:
            continue
        
        # Numeric menu selection
        if prompt == "1":
            url = input(f"{CLR_CYAN}Enter YouTube URL: {CLR_RESET}").strip()
            if url: prompt = f"download {url} --interactive"
            else: continue
        elif prompt == "2": 
            q = input(f"{CLR_CYAN}Search query: {CLR_RESET}").strip()
            if q: prompt = f"search \"{q}\""
            else: continue
        elif prompt == "3": prompt = "monitor"
        elif prompt == "4": prompt = "resume"
        elif prompt == "5": prompt = "analytics"
        elif prompt == "6":
            command_config(argparse.Namespace(action="list"))
            change = input(f"{CLR_CYAN}Change a setting? (y/n): {CLR_RESET}").strip().lower()
            if change == "y":
                key = input(f"{CLR_CYAN}Setting key: {CLR_RESET}").strip()
                value = input(f"{CLR_CYAN}New value: {CLR_RESET}").strip()
                if key and value:
                    command_config(argparse.Namespace(action="set", key=key, value=value))
            continue
        elif prompt == "0": break
        elif prompt.lower() == "menu":
            show_menu()
            continue

        parts = shlex.split(prompt)
        if not parts:
            continue
        cmd = parts[0].lower()
        if cmd in {"exit", "quit"}:
            break
        try:
            if cmd in {"cls", "clear"}:
                import os
                os.system("cls" if os.name == "nt" else "clear")
                show_menu()
                continue
            if cmd == "help":
                print(f"{CLR_BOLD}Available Commands:{CLR_RESET}")
                print(f"  {CLR_GREEN}download{CLR_RESET} <url>, {CLR_GREEN}search{CLR_RESET} <query>, {CLR_GREEN}monitor{CLR_RESET}")
                print(f"  {CLR_GREEN}analyze{CLR_RESET} <url>, {CLR_GREEN}formats{CLR_RESET} <url>, {CLR_GREEN}resume{CLR_RESET}")
                print(f"  {CLR_GREEN}queue{CLR_RESET}, {CLR_GREEN}pause{CLR_RESET}, {CLR_GREEN}resume{CLR_RESET}, {CLR_GREEN}cancel{CLR_RESET}")
                print(f"  {CLR_GREEN}history{CLR_RESET}, {CLR_GREEN}analytics{CLR_RESET}, {CLR_GREEN}profiles{CLR_RESET}, {CLR_GREEN}theme{CLR_RESET}, {CLR_GREEN}settings{CLR_RESET}")
                print(f"  {CLR_GREEN}open{CLR_RESET} (folder), {CLR_GREEN}cls{CLR_RESET}, {CLR_GREEN}exit{CLR_RESET}")
                continue
            if cmd == "download":
                parser = argparse.ArgumentParser(prog="download")
                parser.add_argument("urls", nargs="+", help="Video or playlist URLs")
                parser.add_argument("--mode", choices=["video", "audio"], default="video")
                parser.add_argument("--format-id", help="yt-dlp format selector")
                parser.add_argument("--output-format", help="Output file extension")
                parser.add_argument("--audio-bitrate", default="192k")
                parser.add_argument("--speed-limit", type=int, default=0)
                parser.add_argument("--playlist", action="store_true")
                parser.add_argument("--interactive", "-i", action="store_true")
                parser.add_argument("--gpu", action="store_true")
                try:
                    shell_args = parser.parse_args(parts[1:])
                    command_download(shell_args)
                    show_menu()
                except SystemExit:
                    pass
                continue
            if cmd == "queue":
                active = engine.get_active_jobs()
                queued = engine.get_queue()
                print_header("Active Jobs")
                for job in active:
                    print(f"{job.id}: {job.metadata.title[:50]} ({job.status.value}) {job.progress:.1f}%")
                print_header("Queued Jobs")
                for job in queued:
                    print(f"{job.id}: {job.metadata.title[:50]} ({job.status.value})")
                continue
            if cmd in {"pause", "resume", "cancel"}:
                if len(parts) < 2:
                    print(f"Usage: {cmd} <job_id>")
                    continue
                job_id = parts[1]
                handler = {
                    "pause": engine.pause_job,
                    "resume": engine.resume_job,
                    "cancel": engine.cancel_job,
                }[cmd]
                success = handler(job_id)
                print("OK" if success else "Job not found")
                continue
            if cmd == "analyze":
                if len(parts) < 2:
                    print("Usage: analyze <url>")
                    continue
                command_analyze(argparse.Namespace(url=parts[1]))
                continue
            if cmd == "formats":
                if len(parts) < 2:
                    print("Usage: formats <url>")
                    continue
                command_formats(argparse.Namespace(url=parts[1]))
                continue
            if cmd == "direct-url":
                if len(parts) < 2:
                    print("Usage: direct-url <url> [format_id]")
                    continue
                command_direct_url(argparse.Namespace(url=parts[1], format_id=parts[2] if len(parts) > 2 else None))
                continue
            if cmd == "search":
                parser = argparse.ArgumentParser(prog="search")
                parser.add_argument("query")
                parser.add_argument("--limit", type=int, default=10)
                try:
                    shell_args = parser.parse_args(parts[1:])
                    command_search(shell_args)
                    show_menu()
                except: pass
                continue
            if cmd == "resume":
                command_resume(args)
                continue
            if cmd == "monitor":
                command_monitor(args)
                continue
            if cmd == "open":
                folder = get_setting("download_dir")
                print(f"{CLR_CYAN}Opening folder: {folder}{CLR_RESET}")
                if os.name == 'nt':
                    os.startfile(folder)
                else:
                    import subprocess
                    subprocess.run(['open' if sys.platform == 'darwin' else 'xdg-open', folder])
                continue
            if cmd == "theme":
                command_theme(args)
                continue
            if cmd == "history":
                command_history(argparse.Namespace(limit=20, search=""))
                continue
            if cmd in {"stats", "analytics"}:
                command_analytics(argparse.Namespace())
                continue
            elif cmd in {"config", "settings"}:
                parser = argparse.ArgumentParser(prog=cmd)
                parser.add_argument("action", choices=["get", "set", "list"])
                parser.add_argument("key", nargs="?")
                parser.add_argument("value", nargs="?")
                try:
                    shell_args = parser.parse_args(parts[1:])
                    command_config(shell_args)
                except: pass
                continue
            print(f"{CLR_RED}Unknown command: {cmd}{CLR_RESET}")
        except KeyboardInterrupt:
            print(f"\n{CLR_YELLOW}Command cancelled.{CLR_RESET}")
            continue


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TubeRip YouTube downloader CLI")
    subparsers = parser.add_subparsers(dest="command", required=False)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze a video or playlist URL")
    analyze_parser.add_argument("url", help="Video or playlist URL")

    formats_parser = subparsers.add_parser("formats", help="List available formats")
    formats_parser.add_argument("url", help="Video URL")

    direct_parser = subparsers.add_parser("direct-url", help="Extract direct stream URL")
    direct_parser.add_argument("url", help="Video URL")
    direct_parser.add_argument("--format-id", help="Format ID to extract")

    download_parser = subparsers.add_parser("download", help="Download video or audio")
    download_parser.add_argument("urls", nargs="+", help="Video or playlist URLs")
    download_parser.add_argument("--mode", choices=["video", "audio"], default="video")
    download_parser.add_argument("--format-id", help="yt-dlp format selector")
    download_parser.add_argument("--output-format", help="Output file extension")
    download_parser.add_argument("--audio-bitrate", default="192k")
    download_parser.add_argument("--speed-limit", type=int, default=0)
    download_parser.add_argument("--download-dir", help="Base download directory")
    download_parser.add_argument("--profile", help="Download profile name")
    download_parser.add_argument("--playlist", action="store_true", help="Queue playlist entries individually")
    download_parser.add_argument("--interactive", "-i", action="store_true", help="Pick format interactively")
    download_parser.add_argument("--gpu", action="store_true", help="Enable hardware acceleration (NVENC/VAAPI)")

    history_parser = subparsers.add_parser("history", help="Show download history")
    history_parser.add_argument("--limit", type=int, default=20)
    history_parser.add_argument("--search", default="")
    history_parser.add_argument("--status", choices=["done", "failed", "paused", "cancelled"], default="", help="Filter history by status")

    subparsers.add_parser("analytics", help="Show advanced download analytics")
    subparsers.add_parser("stats", help="Show download statistics")
    
    settings_parser = subparsers.add_parser("settings", help="Get or set application settings")
    settings_parser.add_argument("action", choices=["get", "set", "list"], help="Action to perform")
    settings_parser.add_argument("key", nargs="?", help="Setting key")
    settings_parser.add_argument("value", nargs="?", help="Setting value for set action")

    profiles_parser = subparsers.add_parser("profiles", help="Manage download profiles")
    profiles_parser.add_argument("action", choices=["list", "add", "delete"], help="Action to perform")
    profiles_parser.add_argument("name", nargs="?", help="Profile name")
    profiles_parser.add_argument("--mode", choices=["video", "audio"], default="video")
    profiles_parser.add_argument("--output-format", default="mp4")
    profiles_parser.add_argument("--audio-bitrate", default="192k")
    profiles_parser.add_argument("--quality-label", default="bestvideo+bestaudio/best")
    profiles_parser.add_argument("--description", default="")

    config_parser = subparsers.add_parser("config", help="Get or set configuration")
    config_parser.add_argument("action", choices=["get", "set", "list"])
    config_parser.add_argument("key", nargs="?", help="Setting key")
    config_parser.add_argument("value", nargs="?", help="Setting value for set action")

    schedule_parser = subparsers.add_parser("schedule", help="Manage scheduled downloads")
    schedule_parser.add_argument("action", choices=["list", "add"])
    schedule_parser.add_argument("id", nargs="?", help="Optional schedule ID")
    schedule_parser.add_argument("url", nargs="?", help="URL to schedule")
    schedule_parser.add_argument("--when", help="Scheduled time in YYYY-MM-DD HH:MM:SS")
    schedule_parser.add_argument("--mode", choices=["video", "audio"], default="video")
    schedule_parser.add_argument("--output-format", default="mp4")
    schedule_parser.add_argument("--audio-bitrate", default="192k")
    schedule_parser.add_argument("--quality-label", default="bestvideo+bestaudio/best")
    schedule_parser.add_argument("--format-id", default="bestvideo+bestaudio/best")

    shell_parser = subparsers.add_parser("shell", help="Start interactive CLI shell")
    shell_parser.add_argument("--download-dir", help="Base download directory")
    shell_parser.add_argument("--api", action="store_true", help="Enable HTTP API listener")
    shell_parser.add_argument("--scheduler", action="store_true", help="Enable scheduler thread")

    search_parser = subparsers.add_parser("search", help="Search for videos on YouTube")
    search_parser.add_argument("query", help="Search keywords")
    search_parser.add_argument("--limit", type=int, default=10, help="Max results")

    subparsers.add_parser("resume", help="Resume interrupted downloads")
    subparsers.add_parser("monitor", help="Monitor clipboard for YouTube URLs")

    return parser


def main() -> None:
    init_db()
    parser = build_cli_parser()
    args = parser.parse_args()

    if not getattr(args, "command", None):
        args.command = "shell"

    if args.command == "analyze":
        command_analyze(args)
    elif args.command == "formats":
        command_formats(args)
    elif args.command == "direct-url":
        command_direct_url(args)
    elif args.command == "download":
        command_download(args)
    elif args.command == "history":
        command_history(args)
    elif args.command == "analytics":
        command_analytics(args)
    elif args.command == "stats":
        command_stats(args)
    elif args.command == "settings":
        command_config(args)
    elif args.command == "profiles":
        command_profiles(args)
    elif args.command == "config":
        command_config(args)
    elif args.command == "schedule":
        command_schedule(args)
    elif args.command == "search":
        command_search(args)
    elif args.command == "resume":
        command_resume(args)
    elif args.command == "monitor":
        command_monitor(args)
    elif args.command == "shell":
        command_shell(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
