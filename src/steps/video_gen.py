"""
Video generation step.

Takes a still image and generates a short video clip using
image-to-video AI (e.g., Minimax Video-01, Runway Gen-3, Kling).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.config import PipelineConfig
from src.models import ShotInput, StepName
from .base import PipelineStep, StepError, StepTransientError

logger = logging.getLogger(__name__)

POLL_INTERVAL_SEC = 5
MAX_POLL_ATTEMPTS = 120  # 10 minutes at 5s intervals


class VideoGenStep(PipelineStep):
    step_name = StepName.VIDEO_GEN

    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self.endpoint = config.minimax.url
        self.api_key = config.minimax.api_key
        self.timeout = config.minimax.timeout_sec

    def execute(self, shot: ShotInput, context: dict[str, Any]) -> str:
        """Generate a video clip from a still image."""
        # Use face-swapped image if available, otherwise the raw generated image
        source_image = context.get("face_swap_url") or context.get("image_url")
        if not source_image:
            raise StepError("No source image available for video generation")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Submit video generation job
        payload = {
            "model": "video-01",
            "first_frame_image": source_image,
            "prompt": f"Slow cinematic camera movement, {shot.prompt}, professional real estate video",
            "prompt_optimizer": True,
        }

        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{self.endpoint}/video_generation",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 429:
                    raise StepTransientError("Rate limited by video generation API")
                if resp.status_code >= 500:
                    raise StepTransientError(f"Video gen server error: {resp.status_code}")

                resp.raise_for_status()
                data = resp.json()

        except httpx.TimeoutException:
            raise StepTransientError("Video generation submission timed out")

        task_id = data.get("task_id")
        if not task_id:
            raise StepError(f"No task_id in response: {data}")

        logger.info("Video gen task %s submitted for shot %s", task_id, shot.shot_id)

        # Poll for completion
        return self._poll_for_result(task_id, headers, shot.shot_id)

    def _poll_for_result(self, task_id: str, headers: dict, shot_id: str) -> str:
        """Poll the video generation API until the task completes."""
        with httpx.Client(timeout=30) as client:
            for attempt in range(MAX_POLL_ATTEMPTS):
                time.sleep(POLL_INTERVAL_SEC)

                try:
                    resp = client.get(
                        f"{self.endpoint}/query/video_generation",
                        params={"task_id": task_id},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.HTTPError as e:
                    logger.warning("Poll error for task %s: %s", task_id, e)
                    continue

                status = data.get("status")

                if status == "Success":
                    file_id = data.get("file_id")
                    if file_id:
                        download_url = self._get_download_url(file_id, headers, client)
                        logger.info("Video ready for shot %s: %s", shot_id, download_url[:80])
                        return download_url
                    raise StepError("Video completed but no file_id returned")

                elif status == "Fail":
                    raise StepError(f"Video generation failed: {data.get('base_resp', {}).get('status_msg', 'Unknown')}")

                elif status in ("Queueing", "Processing"):
                    if attempt % 12 == 0:  # Log every minute
                        logger.info("Video gen task %s: %s", task_id, status)

        raise StepTransientError(f"Video generation timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL_SEC}s")

    def _get_download_url(self, file_id: str, headers: dict, client: httpx.Client) -> str:
        """Retrieve the download URL for a completed video file."""
        resp = client.get(
            f"{self.endpoint}/files/retrieve",
            params={"file_id": file_id},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

        download_url = data.get("file", {}).get("download_url")
        if not download_url:
            raise StepError(f"No download URL for file {file_id}")

        return download_url
