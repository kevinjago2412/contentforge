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
from .videodl import FORMAT_SELECTOR_H264 as FORMAT_SELECTOR_FALLBACK, _cookies_opts


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


def _extract_frame(url: str, time_offset: float, out_path: Path) -> None:
    """Grab a single frame at time_offset via yt-dlp section download + OpenCV.

    yt-dlp handles all auth/headers (direct googlevideo access gets 403 on
    datacenter IPs). OpenCV reads the local sample directly — more robust
    than ffmpeg CLI, which hits decoder assertions on some webm/vp9 samples.
    """
    import cv2
    import yt_dlp

    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "sample"
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": FORMAT_SELECTOR_FALLBACK,
            "download_ranges": lambda _, __: [
                {"start_time": time_offset, "end_time": time_offset + 2.0}
            ],
            "outtmpl": str(stem) + ".%(ext)s",
            **_cookies_opts(),
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        samples = [p for p in Path(tmp).glob("sample.*") if p.suffix != ".part"]
        if not samples:
            raise RuntimeError("yt-dlp frame sample download produced no file")

        cap = cv2.VideoCapture(str(samples[0]))
        try:
            ok, frame = cap.read()
        finally:
            cap.release()
        if not ok or frame is None:
            raise RuntimeError("could not read first frame from sample video")
        if not cv2.imwrite(str(out_path), frame):
            raise RuntimeError(f"could not write frame to {out_path}")


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

    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.jpg"
        _extract_frame(url, time_offset, frame_path)

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
