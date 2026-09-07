import json
from typing import Any, List

import httpx

from .models import Candidate, Chunk


SYSTEM_PROMPT = (
    "You are an expert content editor for YouTube Shorts. "
    "Given a chunk of a YouTube transcript with timestamps, identify at most 3 short, "
    "engaging clips suitable for YouTube Shorts. "
    "Each clip must be self-contained, have a hook, and be under 60 seconds. "
    "Return ONLY a raw JSON array of objects. "
    "Each object must have these exact keys: start (float seconds), end (float seconds), "
    "score (number 0-100), topic (short string), reason (string). "
    "Do not include markdown, code fences, or explanations."
)


def _build_user_prompt(chunk: Chunk) -> str:
    return (
        f"Chunk {chunk.index} starts at {chunk.start:.1f}s and ends at {chunk.end:.1f}s.\n\n"
        f"Transcript:\n{chunk.text}\n\n"
        f"Select up to 3 best Shorts candidates within this chunk. "
        f"Ensure start/end are within [{chunk.start:.1f}, {chunk.end:.1f}] and each clip is under 60 seconds."
    )


def create_client(base_url: str, api_key: str) -> httpx.Client:
    """Create an HTTP client configured for an OpenAI-compatible API."""
    if not base_url:
        raise ValueError("OPENAI_BASE_URL is not configured")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=120.0,
    )


def parse_candidates(raw: str, chunk: Chunk) -> List[Candidate]:
    """Parse raw LLM JSON output into Candidate objects, clamped to chunk bounds."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip markdown fences greedily
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()

    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("LLM response is not a JSON array")

    candidates: List[Candidate] = []
    for item in data[:3]:
        start = max(chunk.start, float(item.get("start", chunk.start)))
        end = min(chunk.end, float(item.get("end", chunk.end)))
        # Ensure sane order
        if end <= start:
            end = start + 30.0
        if end > chunk.end:
            end = chunk.end
        if end - start > 60:
            end = start + 60
        candidates.append(
            Candidate(
                start=start,
                end=end,
                score=float(item.get("score", 0)),
                topic=str(item.get("topic", "")).strip() or "Untitled clip",
                reason=str(item.get("reason", "")).strip() or "No reason provided",
            )
        )
    return candidates


def find_candidates_in_chunk(
    client: httpx.Client,
    model: str,
    chunk: Chunk,
    temperature: float = 0.3,
) -> List[Candidate]:
    """Send a chunk to the LLM and parse the returned candidates."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk)},
        ],
        "temperature": temperature,
        "max_tokens": 2500,
    }

    response = client.post("/chat/completions", json=payload)
    response.raise_for_status()
    data = response.json()

    choices = data.get("choices", [])
    if not choices:
        return []

    content = choices[0].get("message", {}).get("content", "")
    if not content:
        return []

    return parse_candidates(content, chunk)
