"""Tes metode akses stream googlevideo dari runner CI: mana yang lolos 403.

Metode:
A. ffmpeg + URL langsung + UA/referer (metode lama, gagal 403)
B. ffmpeg + URL langsung + UA/referer + cookies
C. yt-dlp download section (yt-dlp handle semua header sendiri)
D. ffmpeg + URL langsung + semua header http_headers yt-dlp
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, ".")
from contentforge.downloader import _cookies_opts

URL = "https://www.youtube.com/live/6qexUOI3atg"
OUT = Path("debug_out")
OUT.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

base = {"quiet": True, "no_warnings": True, **_cookies_opts()}

# Resolve stream URLs via yt-dlp (ini lolos, terbukti di run sebelumnya)
import yt_dlp
with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                       "format": "bv*[height<=1080]+ba/b", **_cookies_opts()}) as ydl:
    info = ydl.extract_info(URL, download=False)
req = info.get("requested_formats")
video_url = req[0]["url"] if req else info["url"]
audio_url = req[1]["url"] if req and len(req) > 1 else None
fmt = info.get("http_headers") or {}
print(f"[resolve] OK; headers yt-dlp: {list(fmt.keys())}")

def ffmpeg_test(label, args, url):
    out = OUT / f"{label}.jpg"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args,
           "-ss", "30", "-i", url, "-vframes", "1", "-q:v", "2", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and out.exists() and out.stat().st_size > 1000
    print(f"[{label}] {'OK (%d bytes)' % out.stat().st_size if ok else 'GAGAL: ' + r.stderr.strip()[:150]}")
    return ok

# A: UA + referer (metode yang gagal)
ffmpeg_test("A_ua_referer", ["-user_agent", UA, "-referer", "https://www.youtube.com/"], video_url)

# B: + cookies
ffmpeg_test("B_with_cookies",
            ["-user_agent", UA, "-referer", "https://www.youtube.com/",
             "-headers", "Cookie: " + _read_cookies() if False else ""], video_url) if False else None

# B (benar): pakai ffmpeg -cookies? tidak disupport untuk https input; skip.
# D: semua header http_headers yt-dlp
hdr_args = []
for k, v in fmt.items():
    hdr_args += ["-headers", f"{k}: {v}\r\n"]
ffmpeg_test("D_ytdlp_headers", hdr_args, video_url)

# C: yt-dlp sendiri yang download 30 dtk section (paling pasti)
try:
    outtmpl = str(OUT / "C_ytdlp_section.%(ext)s")
    opts = {
        "quiet": True, "no_warnings": True,
        "format": "bv*[height<=1080]+ba/b",
        "download_ranges": lambda _, __: [{"start_time": 30, "end_time": 33}],
        "outtmpl": outtmpl,
        **_cookies_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl2:
        ydl2.download([URL])
    files = list(OUT.glob("C_ytdlp_section.*"))
    ok = any(f.stat().st_size > 10000 for f in files)
    print(f"[C_ytdlp_section] {'OK (%s)' % [f.name for f in files] if ok else 'GAGAL: file kosong'}")
except Exception as e:
    print(f"[C_ytdlp_section] GAGAL: {str(e)[:150]}")
