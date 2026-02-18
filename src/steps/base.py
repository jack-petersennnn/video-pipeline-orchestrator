"""
Abstract base class for pipeline steps.

Each step handles one stage of the video production pipeline,
with built-in retry logic and status tracking.
"""

from __future__ import annotations

import abc
import time
import logging
from typing import Any

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from src.config import PipelineConfig
from src.models import ShotInput, StepResult, StepName, JobState

logger = logging.getLogger(__name__)


class StepError(Exception):
    """Non-retryable step error."""
    pass


class StepTransientError(Exception):
    """Retryable transient error (timeout, rate limit, server error)."""
    pass


class PipelineStep(abc.ABC):
    """
    Base class for all pipeline steps.

    Subclasses implement `execute()` with the actual API call logic.
    Retry behavior is handled at this level.
    """

    step_name: StepName

    def __init__(self, config: PipelineConfig):
        self.config = config

    @abc.abstractmethod
    def execute(self, shot: ShotInput, context: dict[str, Any]) -> str:
        """
        Execute this pipeline step for a single shot.

        Args:
            shot: The shot input specification
            context: Accumulated results from previous steps.
                     Keys like 'image_url', 'face_swap_url', etc.

        Returns:
            URL of the output asset

        Raises:
            StepTransientError: For retryable failures
            StepError: For permanent failures
        """
        ...

    def run(self, shot: ShotInput, context: dict[str, Any], result: StepResult) -> str:
        """
        Run the step with retry logic and status tracking.

        Updates the StepResult in place with timing and state info.
        """
        result.state = JobState.PROCESSING
        result.started_at = result.started_at or _now()

        max_retries = self.config.max_retries
        base_delay = self.config.retry_base_delay_sec

        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            result.attempts = attempt
            try:
                logger.info(
                    "Step %s for shot %s: attempt %d/%d",
                    self.step_name.value, shot.shot_id, attempt, max_retries,
                )
                output_url = self.execute(shot, context)
                result.state = JobState.COMPLETE
                result.completed_at = _now()
                result.output_url = output_url
                result.duration_sec = (result.completed_at - result.started_at).total_seconds()
                return output_url

            except StepTransientError as e:
                last_error = e
                logger.warning(
                    "Step %s transient error (attempt %d/%d): %s",
                    self.step_name.value, attempt, max_retries, e,
                )
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.info("Retrying in %.1fs", delay)
                    time.sleep(delay)

            except StepError as e:
                result.state = JobState.FAILED
                result.completed_at = _now()
                result.error = str(e)
                result.duration_sec = (result.completed_at - result.started_at).total_seconds()
                raise

            except Exception as e:
                last_error = e
                logger.exception("Step %s unexpected error", self.step_name.value)
                if attempt < max_retries:
                    time.sleep(base_delay)

        # All retries exhausted
        result.state = JobState.FAILED
        result.completed_at = _now()
        result.error = f"Failed after {max_retries} attempts: {last_error}"
        result.duration_sec = (result.completed_at - result.started_at).total_seconds()
        raise StepError(result.error)


def _now():
    from datetime import datetime
    return datetime.utcnow()
