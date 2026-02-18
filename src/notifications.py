"""
Webhook notification delivery for pipeline events.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.models import JobStatus

logger = logging.getLogger(__name__)


def send_webhook(url: str, job: JobStatus, event: str = "job.completed") -> bool:
    """
    Send a webhook notification for a pipeline event.

    Args:
        url: Webhook endpoint URL
        job: Current job status
        event: Event type (job.completed, job.failed, shot.completed)

    Returns:
        True if delivery succeeded
    """
    payload = {
        "event": event,
        "job_id": job.job_id,
        "project_id": job.project_id,
        "state": job.state.value,
        "progress_pct": job.progress_pct,
        "output_url": job.output_url,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "shots": {
            shot_id: {
                "state": shot.state.value,
                "image_url": shot.image_url,
                "video_url": shot.video_url,
            }
            for shot_id, shot in job.shots.items()
        },
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            logger.info("Webhook delivered: %s → %s (%d)", event, url, resp.status_code)
            return True

    except httpx.HTTPError as e:
        logger.error("Webhook delivery failed: %s → %s: %s", event, url, e)
        return False
