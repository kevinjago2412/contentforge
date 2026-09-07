"""Optional automatic facecam region detection for the gaming layout.

Requires OpenCV (``cv2``) with ``FaceDetectorYN_create`` support.  The first
run downloads the YuNet ONNX model (~230 kB) into
``~/.cache/contentforge/``.
"""

import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

from .layout import Region
from .videodl import _get_stream_urls


MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx"
)


def _model_path() -> Path:
    cache = Path.home() / ".cache" / "contentforge"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "face_detection_yunet_2023mar.onnx"


def _ensure_model() -> Path:
    path = _model_path()
    if not path.exists():
        urllib.request.urlretrieve(MODEL_URL, path)
    return path


def _extract_frame(video_url: str, time_offset: float, out_path: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{time_offset:.3f}", "-i", video_url,
        "-vf", "select=eq(n\\,0)", "-vframes", "1", "-q:v", "2",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"frame extraction failed: {result.stderr.strip()[:500]}")


def detect_facecam_region(
    url: str,
    time_offset: float = 30.0,
    target_aspect: float = 1.5,
) -> Optional[Region]:
    """Detect the streamer facecam region from a sample frame.

    Returns a normalized ``Region`` suitable for the gaming layout, or ``None``
    if detection is unavailable or no face is found.
    """
    try:
        import cv2
    except ImportError:
        return None

    video_url, _ = _get_stream_urls(url)

    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.jpg"
        _extract_frame(video_url, time_offset, frame_path)

        img = cv2.imread(str(frame_path))
        if img is None:
            return None

        h, w = img.shape[:2]
        model = _ensure_model()
        detector = cv2.FaceDetectorYN_create(str(model), "", (w, h))
        detector.setScoreThreshold(0.3)
        detector.setNMSThreshold(0.3)
        detector.setTopK(10)

        success, faces = detector.detect(img)
        if not success or faces is None or faces.shape[0] == 0:
            return None

        # Score each detection and prefer faces near the frame edges, because
        # streamer facecams are almost always placed in a corner.
        scored = []
        for f in faces:
            x, y, fw, fh = f[:4].astype(float)
            conf = float(f[14])
            cx, cy = x + fw / 2.0, y + fh / 2.0
            edge_dist = min(cx / w, cy / h, (w - cx) / w, (h - cy) / h)
            scored.append((conf, edge_dist, x, y, fw, fh))

        # Highest confidence first; if conf ties, prefer the face closest to a
        # corner (smallest edge_dist).
        scored.sort(key=lambda t: (t[0], -t[1]), reverse=True)
        _, _, x, y, fw, fh = scored[0]

        # Build a source crop around the detected face with the target aspect
        # ratio.  The margins leave room for shoulders/background while keeping
        # the face as the focal point.
        margin_y = 2.2
        margin_x = 1.8
        region_h = max(fh * margin_y, (fw * margin_x) / target_aspect)
        region_w = region_h * target_aspect

        cx, cy = x + fw / 2.0, y + fh / 2.0
        rx = cx - region_w / 2.0
        ry = cy - region_h / 2.0

        # Clamp to source bounds, preserving as much of the crop as possible.
        if rx < 0:
            rx = 0.0
        if rx + region_w > w:
            rx = max(0.0, w - region_w)
            region_w = w - rx
        if ry < 0:
            ry = 0.0
        if ry + region_h > h:
            ry = max(0.0, h - region_h)
            region_h = h - ry

        return Region(rx / w, ry / h, region_w / w, region_h / h)
