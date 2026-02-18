"""
Face swap step using ComfyUI ReActor on RunPod.

Only runs for 'presenter' type shots that have an agent face reference.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import PipelineConfig
from src.models import ShotInput, ShotType, StepName
from .base import PipelineStep, StepError, StepTransientError

logger = logging.getLogger(__name__)


class FaceSwapStep(PipelineStep):
    step_name = StepName.FACE_SWAP

    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self.endpoint = config.comfyui.url
        self.api_key = config.comfyui.api_key
        self.timeout = config.comfyui.timeout_sec

    def should_run(self, shot: ShotInput, context: dict[str, Any]) -> bool:
        """Face swap only applies to presenter shots with a face reference."""
        return shot.type == ShotType.PRESENTER and bool(
            shot.agent_face_url or context.get("agent_face_url")
        )

    def execute(self, shot: ShotInput, context: dict[str, Any]) -> str:
        """Swap the agent's face onto the generated presenter image."""
        source_image = context.get("image_url")
        if not source_image:
            raise StepError("No generated image available for face swap")

        agent_face = shot.agent_face_url or context.get("agent_face_url")
        if not agent_face:
            raise StepError("No agent face URL provided")

        payload = {
            "input": {
                "workflow_type": "face_swap",
                "source_image": agent_face,
                "target_image": source_image,
                "face_index": 0,
                "restore_face": True,
            }
        }

        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.endpoint}/runsync",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code == 429:
                    raise StepTransientError("Rate limited by RunPod")
                if resp.status_code >= 500:
                    raise StepTransientError(f"RunPod server error: {resp.status_code}")

                resp.raise_for_status()
                data = resp.json()

        except httpx.TimeoutException:
            raise StepTransientError("Face swap request timed out")

        status = data.get("status")
        output = data.get("output", {})

        if status != "COMPLETED":
            raise StepTransientError(f"Face swap failed: {output.get('error', 'Unknown')}")

        urls = output.get("output_urls", [])
        if not urls:
            raise StepError("Face swap returned no output")

        logger.info("Face swap complete for shot %s", shot.shot_id)
        return urls[0]
