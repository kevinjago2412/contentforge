import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import yt_dlp

from .downloader import _extract_video_id, _cookies_opts

FORMAT_SELECTOR = (
    "bv*[height<=1080][ext=mp4]+ba[ext=m4a]"
    "/bv*[height<=1080]+ba/b[height<=1080]/b"
)


def sanitize_slug(text: str, max_len: int = 40) -> str:
    """Make a filesystem-safe slug from arbitrary text."""
    slug = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").lower()
    return slug[:max_len].strip("_") or "clip"


def _get_stream_urls(url: str) -> tuple[str, Optional[str]]:
    """Resolve direct stream URLs (video, audio) without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": FORMAT_SELECTOR,
        **_cookies_opts(),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise ValueError("Could not extract video info")

    requested = info.get("requested_formats")
    if requested:
        video_url = requested[0]["url"]
        audio_url = requested[1]["url"] if len(requested) > 1 else None
        return video_url, audio_url
    return info["url"], None


def download_section(
    url: str,
    start: float,
    end: float,
    pad: float = 2.0,
    output_dir: Optional[Path] = None,
) -> tuple[Path, float]:
    """Fetch only the [start-pad, end+pad] section of a video.

    Uses ffmpeg HTTP range-seeking on the direct stream URLs, so only the
    needed seconds are transferred (not the whole video).
    Returns (path to the section file, actual padded start time).
    """
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="contentforge_vid_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    video_id = _extract_video_id(url)
    padded_start = max(0.0, start - pad)
    padded_end = end + pad

    video_url, audio_url = _get_stream_urls(url)
    out_path = output_dir / f"{video_id}_{int(padded_start)}-{int(padded_end)}.mp4"

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    seek_args = [
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-ss", f"{padded_start:.3f}", "-to", f"{padded_end:.3f}",
    ]
    cmd += seek_args + ["-i", video_url]
    if audio_url:
        cmd += seek_args + ["-i", audio_url]
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c", "copy", "-movflags", "+faststart", str(out_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out_path.exists():
        raise RuntimeError(f"ffmpeg section fetch failed: {result.stderr.strip()[:500]}")

    return out_path, padded_start
