"""
Data models for the video pipeline.

Defines the structure of shot lists, jobs, and pipeline state
using Pydantic for runtime validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VideoType(str, Enum):
    REALTOR_PROFILE = "realtor_profile"
    CREATIVE_REALTOR_PROFILE = "creative_realtor_profile"
    HOUSE_LISTING = "house_listing"
    AVATAR_PROPERTY_TOUR = "avatar_property_tour"
    ZILLOW_EXPLAINER = "zillow_explainer"


class ShotType(str, Enum):
    SCENE = "scene"
    PRESENTER = "presenter"
    TRANSITION = "transition"


class StepName(str, Enum):
    IMAGE_GEN = "image_gen"
    FACE_SWAP = "face_swap"
    VIDEO_GEN = "video_gen"
    LIP_SYNC = "lip_sync"
    ASSEMBLY = "assembly"


class JobState(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class ShotInput(BaseModel):
    """A single shot in the production shot list."""
    shot_id: str
    type: ShotType
    prompt: str
    negative_prompt: str = "blurry, low quality, watermark, text"
    duration_sec: float = 5.0
    width: int = 1280
    height: int = 720
    voice_audio_url: Optional[str] = None
    agent_face_url: Optional[str] = None
    transition_type: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ShotListInput(BaseModel):
    """Full shot list for a video production job."""
    project_id: str
    project_name: str
    video_type: VideoType
    shots: list[ShotInput]
    agent_face_url: Optional[str] = None
    webhook_url: Optional[str] = None
    output_format: str = "mp4"
    output_resolution: str = "1280x720"


class StepResult(BaseModel):
    """Result of a single pipeline step for a shot."""
    step: StepName
    state: JobState = JobState.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_url: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    duration_sec: Optional[float] = None


class ShotStatus(BaseModel):
    """Status of a single shot through the pipeline."""
    shot_id: str
    state: JobState = JobState.PENDING
    steps: dict[StepName, StepResult] = Field(default_factory=dict)
    image_url: Optional[str] = None
    face_swap_url: Optional[str] = None
    video_url: Optional[str] = None
    lip_sync_url: Optional[str] = None

    @property
    def current_step(self) -> Optional[StepName]:
        for step_name, result in self.steps.items():
            if result.state == JobState.PROCESSING:
                return step_name
        return None


class JobStatus(BaseModel):
    """Overall job status with per-shot tracking."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    state: JobState = JobState.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    shots: dict[str, ShotStatus] = Field(default_factory=dict)
    output_url: Optional[str] = None
    error: Optional[str] = None

    @property
    def progress_pct(self) -> float:
        if not self.shots:
            return 0.0
        total_steps = 0
        completed_steps = 0
        for shot in self.shots.values():
            for result in shot.steps.values():
                total_steps += 1
                if result.state == JobState.COMPLETE:
                    completed_steps += 1
        return (completed_steps / total_steps * 100) if total_steps > 0 else 0.0

    @property
    def failed_shots(self) -> list[str]:
        return [sid for sid, s in self.shots.items() if s.state == JobState.FAILED]
