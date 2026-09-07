import re
from pathlib import Path
from typing import List

from .models import Cue


def _parse_timestamp(ts: str) -> float:
    """Parse a VTT/WebVTT timestamp into total seconds."""
    ts = ts.strip().replace("\ufeff", "")
    # Accept formats like: 00:01:02.000, 01:02.000, 1:02.000
    parts = ts.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    elif len(parts) == 1:
        return float(parts[0])
    raise ValueError(f"Unrecognized timestamp format: {ts!r}")


def _clean_text(text: str) -> str:
    """Remove VTT tags, HTML tags, normalize whitespace."""
    # Remove <v Speaker> tags and other WebVTT cue tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_vtt(vtt_content: str) -> List[Cue]:
    """Parse WebVTT content into a list of Cue objects."""
    cues: List[Cue] = []
    lines = vtt_content.splitlines()

    # Skip WebVTT header and any NOTE/STYLE blocks
    i = 0
    while i < len(lines) and (
        lines[i].strip() == "" or lines[i].startswith("WEBVTT") or lines[i].startswith("NOTE") or lines[i].startswith("STYLE")
    ):
        i += 1
        if i < len(lines) and lines[i - 1].startswith("NOTE"):
            while i < len(lines) and lines[i].strip() != "":
                i += 1
        if i < len(lines) and lines[i - 1].startswith("STYLE"):
            while i < len(lines) and lines[i].strip() != "":
                i += 1

    current_start: float | None = None
    current_end: float | None = None
    text_lines: List[str] = []

    def flush() -> None:
        nonlocal current_start, current_end, text_lines
        if current_start is not None and current_end is not None and text_lines:
            full_text = _clean_text(" ".join(text_lines))
            if full_text:
                cues.append(
                    Cue(start=current_start, end=current_end, text=full_text)
                )
        current_start = None
        current_end = None
        text_lines = []

    while i < len(lines):
        line = lines[i]
        # Timestamp line: 00:00:01.000 --> 00:00:04.000 [optional settings]
        arrow_match = re.match(
            r"([\d:.]+)\s*-->\s*([\d:.]+)", line
        )
        if arrow_match:
            flush()
            current_start = _parse_timestamp(arrow_match.group(1))
            current_end = _parse_timestamp(arrow_match.group(2))
        elif current_start is not None and line.strip() != "":
            text_lines.append(line.strip())
        elif line.strip() == "" and current_start is not None:
            flush()
        i += 1

    flush()

    # Merge cues that have the exact same timestamps to avoid duplicates from duplicate VTT lines
    merged: List[Cue] = []
    for cue in cues:
        if merged and merged[-1].start == cue.start and merged[-1].end == cue.end:
            merged[-1].text = _clean_text(merged[-1].text + " " + cue.text)
        else:
            merged.append(cue)

    return merged


def parse_vtt_file(path: str | Path) -> List[Cue]:
    """Parse a VTT file from disk."""
    path = Path(path)
    return parse_vtt(path.read_text(encoding="utf-8"))
