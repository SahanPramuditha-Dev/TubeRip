import argparse

import pytest

import cli
from models.job import DownloadMode, VideoMetadata


def test_choose_format_defaults_video():
    assert cli.choose_format(None, DownloadMode.VIDEO) == "bestvideo+bestaudio/best"


def test_choose_format_audio_mode():
    assert cli.choose_format(None, DownloadMode.AUDIO) == "bestaudio/best"


def test_smart_recommend_format_prefers_1080p():
    metadata = VideoMetadata(
        title="Demo",
        formats=[
            {"format_id": "144", "resolution": 144, "type": "video"},
            {"format_id": "1080", "resolution": 1080, "type": "video"},
            {"format_id": "720", "resolution": 720, "type": "video"},
        ],
    )

    assert cli.smart_recommend_format(metadata) == "1080"


def test_cli_parser_includes_shell():
    parser = cli.build_cli_parser()
    args = parser.parse_args(["shell"])
    assert args.command == "shell"


def test_history_parser_supports_status_filter():
    parser = cli.build_cli_parser()
    args = parser.parse_args(["history", "--status", "failed"])
    assert args.command == "history"
    assert args.status == "failed"


def test_settings_parser_alias():
    parser = cli.build_cli_parser()
    args = parser.parse_args(["settings", "set", "download_dir", "C:/Temp"])
    assert args.command == "settings"
    assert args.action == "set"
    assert args.key == "download_dir"
    assert args.value == "C:/Temp"


def test_build_job_detects_audio_only_format():
    args = argparse.Namespace(
        mode="video",
        output_format="mp4",
        audio_bitrate="192k",
        format_id="140",
        profile=None,
        speed_limit=0,
        gpu=False,
    )
    metadata = VideoMetadata(
        title="Audio Only",
        formats=[{"format_id": "140", "type": "audio", "ext": "m4a"}],
    )

    job = cli.build_job(args, "https://youtu.be/test", metadata=metadata)
    assert job.mode == DownloadMode.AUDIO
    assert job.output_format == "m4a"
    assert job.format_id == "140"
