from pathlib import Path
from typing import List, Optional

from .models import Cue


GAP_BREAK = 0.8      # close a caption at a pause this long (seconds)
READ_CPS = 15.0      # assumed reading speed: chars per second
MIN_DISPLAY = 0.7    # absolute minimum on-screen time per caption (seconds)

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


def _read_time(text: str) -> float:
    """Minimum time a caption needs to be readable (seconds)."""
    visible = text.replace("\\N", " ").replace(" ", "")
    return max(MIN_DISPLAY, len(visible) / READ_CPS)


def _words_with_timing(cues: List[Cue]) -> List[tuple]:
    """Flatten cues into (start, end, word) triples, splitting each cue's
    duration proportionally to word length (auto-VTT has no per-word timing)."""
    words = []
    for cue in cues:
        ws = cue.text.split()
        if not ws:
            continue
        duration = cue.end - cue.start
        total_chars = sum(len(w) for w in ws)
        t = cue.start
        for w in ws:
            frac = len(w) / total_chars if total_chars else 1 / len(ws)
            end = min(cue.end, t + duration * frac)
            if end <= t:
                end = t + 0.05
            words.append((t, end, w))
            t = end
    return words


def _split_into_phrases(cues: List[Cue]) -> List[Cue]:
    """Split cues into short captions that never exceed the 9:16 safe area.

    Wrapping is based on the actual rendered pixel width (not word count):
    each caption holds at most MAX_LINES lines, each line fits within
    MAX_LINE_WIDTH. Words are never changed. Captions are packed greedily
    across cue boundaries (a pause of GAP_BREAK s or longer closes the
    caption) so text stays on screen longer than raw VTT cue timing.
    """
    words = _words_with_timing(cues)
    if not words:
        return []

    phrases: List[Cue] = []
    cap_lines: List[str] = []
    cap_start = words[0][0]
    cap_end = words[0][1]

    def flush():
        nonlocal cap_lines, cap_start, cap_end
        if cap_lines:
            phrases.append(Cue(start=cap_start, end=cap_end, text="\\N".join(cap_lines)))
        cap_lines = []
        cap_start = None
        cap_end = None

    for i, (w_start, w_end, word) in enumerate(words):
        candidate = (cap_lines[-1] + " " + word).strip() if cap_lines else word
        fits_line = not cap_lines or _text_width(candidate) <= MAX_LINE_WIDTH
        full = len(cap_lines) >= MAX_LINES
        if not fits_line:
            if not full:
                cap_lines.append(word)
            else:
                flush()
                cap_lines = [word]
        else:
            if full:
                flush()
                cap_lines = [word]
            elif not cap_lines:
                cap_lines = [candidate]
            else:
                cap_lines[-1] = candidate
        if cap_start is None:
            cap_start = w_start
        cap_end = w_end

        # Close the caption at a natural pause
        if i + 1 < len(words):
            gap = words[i + 1][0] - w_end
            if gap >= GAP_BREAK:
                flush()
    flush()
    return phrases


def _enforce_read_time(phrases: List[Cue]) -> List[Cue]:
    """Stretch each caption to a minimum readable duration by borrowing time
    from the gap after it (and the gap before, if needed). Never overlaps a
    neighbour caption."""
    if not phrases:
        return phrases
    out = []
    for i, p in enumerate(phrases):
        start, end = p.start, p.end
        need = _read_time(p.text)
        if end - start >= need:
            out.append(p)
            continue
        # Borrow from the gap after this caption
        nxt = phrases[i + 1] if i + 1 < len(phrases) else None
        prev = out[-1] if out else None
        limit = nxt.start if nxt else end + 10.0
        end2 = min(max(end, start + need), limit)
        # Still short? borrow from the gap before (pull start earlier)
        if end2 - start < need and prev is not None:
            start = max(prev.end, start - (need - (end2 - start)))
        out.append(Cue(start=start, end=max(end2, start + 0.05), text=p.text))
    # Second pass for the few captions that got shortened by a neighbour
    for i in range(len(out) - 1):
        if out[i].end > out[i + 1].start:
            out[i] = Cue(start=out[i].start, end=out[i + 1].start, text=out[i].text)
    return out


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
    phrases = _enforce_read_time(_split_into_phrases(window))

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
