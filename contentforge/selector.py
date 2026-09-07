from typing import List

from .models import Candidate


def _iou(a: Candidate, b: Candidate) -> float:
    """Compute intersection-over-union of two time intervals."""
    inter_start = max(a.start, b.start)
    inter_end = min(a.end, b.end)
    inter = max(0.0, inter_end - inter_start)
    union = max(a.end, b.end) - min(a.start, b.start)
    return inter / union if union > 0 else 0.0


def deduplicate_candidates(
    candidates: List[Candidate],
    iou_threshold: float = 0.5,
) -> List[Candidate]:
    """Remove overlapping candidates, keeping the higher-scored one."""
    # Sort by score descending
    sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
    kept: List[Candidate] = []
    for cand in sorted_candidates:
        if any(_iou(cand, kept_cand) >= iou_threshold for kept_cand in kept):
            continue
        kept.append(cand)
    return kept


def rank_candidates(candidates: List[Candidate], top_n: int = 5) -> List[Candidate]:
    """Rank candidates by score and return the top N."""
    scored = sorted(candidates, key=lambda c: (c.score, -(c.end - c.start)), reverse=True)
    return scored[:top_n]
