import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .chunker import chunk_transcript
from .config import load_config
from .cutter import clip_filename, cut_clip
from .downloader import download_subtitle
from .facecam import detect_facecam_region
from .layout import Region
from .llm import create_client, find_candidates_in_chunk
from .models import Candidate, FinalResult
from .parser import parse_vtt_file
from .selector import deduplicate_candidates, rank_candidates


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contentforge",
        description="ContentForge V1: YouTube URL -> transcript -> top 5 Shorts clips",
    )
    parser.add_argument("url", help="YouTube URL")
    parser.add_argument(
        "-o",
        "--output",
        default="contentforge_output.json",
        help="Output JSON file path",
    )
    parser.add_argument(
        "-n",
        "--top-n",
        type=int,
        default=5,
        help="Number of top clips to output",
    )
    parser.add_argument(
        "--lang",
        default="id",
        help="Preferred subtitle language (default: id)",
    )
    parser.add_argument(
        "--cut",
        action="store_true",
        help="Also cut the top clips to MP4 (9:16 vertical)",
    )
    parser.add_argument(
        "--subtitles",
        action="store_true",
        help="Burn Podcast Shorts style subtitles into the cut clips (requires --cut)",
    )
    parser.add_argument(
        "--clips-dir",
        default="/sdcard/Movies/ContentForge",
        help="Output directory for cut clips (default: /sdcard/Movies/ContentForge)",
    )
    parser.add_argument(
        "--layout",
        default="default",
        choices=["default", "gaming"],
        help="Vertical layout: default (center-crop) or gaming (facecam + gameplay)",
    )
    parser.add_argument(
        "--facecam-region",
        default=None,
        help="Gaming layout: normalized source facecam region as x,y,w,h",
    )
    parser.add_argument(
        "--gameplay-region",
        default=None,
        help="Gaming layout: normalized source gameplay region as x,y,w,h",
    )
    parser.add_argument(
        "--gameplay-focus",
        type=float,
        default=0.5,
        help="Gaming layout: horizontal focus for auto gameplay crop (0=left, 1=right, default 0.5)",
    )
    parser.add_argument(
        "--subtitle-margin",
        type=int,
        default=None,
        help="ASS subtitle bottom margin in pixels (default: 620 default layout, 250 gaming layout)",
    )
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=300,
        help="Transcript chunk duration in seconds for LLM processing (default: 300)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=60,
        help="Overlap between transcript chunks in seconds (default: 60)",
    )
    return parser


def process(
    url: str,
    lang: str = "id",
    top_n: int = 5,
    cut: bool = False,
    subtitles: bool = False,
    clips_dir: str = "/sdcard/Movies/ContentForge",
    layout: str = "default",
    facecam_region: Optional[Region] = None,
    gameplay_region: Optional[Region] = None,
    gameplay_focus: float = 0.5,
    subtitle_margin: Optional[int] = None,
    chunk_duration: int = 300,
    overlap: int = 60,
) -> FinalResult:
    """Main pipeline: download subtitles, chunk, ask LLM, rank."""
    config = load_config()
    client = create_client(config["base_url"], config["api_key"])

    print(f"[1/5] Downloading subtitles for: {url}")
    subtitle_path, info = download_subtitle(url, preferred_lang=lang)
    title = info.get("title")
    print(f"      Subtitle saved: {subtitle_path}")
    if title:
        print(f"      Title: {title}")

    print("[2/5] Parsing VTT...")
    cues = parse_vtt_file(subtitle_path)
    print(f"      Found {len(cues)} cues")

    print("[3/5] Chunking transcript...")
    chunks = chunk_transcript(cues, chunk_duration=chunk_duration, overlap=overlap)
    print(f"      Created {len(chunks)} chunks")

    print("[4/5] Querying LLM for candidates...")
    all_candidates: List[Candidate] = []
    for chunk in chunks:
        try:
            candidates = find_candidates_in_chunk(
                client=client,
                model=config["model"],
                chunk=chunk,
            )
            print(f"      Chunk {chunk.index}: {len(candidates)} candidates")
            all_candidates.extend(candidates)
        except Exception as exc:
            print(f"      Chunk {chunk.index}: error ({exc})", file=sys.stderr)

    print("[5/5] Deduplicating and ranking...")
    unique = deduplicate_candidates(all_candidates)
    top = rank_candidates(unique, top_n=top_n)

    if cut:
        out_dir = Path(clips_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if layout == "gaming" and facecam_region is None:
            print("[layout] Auto-detecting facecam region for gaming layout...")
            facecam_region = detect_facecam_region(url)
            if facecam_region:
                print(f"      Detected facecam region: {facecam_region}")
        print(f"[cut] Cutting {len(top)} clip(s) to {out_dir} ...")
        for i, clip in enumerate(top, start=1):
            try:
                filename = clip_filename(title, i, clip.topic)
                target = out_dir / filename
                print(f"      Clip {i}: {clip.start:.0f}s-{clip.end:.0f}s -> {filename}")
                cut_clip(
                    url, clip.start, clip.end, cues, target,
                    with_subtitles=subtitles,
                    layout=layout,
                    facecam_region=facecam_region,
                    gameplay_region=gameplay_region,
                    gameplay_focus=gameplay_focus,
                    subtitle_margin_v=subtitle_margin,
                )
                clip.file = str(target)
            except Exception as exc:
                print(f"      Clip {i}: error ({exc})", file=sys.stderr)

    return FinalResult(url=url, title=title, top_clips=top)


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    facecam_region = Region.from_string(args.facecam_region) if args.facecam_region else None
    gameplay_region = Region.from_string(args.gameplay_region) if args.gameplay_region else None

    result = process(
        args.url, lang=args.lang, top_n=args.top_n,
        cut=args.cut, subtitles=args.subtitles, clips_dir=args.clips_dir,
        layout=args.layout,
        facecam_region=facecam_region,
        gameplay_region=gameplay_region,
        gameplay_focus=args.gameplay_focus,
        subtitle_margin=args.subtitle_margin,
        chunk_duration=args.chunk_duration,
        overlap=args.overlap,
    )

    output_path = Path(args.output)
    output_path.write_text(
        result.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
    print(f"Saved {len(result.top_clips)} top clip(s) to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
