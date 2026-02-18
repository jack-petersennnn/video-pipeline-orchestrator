"""
Tests for the pipeline orchestrator.

Uses mocked service endpoints to validate pipeline logic
without requiring live API access.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.config import PipelineConfig, ServiceEndpoint, StorageConfig
from src.models import ShotListInput, ShotInput, ShotType, JobState, StepName
from src.orchestrator import PipelineOrchestrator


@pytest.fixture
def config():
    return PipelineConfig(
        comfyui=ServiceEndpoint(url="https://mock-comfyui.test", api_key="test-key"),
        minimax=ServiceEndpoint(url="https://mock-minimax.test", api_key="test-key"),
        storage=StorageConfig(
            bucket="test-bucket",
            access_key="test",
            secret_key="test",
            endpoint="https://mock-s3.test",
        ),
        max_concurrent_shots=2,
        max_retries=1,
    )


@pytest.fixture
def shot_list():
    return ShotListInput(
        project_id="test-project",
        project_name="Test Property",
        agent_face_url="https://example.com/face.jpg",
        shots=[
            ShotInput(
                shot_id="shot-001",
                type=ShotType.SCENE,
                prompt="A beautiful kitchen",
                duration_sec=5.0,
            ),
            ShotInput(
                shot_id="shot-002",
                type=ShotType.PRESENTER,
                prompt="Agent presenting in living room",
                duration_sec=6.0,
                voice_audio_url="https://example.com/audio.mp3",
            ),
        ],
    )


def test_plan_steps_scene(config, shot_list):
    """Scene shots should get image_gen + video_gen."""
    orchestrator = PipelineOrchestrator(config)
    steps = orchestrator._plan_steps(shot_list.shots[0], shot_list)
    assert steps == [StepName.IMAGE_GEN, StepName.VIDEO_GEN]


def test_plan_steps_presenter(config, shot_list):
    """Presenter shots should get all four steps."""
    orchestrator = PipelineOrchestrator(config)
    steps = orchestrator._plan_steps(shot_list.shots[1], shot_list)
    assert steps == [
        StepName.IMAGE_GEN,
        StepName.FACE_SWAP,
        StepName.VIDEO_GEN,
        StepName.LIP_SYNC,
    ]


def test_plan_steps_presenter_no_face(config):
    """Presenter without face URL should skip face swap."""
    shot_list = ShotListInput(
        project_id="test",
        project_name="Test",
        shots=[
            ShotInput(
                shot_id="shot-001",
                type=ShotType.PRESENTER,
                prompt="Agent",
                voice_audio_url="https://example.com/audio.mp3",
            ),
        ],
    )
    orchestrator = PipelineOrchestrator(config)
    steps = orchestrator._plan_steps(shot_list.shots[0], shot_list)
    assert StepName.FACE_SWAP not in steps
    assert StepName.LIP_SYNC in steps


def test_job_initialization(config, shot_list):
    """Verify job status is correctly initialized."""
    orchestrator = PipelineOrchestrator(config)

    # Mock all external calls to prevent actual API calls
    with patch.object(orchestrator.image_gen, 'run', return_value="https://img.test/1.png"), \
         patch.object(orchestrator.face_swap, 'should_run', return_value=False), \
         patch.object(orchestrator.video_gen, 'run', return_value="https://vid.test/1.mp4"), \
         patch.object(orchestrator.lip_sync, 'should_run', return_value=False), \
         patch.object(orchestrator.assembly, 'assemble', return_value="https://final.test/out.mp4"):

        job = orchestrator.submit_shot_list(shot_list)

    assert job.project_id == "test-project"
    assert len(job.shots) == 2
    assert "shot-001" in job.shots
    assert "shot-002" in job.shots


def test_shot_list_parsing():
    """Verify shot list JSON parsing."""
    example_path = Path(__file__).parent.parent / "examples" / "shot_list.json"
    with open(example_path) as f:
        data = json.load(f)

    shot_list = ShotListInput(**data)
    assert shot_list.project_id == "prop-2024-oceanview"
    assert len(shot_list.shots) == 8

    presenter_shots = [s for s in shot_list.shots if s.type == ShotType.PRESENTER]
    assert len(presenter_shots) == 3
    assert all(s.voice_audio_url for s in presenter_shots)
