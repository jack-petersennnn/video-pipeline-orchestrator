"""
Job queue management for batch processing.

Thread-safe queue that manages concurrent shot processing
with configurable parallelism.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable, Any

from src.models import JobStatus, ShotInput, JobState

logger = logging.getLogger(__name__)


class JobQueue:
    """
    Manages concurrent processing of shots within a job.

    Limits parallelism to avoid overwhelming external APIs
    while maximizing throughput.
    """

    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self._jobs: dict[str, JobStatus] = {}
        self._lock = threading.Lock()

    def register_job(self, job: JobStatus) -> None:
        """Register a new job for tracking."""
        with self._lock:
            self._jobs[job.job_id] = job

    def get_job(self, job_id: str) -> JobStatus | None:
        """Get job status by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def process_shots(
        self,
        job: JobStatus,
        shots: list[ShotInput],
        process_fn: Callable[[ShotInput], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Process shots concurrently with bounded parallelism.

        Args:
            job: Job status to update
            shots: List of shots to process
            process_fn: Function that processes a single shot and returns results

        Returns:
            List of result dicts, one per shot (in order)
        """
        results: list[dict[str, Any] | None] = [None] * len(shots)
        errors: list[str] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures: list[tuple[int, Future]] = []

            for i, shot in enumerate(shots):
                future = pool.submit(self._safe_process, shot, process_fn, job)
                futures.append((i, future))

            for i, future in futures:
                try:
                    result = future.result()
                    results[i] = result
                except Exception as e:
                    logger.error("Shot %d failed: %s", i, e)
                    errors.append(f"Shot {shots[i].shot_id}: {e}")
                    results[i] = {"error": str(e)}

        if errors:
            logger.warning("Job %s had %d shot failures", job.job_id, len(errors))

        return [r or {"error": "No result"} for r in results]

    def _safe_process(
        self,
        shot: ShotInput,
        process_fn: Callable[[ShotInput], dict[str, Any]],
        job: JobStatus,
    ) -> dict[str, Any]:
        """Process a shot with error capture and status updates."""
        shot_status = job.shots.get(shot.shot_id)

        try:
            if shot_status:
                shot_status.state = JobState.PROCESSING
            result = process_fn(shot)
            if shot_status:
                shot_status.state = JobState.COMPLETE
            return result

        except Exception as e:
            if shot_status:
                shot_status.state = JobState.FAILED
            raise

    def list_jobs(self, state: JobState | None = None) -> list[JobStatus]:
        """List jobs, optionally filtered by state."""
        with self._lock:
            jobs = list(self._jobs.values())
        if state:
            jobs = [j for j in jobs if j.state == state]
        return jobs
