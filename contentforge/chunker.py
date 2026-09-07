from typing import List

from .models import Chunk, Cue


SECONDS_PER_CHUNK = 300  # 5 minutes
OVERLAP_SECONDS = 60  # 1 minute


def chunk_transcript(
    cues: List[Cue],
    chunk_duration: float = SECONDS_PER_CHUNK,
    overlap: float = OVERLAP_SECONDS,
) -> List[Chunk]:
    """Split transcript cues into overlapping chunks.

    Each chunk spans ``chunk_duration`` seconds, overlapping the previous
    chunk by ``overlap`` seconds. Cues are included wholly if they fall inside
    the chunk window.
    """
    if not cues:
        return []

    if chunk_duration <= overlap:
        raise ValueError("chunk_duration must be greater than overlap")

    total_duration = cues[-1].end
    step = chunk_duration - overlap
    chunks: List[Chunk] = []

    start_time = 0.0
    chunk_index = 0
    while start_time < total_duration:
        end_time = min(start_time + chunk_duration, total_duration + 1.0)

        chunk_text_parts: List[str] = []
        for cue in cues:
            if cue.start >= start_time and cue.end <= end_time:
                chunk_text_parts.append(cue.text)
            elif cue.start < end_time and cue.end > start_time:
                # Cue straddles the boundary: include it if the majority is inside
                inside_start = max(cue.start, start_time)
                inside_end = min(cue.end, end_time)
                if inside_end > inside_start:
                    chunk_text_parts.append(cue.text)

        if chunk_text_parts:
            chunks.append(
                Chunk(
                    index=chunk_index,
                    start=start_time,
                    end=end_time,
                    text=" ".join(chunk_text_parts),
                )
            )
            chunk_index += 1

        start_time += step

    return chunks
