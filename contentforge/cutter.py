import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from .captions import write_ass
from .facecam import detect_facecam_region
from .layout import (
    Layout,
    Region,
    default_layout,
    gaming_layout,
    get_video_dimensions,
    scale_crop_filter,
)
from .models import Cue
from .videodl import download_section, sanitize_slug


def _has_subtitles_filter() -> bool:
    """Check whether the local ffmpeg build has libass (subtitles filter)."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True, check=True,
        ).stdout
        return " subtitles " in out
    except Exception:
        return False


def _default_filters(with_subtitles: bool, cues: List[Cue], start: float, end: float,
                     layout: Layout, work_dir: Path) -> tuple[List[str], Optional[Path]]:
    """Build the simple `-vf` filter list used by the default layout."""
    filters = ["crop=ih*9/16:ih", "scale=1080:1920"]
    ass_path: Optional[Path] = None
    if with_subtitles and cues:
        if _has_subtitles_filter():
            ass_path = work_dir / "cap.ass"
            write_ass(cues, start, end, ass_path, margin_v=layout.subtitle_margin_v)
            filters.append("subtitles=cap.ass")
        else:
            print("      warning: ffmpeg has no subtitles filter, clipping without burned captions")
    return filters, ass_path


def _gaming_filter_complex(
    layout: Layout,
    source_w: int,
    source_h: int,
    with_subtitles: bool,
    cues: List[Cue],
    start: float,
    end: float,
    work_dir: Path,
) -> tuple[str, str]:
    """Build a filter_complex that stacks facecam + gameplay for the gaming layout.

    Returns ``(filter_complex_string, output_label)``.
    """
    assert layout.facecam_source is not None
    assert layout.gameplay_source is not None

    fc_tx, fc_ty, fc_tw, fc_th = layout.facecam_target.to_pixels(
        layout.output_width, layout.output_height
    )
    gp_tx, gp_ty, gp_tw, gp_th = layout.gameplay_target.to_pixels(
        layout.output_width, layout.output_height
    )

    fc_sx, fc_sy, fc_sw, fc_sh = layout.facecam_source.to_pixels(source_w, source_h)
    gp_sx, gp_sy, gp_sw, gp_sh = layout.gameplay_source.to_pixels(source_w, source_h)

    fc_filter = scale_crop_filter(fc_sx, fc_sy, fc_sw, fc_sh, fc_tw, fc_th)
    gp_filter = scale_crop_filter(gp_sx, gp_sy, gp_sw, gp_sh, gp_tw, gp_th)

    filter_complex = (
        f"[0:v]split=2[fc_in][gp_in];"
        f"[fc_in]{fc_filter}[fc];"
        f"[gp_in]{gp_filter}[gp];"
        f"[fc][gp]vstack=inputs=2[stack]"
    )
    output_label = "[stack]"

    if with_subtitles and cues:
        if _has_subtitles_filter():
            ass_path = work_dir / "cap.ass"
            write_ass(cues, start, end, ass_path, margin_v=layout.subtitle_margin_v)
            filter_complex += f";[stack]subtitles={ass_path.name}[v]"
            output_label = "[v]"
        else:
            print("      warning: ffmpeg has no subtitles filter, clipping without burned captions")

    return filter_complex, output_label


def cut_clip(
    url: str,
    start: float,
    end: float,
    cues: List[Cue],
    output_path: Path,
    pad: float = 2.0,
    with_subtitles: bool = False,
    layout: str = "default",
    facecam_region: Optional[Region] = None,
    gameplay_region: Optional[Region] = None,
    gameplay_focus: float = 0.5,
    subtitle_margin_v: Optional[int] = None,
) -> Path:
    """Cut a [start, end] clip from a YouTube video into a 9:16 MP4.

    Supports two layouts:
      * ``default``  -- center-crop the source to 1080x1920.
      * ``gaming``   -- vertical composition with facecam on top and gameplay
        below.

    Returns the path to the produced MP4.
    """
    work_dir = Path(tempfile.mkdtemp(prefix="contentforge_cut_"))
    try:
        section_path, padded_start = download_section(
            url, start, end, pad=pad, output_dir=work_dir
        )
        offset = start - padded_start  # where the real clip starts inside the section file
        duration = end - start

        output_path.parent.mkdir(parents=True, exist_ok=True)

        if layout == "gaming":
            source_w, source_h = get_video_dimensions(section_path)

            if facecam_region is None:
                facecam_region = detect_facecam_region(
                    url, time_offset=start + duration / 2
                )
            if facecam_region is None:
                # Sensible fallback for a bottom-left webcam overlay.
                facecam_region = Region(0.0, 0.75, 0.25, 0.25)

            margin = subtitle_margin_v if subtitle_margin_v is not None else 250
            config = gaming_layout(
                source_w,
                source_h,
                facecam_source=facecam_region,
                gameplay_source=gameplay_region,
                gameplay_focus=gameplay_focus,
                subtitle_margin_v=margin,
            )

            filter_complex, output_label = _gaming_filter_complex(
                config, source_w, source_h, with_subtitles, cues, start, end, work_dir
            )

            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{offset:.3f}",
                "-i", section_path.name,
                "-t", f"{duration:.3f}",
                "-filter_complex", filter_complex,
                "-map", output_label,
                "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path.name,
            ]
        else:
            margin = subtitle_margin_v if subtitle_margin_v is not None else 620
            config = default_layout(subtitle_margin_v=margin)
            filters, _ = _default_filters(
                with_subtitles, cues, start, end, config, work_dir
            )
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{offset:.3f}",
                "-i", section_path.name,
                "-t", f"{duration:.3f}",
                "-vf", ",".join(filters),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                output_path.name,
            ]

        result = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[:500]}")

        shutil.move(str(work_dir / output_path.name), str(output_path))
        return output_path
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def clip_filename(title: Optional[str], index: int, topic: str) -> str:
    """Build a readable, filesystem-safe clip filename."""
    prefix = sanitize_slug(title or "video", max_len=25)
    slug = sanitize_slug(topic, max_len=30)
    return f"{prefix}_clip_{index}_{slug}.mp4"
