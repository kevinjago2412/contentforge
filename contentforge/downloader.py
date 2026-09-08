import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import yt_dlp


# Priority order for subtitle languages (Indonesian first, then common fallbacks)
LANG_PRIORITY = ["id", "en", "ms", "auto"]


def _cookies_opts() -> dict:
    """Extra yt-dlp options for cookie + JS-runtime support.

    Env vars:
    - CONTENTFORGE_COOKIES: Netscape cookies.txt path or
      "from-browser:BROWSER[:PROFILE]" (e.g. from-browser:brave).
    - CONTENTFORGE_JS_RUNTIME: "node" (default if empty when cookies are set),
      "deno", "quickjs", or "none" to disable. YouTube's n-challenge needs a
      JS runtime; without it formats are missing / requests get blocked.
    - CONTENTFORGE_REMOTE_COMPONENTS: comma-separated yt-dlp remote components
      (default "ejs:github" when a JS runtime is enabled).
    """
    opts: dict = {}

    val = os.getenv("CONTENTFORGE_COOKIES", "").strip()
    if val.startswith("from-browser:"):
        opts["cookiefile"] = None
        opts["cookiesfrombrowser"] = tuple(val.split(":", 2)[1:])
    elif val:
        opts["cookiefile"] = val

    js = os.getenv("CONTENTFORGE_JS_RUNTIME", "").strip().lower()
    if not js and val:
        js = "node"  # sane default: node is the most widely available runtime
    if js and js != "none":
        opts["js_runtimes"] = {js: {}}
        comps = os.getenv("CONTENTFORGE_REMOTE_COMPONENTS", "ejs:github").strip()
        if comps:
            opts["remote_components"] = [c.strip() for c in comps.split(",") if c.strip()]

    return opts


def _extract_video_id(url: str) -> str:
    """Extract a normalized video id from a YouTube URL."""
    patterns = [
        r"(?:v=|/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be/([0-9A-Za-z_-]{11})",
        r"youtube\.com/shorts/([0-9A-Za-z_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return "unknown"


def _pick_best_subtitle(subs: dict, auto_subs: dict, preferred: str = "id") -> tuple[str, bool]:
    """Choose the best available subtitle track.

    Returns (lang_code, is_auto_generated).
    """
    # Direct subtitle available in preferred language
    if preferred in subs:
        return preferred, False

    # Auto-generated subtitle available in preferred language
    if preferred in auto_subs:
        return preferred, True

    # Try fallbacks
    for lang in LANG_PRIORITY:
        if lang == preferred:
            continue
        if lang in subs:
            return lang, False
        if lang in auto_subs:
            return lang, True

    # Fallback: pick any available subtitle
    if subs:
        return next(iter(subs)), False
    if auto_subs:
        return next(iter(auto_subs)), True

    raise ValueError("No subtitles available for this video")


def download_subtitle(
    url: str,
    preferred_lang: str = "id",
    output_dir: Optional[Path] = None,
) -> tuple[Path, dict]:
    """Download automatic/manual subtitles using yt-dlp.

    Returns the path to the saved .vtt file and the video info dict.
    """
    output_dir = output_dir or Path(tempfile.mkdtemp(prefix="contentforge_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    video_id = _extract_video_id(url)
    outtmpl = str(output_dir / f"{video_id}.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitlesformat": "vtt",
        "subtitleslangs": [preferred_lang] + [l for l in LANG_PRIORITY if l != preferred_lang and l != "auto"],
        "skip_download": True,
        "outtmpl": outtmpl,
        **_cookies_opts(),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ValueError("Could not extract video info")

        subs = info.get("subtitles", {}) or {}
        auto_subs = info.get("automatic_captions", {}) or {}

        lang, is_auto = _pick_best_subtitle(subs, auto_subs, preferred_lang)

        # Reconfigure to download only the chosen language
        ydl.params["subtitleslangs"] = [lang]
        ydl.download([url])

    expected_file = output_dir / f"{video_id}.{lang}.vtt"
    if not expected_file.exists():
        # yt-dlp sometimes names auto subs with locale suffix, e.g. id-ID
        for f in output_dir.glob(f"{video_id}*.vtt"):
            return f, info
        raise FileNotFoundError(f"Expected subtitle file not found: {expected_file}")

    return expected_file, info
