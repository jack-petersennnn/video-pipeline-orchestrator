"""
Main pipeline orchestrator.

Coordinates the full video production pipeline from shot list input
through to final assembled video output.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import PipelineConfig
from src.models import (
    ShotListInput,
    ShotInput,
    ShotStatus,
    StepResult,
    JobStatus,
    JobState,
    StepName,
    ShotType,
)
from src.queue import JobQueue
from src.notifications import send_webhook
from src.steps import (
    ImageGenStep,
    FaceSwapStep,
    VideoGenStep,
    LipSyncStep,
    AssemblyStep,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the full video production pipeline.

    Takes a shot list and runs each shot through the appropriate
    pipeline stages, then assembles the final video.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.queue = JobQueue(max_workers=config.max_concurrent_shots)

        # Initialize pipeline steps
        self.image_gen = ImageGenStep(config)
        self.face_swap = FaceSwapStep(config)
        self.video_gen = VideoGenStep(config)
        self.lip_sync = LipSyncStep(config)
        self.assembly = AssemblyStep(config)

    def submit(self, shot_list_path: str | Path) -> JobStatus:
        """
        Submit a shot list file for processing.

        Args:
            shot_list_path: Path to shot list JSON file

        Returns:
            JobStatus with tracking information
        """
        with open(shot_list_path) as f:
            data = json.load(f)

        shot_list = ShotListInput(**data)
        return self.submit_shot_list(shot_list)

    def submit_shot_list(self, shot_list: ShotListInput) -> JobStatus:
        """Submit a parsed shot list for processing."""
        job = JobStatus(project_id=shot_list.project_id)

        # Initialize per-shot status tracking
        for shot in shot_list.shots:
            steps = self._plan_steps(shot, shot_list)
            job.shots[shot.shot_id] = ShotStatus(
                shot_id=shot.shot_id,
                steps={step: StepResult(step=step) for step in steps},
            )

        self.queue.register_job(job)
        logger.info(
            "Job %s created: %d shots for project '%s'",
            job.job_id, len(shot_list.shots), shot_list.project_name,
        )

        # Process all shots
        job.state = JobState.PROCESSING
        job.started_at = datetime.utcnow()

        global_context = {}
        if shot_list.agent_face_url:
            global_context["agent_face_url"] = shot_list.agent_face_url

        webhook_url = shot_list.webhook_url or self.config.webhook_url

        try:
            results = self.queue.process_shots(
                job,
                shot_list.shots,
                lambda shot: self._process_shot(shot, job, global_context),
            )

            # Collect successful shot videos for assembly
            shot_videos = []
            for shot, result in zip(shot_list.shots, results):
                video_url = result.get("final_video_url") or result.get("video_url")
                if video_url:
                    shot_videos.append({
                        "shot_id": shot.shot_id,
                        "video_url": video_url,
                        "duration_sec": shot.duration_sec,
                    })

            # Assemble final video
            if shot_videos:
                logger.info("Assembling %d shot videos for job %s", len(shot_videos), job.job_id)
                job.output_url = self.assembly.assemble(shot_videos, job.job_id)

            job.state = JobState.COMPLETE
            job.completed_at = datetime.utcnow()

            if webhook_url:
                send_webhook(webhook_url, job, "job.completed")

            logger.info("Job %s complete: %s", job.job_id, job.output_url)

        except Exception as e:
            job.state = JobState.FAILED
            job.completed_at = datetime.utcnow()
            job.error = str(e)
            logger.exception("Job %s failed", job.job_id)

            if webhook_url:
                send_webhook(webhook_url, job, "job.failed")

        return job

    def get_status(self, job_id: str) -> JobStatus | None:
        """Get current status of a job."""
        return self.queue.get_job(job_id)

    def wait(self, job_id: str, timeout: int = 600, poll_interval: float = 5.0) -> JobStatus:
        """Wait for a job to complete."""
        start = time.time()
        while time.time() - start < timeout:
            job = self.get_status(job_id)
            if job and job.state in (JobState.COMPLETE, JobState.FAILED):
                return job
            time.sleep(poll_interval)
        raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")

    def _plan_steps(self, shot: ShotInput, shot_list: ShotListInput) -> list[StepName]:
        """Determine which pipeline steps a shot needs."""
        steps = [StepName.IMAGE_GEN]

        if shot.type == ShotType.PRESENTER:
            face_url = shot.agent_face_url or shot_list.agent_face_url
            if face_url:
                steps.append(StepName.FACE_SWAP)

        steps.append(StepName.VIDEO_GEN)

        if shot.type == ShotType.PRESENTER and shot.voice_audio_url:
            steps.append(StepName.LIP_SYNC)

        return steps

    def _process_shot(
        self,
        shot: ShotInput,
        job: JobStatus,
        global_context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Run a single shot through its pipeline steps sequentially.

        Each step's output feeds into the next step's context.
        """
        shot_status = job.shots[shot.shot_id]
        context: dict[str, Any] = {**global_context}

        logger.info("Processing shot %s (%s)", shot.shot_id, shot.type.value)

        # Step 1: Image generation
        if StepName.IMAGE_GEN in shot_status.steps:
            result = shot_status.steps[StepName.IMAGE_GEN]
            url = self.image_gen.run(shot, context, result)
            context["image_url"] = url
            shot_status.image_url = url

        # Step 2: Face swap (conditional)
        if StepName.FACE_SWAP in shot_status.steps:
            if self.face_swap.should_run(shot, context):
                result = shot_status.steps[StepName.FACE_SWAP]
                url = self.face_swap.run(shot, context, result)
                context["face_swap_url"] = url
                shot_status.face_swap_url = url

        # Step 3: Video generation
        if StepName.VIDEO_GEN in shot_status.steps:
            result = shot_status.steps[StepName.VIDEO_GEN]
            url = self.video_gen.run(shot, context, result)
            context["video_url"] = url
            shot_status.video_url = url

        # Step 4: Lip sync (conditional)
        if StepName.LIP_SYNC in shot_status.steps:
            if self.lip_sync.should_run(shot, context):
                result = shot_status.steps[StepName.LIP_SYNC]
                url = self.lip_sync.run(shot, context, result)
                context["lip_sync_url"] = url
                shot_status.lip_sync_url = url

        shot_status.state = JobState.COMPLETE
        return {
            "shot_id": shot.shot_id,
            "image_url": context.get("image_url"),
            "face_swap_url": context.get("face_swap_url"),
            "video_url": context.get("video_url"),
            "final_video_url": context.get("lip_sync_url") or context.get("video_url"),
        }


def main():
    """CLI entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m src.orchestrator <shot_list.json>")
        sys.exit(1)

    config = PipelineConfig.from_env()
    orchestrator = PipelineOrchestrator(config)
    job = orchestrator.submit(sys.argv[1])

    print(f"\nJob {job.job_id}: {job.state.value}")
    print(f"Progress: {job.progress_pct:.0f}%")

    if job.output_url:
        print(f"Output: {job.output_url}")
    if job.error:
        print(f"Error: {job.error}")
    if job.failed_shots:
        print(f"Failed shots: {', '.join(job.failed_shots)}")


if __name__ == "__main__":
    main()
