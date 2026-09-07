from pydantic import BaseModel, Field
from typing import List, Optional


class Cue(BaseModel):
    """A single subtitle cue with timestamps."""

    start: float = Field(..., description="Start time in seconds")
    end: float = Field(..., description="End time in seconds")
    text: str = Field(..., description="Cleaned cue text")


class Chunk(BaseModel):
    """A transcript chunk for LLM processing."""

    index: int = Field(..., description="Chunk index")
    start: float = Field(..., description="Chunk start time in seconds")
    end: float = Field(..., description="Chunk end time in seconds")
    text: str = Field(..., description="Combined transcript text in the chunk")


class Candidate(BaseModel):
    """A candidate Shorts clip proposed by the LLM."""

    start: float = Field(..., description="Clip start time in seconds")
    end: float = Field(..., description="Clip end time in seconds")
    score: float = Field(
        ..., ge=0, le=100, description="Engagement score from 0 to 100"
    )
    topic: str = Field(..., description="Short topic/title of the clip")
    reason: str = Field(..., description="Why this clip works as a Short")
    file: Optional[str] = Field(
        None, description="Path to the cut video file, if clipping was enabled"
    )


class FinalResult(BaseModel):
    """Final output of ContentForge."""

    url: str = Field(..., description="Source YouTube URL")
    title: Optional[str] = Field(None, description="Video title if available")
    top_clips: List[Candidate] = Field(
        ..., description="Top 5 ranked Shorts candidates"
    )
