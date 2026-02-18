"""
Video assembly step.

Concatenates individual shot videos into a final production using FFmpeg.
Handles transitions and audio mixing.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import Any

import httpx
import boto3
from botocore.config import Config

from src.config import PipelineConfig
from src.models import ShotInput, StepName
from .base import PipelineStep, StepError

logger = logging.getLogger(__name__)


class AssemblyStep(PipelineStep):
    step_name = StepName.ASSEMBLY

    def __init__(self, config: PipelineConfig):
        super().__init__(config)
        self.ffmpeg = config.ffmpeg_path
        self.storage = config.storage

    def execute(self, shot: ShotInput, context: dict[str, Any]) -> str:
        """
        This step is called once for the final assembly, not per-shot.
        The orchestrator calls assemble() directly instead.
        """
        raise NotImplementedError("Use assemble() for multi-shot assembly")

    def assemble(self, shot_videos: list[dict[str, Any]], job_id: str) -> str:
        """
        Concatenate shot videos into a final production.

        Args:
            shot_videos: List of dicts with 'shot_id', 'video_url', 'duration_sec'
            job_id: Job ID for output naming

        Returns:
            URL of the assembled final video
        """
        if not shot_videos:
            raise StepError("No shot videos to assemble")

        with tempfile.TemporaryDirectory(prefix="assembly_") as tmpdir:
            # Download all shot videos
            clip_paths = []
            for i, shot_video in enumerate(shot_videos):
                url = shot_video["video_url"]
                clip_path = os.path.join(tmpdir, f"clip_{i:03d}.mp4")
                self._download(url, clip_path)
                clip_paths.append(clip_path)

            # Build FFmpeg concat file
            concat_path = os.path.join(tmpdir, "concat.txt")
            with open(concat_path, "w") as f:
                for clip_path in clip_paths:
                    f.write(f"file '{clip_path}'\n")

            # Assemble
            output_path = os.path.join(tmpdir, "final.mp4")
            cmd = [
                self.ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_path,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                "-pix_fmt", "yuv420p",
                output_path,
            ]

            logger.info("Assembling %d clips for job %s", len(clip_paths), job_id)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                logger.error("FFmpeg stderr: %s", result.stderr[-500:])
                raise StepError(f"FFmpeg assembly failed: {result.stderr[-200:]}")

            # Upload to storage
            output_key = f"productions/{job_id}/final.mp4"
            url = self._upload(output_path, output_key)

            logger.info("Assembly complete for job %s: %s", job_id, output_key)
            return url

    def _download(self, url: str, dest: str) -> None:
        """Download a file from URL."""
        with httpx.Client(timeout=120) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)

    def _upload(self, filepath: str, key: str) -> str:
        """Upload a file to S3-compatible storage and return presigned URL."""
        s3 = boto3.client(
            "s3",
            endpoint_url=self.storage.endpoint,
            aws_access_key_id=self.storage.access_key,
            aws_secret_access_key=self.storage.secret_key,
            region_name=self.storage.region,
            config=Config(signature_version="s3v4"),
        )

        with open(filepath, "rb") as f:
            s3.put_object(
                Bucket=self.storage.bucket,
                Key=key,
                Body=f,
                ContentType="video/mp4",
            )

        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.storage.bucket, "Key": key},
            ExpiresIn=3600 * 24 * 7,  # 7 days
        )
        return url
