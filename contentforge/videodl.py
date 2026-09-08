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


# Headers googlevideo expects from a real browser; without these, direct
# ffmpeg access from datacenter IPs (e.g. GitHub Actions runners) gets 403.
FFMPEG_HTTP_ARGS = [
    "-user_agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "-referer", "https://www.youtube.com/",
]


def download_section(
    url: str,
    start: float,
    end: float,
    pad: float = 2.0,
    output_dir: Optional[Path] = None,
) -> tuple[Path, float]:
    """Fetch only the [start-pad, end+pad] section of a video.

    Uses yt-dlp's native download_ranges so all auth/headers/PO-token handling
    is done by yt-dlp itself — direct ffmpeg access to googlevideo URLs gets
    403 Forbidden on datacenter IPs (e.g. GitHub Actions runners).
    Returns (path to the section file, actual padded start time).
    """
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="contentforge_vid_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    video_id = _extract_video_id(url)
    padded_start = max(0.0, start - pad)
    padded_end = end + pad

    out_path = output_dir / f"{video_id}_{int(padded_start)}-{int(padded_end)}.mp4"
    if out_path.exists():
        return out_path, padded_start

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": FORMAT_SELECTOR,
        "download_ranges": lambda _, __: [{"start_time": padded_start, "end_time": padded_end}],
        "outtmpl": str(out_path.parent / (out_path.stem + ".%(ext)s")),
        **_cookies_opts(),
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    # yt-dlp may pick a different container than .mp4
    if not out_path.exists():
        candidates = list(out_path.parent.glob(out_path.stem + ".*"))
        if not candidates:
            raise RuntimeError(f"yt-dlp section download produced no file for {out_path.stem}")
        out_path = candidates[0]

    return out_path, padded_start
