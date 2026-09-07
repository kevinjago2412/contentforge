"""Vertical layout definitions for ContentForge clipping.

A *layout* describes how a landscape source video should be composed into a
9:16 (1080x1920) output.  The default layout center-crops the source.  The
``gaming`` layout builds a vertical composition with a facecam panel on top
and a gameplay panel below.

All source regions are stored as normalized ``Region`` values (0.0-1.0) so
they remain valid across different source resolutions.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass(frozen=True)
class Region:
    """A normalized rectangle: x, y, width, height in 0.0-1.0 coordinates."""

    x: float
    y: float
    w: float
    h: float

    def to_pixels(self, width: int, height: int) -> Tuple[int, int, int, int]:
        """Convert to integer pixel coordinates for a video of given size."""
        x = int(round(self.x * width))
        y = int(round(self.y * height))
        w = int(round(self.w * width))
        h = int(round(self.h * height))
        return x, y, w, h

    @staticmethod
    def from_string(value: str) -> "Region":
        """Parse a CLI value like ``0.1,0.2,0.3,0.4``."""
        parts = [float(p.strip()) for p in value.split(",")]
        if len(parts) != 4:
            raise ValueError("Region must be 'x,y,w,h' in normalized coordinates")
        return Region(*parts)

    @staticmethod
    def full() -> "Region":
        return Region(0.0, 0.0, 1.0, 1.0)


@dataclass(frozen=True)
class Layout:
    """Complete description of a vertical composition."""

    name: str
    output_width: int
    output_height: int
    facecam_target: Region   # area inside the 1080x1920 output
    gameplay_target: Region  # area inside the 1080x1920 output
    facecam_source: Optional[Region]   # crop from the source (or None for default)
    gameplay_source: Optional[Region]  # crop from the source (or None for default)
    subtitle_margin_v: int   # ASS bottom margin for this layout


def get_video_dimensions(path: Path) -> Tuple[int, int]:
    """Return (width, height) of the first video stream using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    width, height = result.stdout.strip().split("x")
    return int(width), int(height)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def default_layout(subtitle_margin_v: int = 620) -> Layout:
    """The original Podcast Shorts layout: center-crop to 9:16."""
    return Layout(
        name="default",
        output_width=1080,
        output_height=1920,
        facecam_target=Region.full(),
        gameplay_target=Region.full(),
        facecam_source=None,
        gameplay_source=None,
        subtitle_margin_v=subtitle_margin_v,
    )


def _auto_gameplay_region(
    source_w: int,
    source_h: int,
    facecam_source: Optional[Region],
    target_aspect: float,
    focus: float,
) -> Region:
    """Pick a vertical-ish gameplay crop that avoids the facecam overlay.

    ``target_aspect`` is width/height of the gameplay panel.  ``focus`` is a
    value in [0, 1] controlling the horizontal center of the crop (0 = left,
    1 = right).  The crop is clamped to the source frame and shifted away from
    the facecam region if they overlap.
    """
    crop_h = source_h
    crop_w = int(round(target_aspect * source_h))
    if crop_w > source_w:
        # Very wide source: fit width and letterbox/pillarbox later.
        crop_w = source_w
        crop_h = int(round(source_w / target_aspect))

    x_center = int(round(_clamp(focus, 0.0, 1.0) * source_w))
    x = x_center - crop_w // 2

    if facecam_source:
        fx, fy, fw, fh = facecam_source.to_pixels(source_w, source_h)
        # Shift horizontally if the gameplay crop would intersect the facecam.
        if x < fx + fw and x + crop_w > fx:
            room_right = source_w - (fx + fw)
            room_left = fx
            if room_right >= room_left:
                x = fx + fw
            else:
                x = max(0, fx - crop_w)

    x = max(0, min(source_w - crop_w, x))
    y = max(0, (source_h - crop_h) // 2)
    return Region(x / source_w, y / source_h, crop_w / source_w, crop_h / source_h)


def gaming_layout(
    source_w: int,
    source_h: int,
    facecam_source: Optional[Region] = None,
    gameplay_source: Optional[Region] = None,
    gameplay_focus: float = 0.5,
    subtitle_margin_v: int = 250,
) -> Layout:
    """Build a gaming vertical layout for a source of the given size.

    The output is split into:
      - facecam panel: top 37.5%  (720px of 1920)
      - gameplay panel: bottom 62.5% (1200px of 1920)

    Source regions are normalized and computed relative to the source so the
    same settings work for 720p, 1080p, etc.
    """
    facecam_h = 0.375   # 720 / 1920
    gameplay_h = 0.625  # 1200 / 1920

    facecam_target = Region(0.0, 0.0, 1.0, facecam_h)
    gameplay_target = Region(0.0, facecam_h, 1.0, gameplay_h)

    # Aspect ratio of the gameplay panel inside the 1080x1920 canvas.
    target_aspect = (gameplay_target.w * 1080) / (gameplay_target.h * 1920)

    if gameplay_source is None:
        gameplay_source = _auto_gameplay_region(
            source_w, source_h, facecam_source, target_aspect, gameplay_focus
        )

    return Layout(
        name="gaming",
        output_width=1080,
        output_height=1920,
        facecam_target=facecam_target,
        gameplay_target=gameplay_target,
        facecam_source=facecam_source,
        gameplay_source=gameplay_source,
        subtitle_margin_v=subtitle_margin_v,
    )


def scale_crop_filter(
    src_x: int,
    src_y: int,
    src_w: int,
    src_h: int,
    target_w: int,
    target_h: int,
) -> str:
    """FFmpeg filter: crop a source region then scale+fill a target box.

    The source region is scaled to completely fill ``target_w x target_h``
    while preserving its aspect ratio; any overflow is cropped equally from
    both sides.  This avoids stretching/distorting the facecam or gameplay.
    """
    return (
        f"crop={src_w}:{src_h}:{src_x}:{src_y},"
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2"
    )
