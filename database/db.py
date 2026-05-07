"""
TubeRip — SQLite database layer.
Manages: history, resume_state, stats, profiles, scheduler, settings.
"""
import sqlite3
import time
from typing import List, Optional
from pathlib import Path

DB_PATH = Path.home() / ".tuberip" / "downloads.db"


def get_connection() -> sqlite3.Connection:
    db_path = _resolve_writable_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _resolve_writable_db_path() -> Path:
    primary = DB_PATH
    fallback = Path.cwd() / ".tuberip" / "downloads.db"
    for candidate in (primary, fallback):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        try:
            with candidate.open("a", encoding="utf-8"):
                pass
            return candidate
        except OSError:
            continue
    return fallback


def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Core tables
    c.executescript("""
        CREATE TABLE IF NOT EXISTS history (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            thumbnail_url TEXT,
            channel TEXT,
            duration INTEGER,
            views INTEGER,
            upload_date TEXT,
            video_id TEXT,
            mode TEXT,
            output_format TEXT,
            quality_label TEXT,
            output_path TEXT,
            total_bytes INTEGER DEFAULT 0,
            avg_speed_bps REAL DEFAULT 0,
            status TEXT DEFAULT 'done',
            error_msg TEXT,
            created_at REAL,
            finished_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_history_finished_at
            ON history (finished_at DESC);
        CREATE INDEX IF NOT EXISTS idx_history_status
            ON history (status);

        CREATE TABLE IF NOT EXISTS resume_state (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            mode TEXT,
            output_format TEXT,
            audio_bitrate TEXT,
            quality_label TEXT,
            format_id TEXT,
            temp_path TEXT,
            metadata_json TEXT,
            created_at REAL
        );

        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS profiles (
            name TEXT PRIMARY KEY,
            mode TEXT,
            output_format TEXT,
            audio_bitrate TEXT,
            quality_label TEXT,
            description TEXT,
            created_at REAL DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            channel_id TEXT PRIMARY KEY,
            name TEXT,
            url TEXT,
            last_checked REAL,
            auto_download INTEGER DEFAULT 0,
            created_at REAL
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS scheduler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            mode TEXT,
            output_format TEXT,
            audio_bitrate TEXT,
            quality_label TEXT,
            format_id TEXT,
            scheduled_at REAL,
            status TEXT DEFAULT 'pending'
        );
    """)

    # Migration: Add missing columns to resume_state
    for col, definition in [("downloaded_bytes", "INTEGER DEFAULT 0"), 
                            ("total_bytes", "INTEGER DEFAULT 0"),
                            ("metadata_json", "TEXT")]:
        try:
            c.execute(f"SELECT {col} FROM resume_state LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(f"ALTER TABLE resume_state ADD COLUMN {col} {definition}")

    # Migrations
    for table, col, definition in [("history", "avg_speed_bps", "REAL DEFAULT 0"), 
                                   ("profiles", "created_at", "REAL DEFAULT 0"),
                                   ("subscriptions", "created_at", "REAL DEFAULT 0"),
                                   ("scheduler", "created_at", "REAL DEFAULT 0")]:
        try:
            c.execute(f"SELECT {col} FROM {table} LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

    # Default profiles
    c.executemany("""
        INSERT OR IGNORE INTO profiles (name, mode, output_format, audio_bitrate, quality_label, description)
        VALUES (?,?,?,?,?,?)
    """, [
        ("Best Quality",  "video", "mkv", "320k", "bestvideo+bestaudio", "Highest resolution + audio, MKV container"),
        ("1080p MP4",     "video", "mp4", "192k", "137+140",             "Full HD, web-compatible MP4"),
        ("720p Balanced", "video", "mp4", "192k", "22",                  "Good quality, smaller file"),
        ("Music / MP3",   "audio", "mp3", "320k", "bestaudio",           "High-quality MP3 audio only"),
        ("Podcast / AAC", "audio", "m4a", "128k", "bestaudio",           "Efficient AAC for speech"),
    ])

    # Default settings
    c.executemany("""
        INSERT OR IGNORE INTO app_settings (key, value) VALUES (?,?)
    """, [
        ("max_concurrent", "3"),
        ("speed_limit_kbps", "0"),
        ("download_dir", str(Path.home() / "Downloads" / "TubeRip")),
        ("clipboard_monitor", "1"),
        ("theme", "dark"),
        ("notify_on_complete", "1"),
    ])

    conn.commit()
    conn.close()


# ── History ────────────────────────────────────────────────────────────────

def save_history(job) -> None:
    conn = get_connection()
    m = job.metadata
    elapsed = job.elapsed or 1
    avg_speed = (job.total_bytes / elapsed) if job.total_bytes and elapsed > 0 else 0
    conn.execute("""
        INSERT OR REPLACE INTO history
        (id, url, title, thumbnail_url, channel, duration, views, upload_date,
         video_id, mode, output_format, quality_label, output_path, total_bytes,
         avg_speed_bps, status, error_msg, created_at, finished_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        job.id, job.url, m.title, m.thumbnail_url, m.channel, m.duration,
        m.views, m.upload_date, m.video_id, job.mode.value, job.output_format,
        job.quality_label, job.output_path, job.total_bytes, avg_speed,
        job.status.value, job.error_msg, job.created_at, job.finished_at
    ))
    conn.commit()
    conn.close()


def get_history(limit: int = 200, search: str = "", status_filter: str = "") -> List[dict]:
    conn = get_connection()
    query = "SELECT * FROM history WHERE 1=1"
    params = []
    if search:
        query += " AND (title LIKE ? OR channel LIKE ? OR url LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s])
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
    query += " ORDER BY finished_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_history():
    conn = get_connection()
    conn.execute("DELETE FROM history")
    conn.commit()
    conn.close()


def delete_history_item(item_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def is_duplicate_url(url: str) -> Optional[dict]:
    """Check if a URL was already successfully downloaded."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM history WHERE url=? AND status='done' ORDER BY finished_at DESC LIMIT 1",
        (url,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Stats ──────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    conn = get_connection()
    agg = conn.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(total_bytes), 0) as tb, "
        "COALESCE(AVG(avg_speed_bps), 0) as avg_spd "
        "FROM history WHERE status='done'"
    ).fetchone()
    avg_dur = conn.execute(
        "SELECT COALESCE(AVG(duration), 0) as avg_dur "
        "FROM history WHERE status='done'"
    ).fetchone()
    total_rows = conn.execute("SELECT COUNT(*) as cnt FROM history").fetchone()
    fmt_rows = conn.execute(
        "SELECT output_format, COUNT(*) as cnt "
        "FROM history WHERE status='done' "
        "GROUP BY output_format ORDER BY cnt DESC"
    ).fetchall()
    status_rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM history "
        "GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    mode_rows = conn.execute(
        "SELECT mode, COUNT(*) as cnt FROM history "
        "GROUP BY mode ORDER BY cnt DESC"
    ).fetchall()
    quality_rows = conn.execute(
        "SELECT quality_label, COUNT(*) as cnt FROM history "
        "WHERE status='done' GROUP BY quality_label ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    daily = conn.execute(
        "SELECT date(finished_at, 'unixepoch') as day, COUNT(*) as cnt, "
        "COALESCE(SUM(total_bytes),0) as bytes "
        "FROM history WHERE status='done' "
        "AND finished_at > ? "
        "GROUP BY day ORDER BY day",
        (time.time() - 7 * 86400,)
    ).fetchall()
    channels = conn.execute(
        "SELECT channel, COUNT(*) as cnt FROM history "
        "WHERE status='done' AND channel != '' "
        "GROUP BY channel ORDER BY cnt DESC LIMIT 10"
    ).fetchall()
    conn.close()
    total_count = total_rows["cnt"] if total_rows else 0
    return {
        "total_downloads": agg["cnt"],
        "total_bytes":     agg["tb"],
        "avg_speed_bps":   agg["avg_spd"],
        "avg_duration":    avg_dur["avg_dur"],
        "success_rate":    (agg["cnt"] / total_count * 100) if total_count else 0.0,
        "formats":         {r["output_format"] or "?": r["cnt"] for r in fmt_rows},
        "status_counts":   [dict(r) for r in status_rows],
        "mode_counts":     [dict(r) for r in mode_rows],
        "quality_labels":  [dict(r) for r in quality_rows],
        "daily":           [dict(r) for r in daily],
        "channels":        [dict(r) for r in channels],
    }


# ── Profiles ───────────────────────────────────────────────────────────────

def get_profiles() -> List[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM profiles ORDER BY created_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_profile(name: str, mode: str, output_format: str,
                 audio_bitrate: str, quality_label: str, description: str = ""):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO profiles
        (name, mode, output_format, audio_bitrate, quality_label, description, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (name, mode, output_format, audio_bitrate, quality_label, description, time.time()))
    conn.commit()
    conn.close()


def delete_profile(name: str):
    conn = get_connection()
    conn.execute("DELETE FROM profiles WHERE name=?", (name,))
    conn.commit()
    conn.close()


# ── Resume State ───────────────────────────────────────────────────────────

def save_resume_state(job) -> None:
    import json
    conn = get_connection()
    meta_json = json.dumps({
        "title": job.metadata.title,
        "thumbnail_url": job.metadata.thumbnail_url,
        "channel": job.metadata.channel,
        "duration": job.metadata.duration,
    })
    conn.execute("""
        INSERT OR REPLACE INTO resume_state
        (id, url, mode, output_format, audio_bitrate, quality_label, format_id,
         downloaded_bytes, total_bytes, temp_path, metadata_json, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        job.id, job.url, job.mode.value, job.output_format, job.audio_bitrate,
        job.quality_label, job.format_id, job.downloaded_bytes, job.total_bytes,
        job.output_path, meta_json, job.created_at
    ))
    conn.commit()
    conn.close()


def get_resume_states() -> List[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM resume_state ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_resume_state(job_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM resume_state WHERE id=?", (job_id,))
    conn.commit()
    conn.close()


# ── Scheduler ──────────────────────────────────────────────────────────────

def save_scheduled_job(job_id: str, url: str, mode: str, output_format: str,
                        audio_bitrate: str, quality_label: str, format_id: str,
                        scheduled_at: float):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO scheduler
        (id, url, mode, output_format, audio_bitrate, quality_label, format_id,
         scheduled_at, status, created_at)
        VALUES (?,?,?,?,?,?,?,?,'pending',?)
    """, (job_id, url, mode, output_format, audio_bitrate, quality_label,
          format_id, scheduled_at, time.time()))
    conn.commit()
    conn.close()


def get_pending_scheduled_jobs() -> List[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scheduler WHERE status='pending' AND scheduled_at <= ? ORDER BY scheduled_at",
        (time.time(),)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_scheduled_done(job_id: str):
    conn = get_connection()
    conn.execute("UPDATE scheduler SET status='done' WHERE id=?", (job_id,))
    conn.commit()
    conn.close()


def get_all_scheduled() -> List[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM scheduler ORDER BY scheduled_at").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── App Settings ───────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


# ── Subscriptions ──────────────────────────────────────────────────────────

def add_subscription(channel_id: str, name: str, url: str, auto: bool = False):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO subscriptions (channel_id, name, url, last_checked, auto_download, created_at)
        VALUES (?,?,?,?,?,?)
    """, (channel_id, name, url, time.time(), 1 if auto else 0, time.time()))
    conn.commit()
    conn.close()

def get_subscriptions() -> List[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM subscriptions ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_subscription(channel_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM subscriptions WHERE channel_id=?", (channel_id,))
    conn.commit()
    conn.close()

# ── Misc ───────────────────────────────────────────────────────────────────

def update_stats_key(key: str, value: str):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO stats VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()
