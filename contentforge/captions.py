from pathlib import Path
from typing import List, Optional

from .models import Cue


FONT_SIZE = 92
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
PLAY_RES_X = 1080
SIDE_MARGIN = 90                    # safe area: keep text away from frame edges
MAX_LINE_WIDTH = PLAY_RES_X - 2 * SIDE_MARGIN  # 900 px at PlayResX 1080
MAX_LINES = 2

_font = None


def _text_width(text: str) -> float:
    """Rendered pixel width of text at FONT_SIZE (PlayResX 1080)."""
    global _font
    try:
        if _font is None:
            from PIL import ImageFont
            _font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
        return _font.getlength(text)
    except Exception:
        # Fallback heuristic: DejaVu Sans Bold is ~0.6em wide on average
        return len(text) * FONT_SIZE * 0.6

def _ass_header(margin_v: int = 620) -> str:
    """Build the ASS header with a configurable bottom margin.

    The default margin (620) is tuned for the Podcast Shorts center-crop
    layout.  The gaming layout uses a smaller margin so captions sit inside
    the gameplay panel and clear the facecam area.
    """
    return f"""[Script Info]
Title: ContentForge captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,92,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,90,90,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(seconds: float) -> str:
    """Format seconds as ASS time (h:mm:ss.cc)."""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _ass_escape(text: str) -> str:
    """Escape text for ASS dialogue lines."""
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def _split_into_phrases(cues: List[Cue]) -> List[Cue]:
    """Split cues into short captions that never exceed the 9:16 safe area.

    Wrapping is based on the actual rendered pixel width (not word count):
    each caption holds at most MAX_LINES lines, each line fits within
    MAX_LINE_WIDTH. Words are never changed; timing within a cue is
    distributed proportionally to word length (auto-VTT has no per-word timing).
    """
    phrases: List[Cue] = []
    for cue in cues:
        words = cue.text.split()
        if not words:
            continue
        duration = cue.end - cue.start

        # Greedily pack words into lines, then into captions (max 2 lines each)
        captions: List[List[str]] = []  # each caption = list of 1-2 lines
        lines: List[str] = [""]
        for word in words:
            candidate = (lines[-1] + " " + word).strip()
            if not lines[-1] or _text_width(candidate) <= MAX_LINE_WIDTH:
                lines[-1] = candidate
            elif len(lines) < MAX_LINES:
                lines.append(word)
            else:
                captions.append(lines)
                lines = [word]
        captions.append(lines)

        if len(captions) == 1:
            phrases.append(Cue(start=cue.start, end=cue.end, text="\\N".join(captions[0])))
            continue

        # Multiple captions for one cue: split timing proportionally to length
        total_chars = sum(len(" ".join(cap)) for cap in captions)
        t = cue.start
        for cap in captions:
            frac = len(" ".join(cap)) / total_chars if total_chars else 1 / len(captions)
            cap_end = min(cue.end, t + duration * frac)
            phrases.append(Cue(start=t, end=cap_end, text="\\N".join(cap)))
            t = cap_end
    return phrases


def build_ass(cues: List[Cue], clip_start: float, clip_end: float, margin_v: int = 620) -> str:
    """Build a Podcast Shorts style ASS subtitle file for the clip window.

    Timestamps are shifted so 0 = clip start.
    """
    window = [
        Cue(
            start=max(c.start, clip_start) - clip_start,
            end=min(c.end, clip_end) - clip_start,
            text=c.text,
        )
        for c in cues
        if c.end > clip_start and c.start < clip_end and c.text.strip()
    ]
    phrases = _split_into_phrases(window)

    lines = [_ass_header(margin_v)]
    for p in phrases:
        if p.end <= p.start:
            p.end = p.start + 0.4
        text = _ass_escape(p.text)
        # Safety net: a single ultra-long word can still exceed the safe width
        # (it must stay intact). Shrink it horizontally with an ASS override.
        scale = min(
            (MAX_LINE_WIDTH / _text_width(part) for part in p.text.split("\\N") if part),
            default=1.0,
        )
        if scale < 1.0:
            text = f"{{\\fscx{int(scale * 100)}}}" + text
        lines.append(
            f"Dialogue: 0,{_ass_time(p.start)},{_ass_time(p.end)},Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def write_ass(cues: List[Cue], clip_start: float, clip_end: float, path: Path, margin_v: int = 620) -> Path:
    """Write the ASS subtitle file to disk."""
    path.write_text(build_ass(cues, clip_start, clip_end, margin_v=margin_v), encoding="utf-8")
    return path
