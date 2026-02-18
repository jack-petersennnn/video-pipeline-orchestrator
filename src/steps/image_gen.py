"""
Image generation step using ComfyUI on RunPod.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.config import PipelineConfig
from src.models import ShotInput, StepName
from .base import PipelineStep, StepError, StepTransientError

logger = logging.getLogger(__name__)


class ImageGenStep(PipelineStep):
    step_name = StepName.IMAGE_GEN

    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self.endpoint = config.comfyui.url
        self.api_key = config.comfyui.api_key
        self.timeout = config.comfyui.timeout_sec

    def execute(self, shot: ShotInput, context: dict[str, Any]) -> str:
        """Generate a scene image via ComfyUI RunPod endpoint."""
        payload = {
            "input": {
                "workflow_type": "image_gen",
                "prompt": shot.prompt,
                "negative_prompt": shot.negative_prompt,
                "width": shot.width,
                "height": shot.height,
                "steps": 25,
                "cfg_scale": 7.5,
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
            raise StepTransientError("ComfyUI request timed out")
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                raise StepTransientError(str(e))
            raise StepError(f"ComfyUI API error: {e}")

        status = data.get("status")
        output = data.get("output", {})

        if status != "COMPLETED":
            error = output.get("error", "Unknown error")
            raise StepTransientError(f"ComfyUI job failed: {error}")

        urls = output.get("output_urls", [])
        if not urls:
            raise StepError("ComfyUI returned no output images")

        logger.info("Generated image for shot %s: %s", shot.shot_id, urls[0][:80])
        return urls[0]
