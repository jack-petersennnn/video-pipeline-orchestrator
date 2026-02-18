"""
Lip sync step.

Takes a video clip and audio track, produces a lip-synced version.
Only runs for presenter shots that have voice audio.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.config import PipelineConfig
from src.models import ShotInput, ShotType, StepName
from .base import PipelineStep, StepError, StepTransientError

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5
MAX_POLL_ATTEMPTS = 60


class LipSyncStep(PipelineStep):
    step_name = StepName.LIP_SYNC

    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self.endpoint = config.minimax.url
        self.api_key = config.minimax.api_key

    def should_run(self, shot: ShotInput, context: dict[str, Any]) -> bool:
        """Lip sync only for presenter shots with voice audio."""
        return (
            shot.type == ShotType.PRESENTER
            and bool(shot.voice_audio_url)
            and bool(context.get("video_url"))
        )

    def execute(self, shot: ShotInput, context: dict[str, Any]) -> str:
        """Apply lip sync to video using the voice audio track."""
        video_url = context.get("video_url")
        if not video_url:
            raise StepError("No video URL for lip sync")

        if not shot.voice_audio_url:
            raise StepError("No voice audio URL for lip sync")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "video-01-live2d",
            "input_video_url": video_url,
            "input_audio_url": shot.voice_audio_url,
            "max_output_duration": int(shot.duration_sec) + 2,
        }

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{self.endpoint}/video_generation",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 429:
                    raise StepTransientError("Rate limited")
                if resp.status_code >= 500:
                    raise StepTransientError(f"Server error: {resp.status_code}")

                resp.raise_for_status()
                data = resp.json()

        except httpx.TimeoutException:
            raise StepTransientError("Lip sync submission timed out")

        task_id = data.get("task_id")
        if not task_id:
            raise StepError(f"No task_id in lip sync response: {data}")

        logger.info("Lip sync task %s for shot %s", task_id, shot.shot_id)

        # Poll for result
        with httpx.Client(timeout=30) as client:
            for _ in range(MAX_POLL_ATTEMPTS):
                time.sleep(POLL_INTERVAL_SEC)

                try:
                    resp = client.get(
                        f"{self.endpoint}/query/video_generation",
                        params={"task_id": task_id},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError:
                    continue

                if data.get("status") == "Success":
                    file_id = data.get("file_id")
                    if file_id:
                        resp = client.get(
                            f"{self.endpoint}/files/retrieve",
                            params={"file_id": file_id},
                            headers=headers,
                        )
                        resp.raise_for_status()
                        url = resp.json().get("file", {}).get("download_url")
                        if url:
                            logger.info("Lip sync complete for shot %s", shot.shot_id)
                            return url
                    raise StepError("Lip sync completed but no download URL")

                elif data.get("status") == "Fail":
                    raise StepError(f"Lip sync failed: {data}")

        raise StepTransientError("Lip sync timed out")
