# Video Pipeline Orchestrator

Python orchestration layer for AI-generated real estate marketing videos. Takes a structured shot list and chains: **image generation → face swap → video generation → lip sync → final assembly**.

## Pipeline Flow

```
                         Shot List (JSON)
                              │
                              ▼
┌──────────────────────────────────────────────────────────┐
│                    Pipeline Orchestrator                   │
│                                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │  Image    │  │  Face    │  │  Video   │  │  Lip     │ │
│  │  Gen      │─▶│  Swap    │─▶│  Gen     │─▶│  Sync    │ │
│  │ (ComfyUI) │  │(ComfyUI) │  │(Minimax) │  │(Minimax) │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘ │
│       │              │              │              │       │
│       ▼              ▼              ▼              ▼       │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Asset Storage (S3/R2)                   │  │
│  └─────────────────────────────────────────────────────┘  │
│                              │                             │
│                              ▼                             │
│                   ┌──────────────────┐                     │
│                   │  Video Assembly   │                     │
│                   │  (FFmpeg concat)  │                     │
│                   └──────────────────┘                     │
│                              │                             │
│                              ▼                             │
│                   ┌──────────────────┐                     │
│                   │  Webhook / S3    │                     │
│                   │  Delivery        │                     │
│                   └──────────────────┘                     │
└──────────────────────────────────────────────────────────┘
```

## Features

- **Step chaining** with dependency resolution between pipeline stages
- **Retry logic** with exponential backoff per step
- **Batch processing** with configurable concurrency limits
- **Job status tracking** with per-shot granularity
- **Webhook notifications** on completion/failure
- **Structured logging** with correlation IDs per job

## Project Structure

```
├── src/
│   ├── orchestrator.py     # Main pipeline orchestrator
│   ├── steps/
│   │   ├── base.py         # Abstract pipeline step
│   │   ├── image_gen.py    # ComfyUI image generation
│   │   ├── face_swap.py    # ComfyUI face swap
│   │   ├── video_gen.py    # Video generation (Minimax/Runway)
│   │   ├── lip_sync.py     # Lip sync with audio
│   │   └── assembly.py     # FFmpeg video assembly
│   ├── queue.py            # Job queue management
│   ├── config.py           # Service endpoint configuration
│   ├── models.py           # Data models
│   └── notifications.py    # Webhook delivery
├── examples/
│   ├── shot_list.json      # Example input
│   └── job_output.json     # Example output
└── tests/
    └── test_orchestrator.py
```

## Quick Start

```bash
pip install -r requirements.txt

# Configure services
export COMFYUI_ENDPOINT="https://api.runpod.ai/v2/your-endpoint-id"
export COMFYUI_API_KEY="rp_xxxxx"
export MINIMAX_API_KEY="your-minimax-key"
export S3_BUCKET="your-bucket"

# Run a pipeline
python -m src.orchestrator examples/shot_list.json
```

## Usage

### Programmatic

```python
from src.orchestrator import PipelineOrchestrator
from src.config import PipelineConfig

config = PipelineConfig.from_env()
orchestrator = PipelineOrchestrator(config)

# Submit a job
job = orchestrator.submit("examples/shot_list.json")
print(f"Job {job.id} submitted")

# Check status
status = orchestrator.get_status(job.id)
print(f"Status: {status.state}, Progress: {status.progress_pct}%")

# Wait for completion
result = orchestrator.wait(job.id, timeout=600)
print(f"Final video: {result.output_url}")
```

### Shot List Format

See `examples/shot_list.json` for the full schema.

The top-level `video_type` field selects a product preset: `realtor_profile`, `creative_realtor_profile`, `house_listing`, `avatar_property_tour`, or `zillow_explainer`. These correspond to Arclight Content's video product types.

Each shot specifies:

| Field | Type | Description |
|-------|------|-------------|
| `shot_id` | string | Unique shot identifier |
| `type` | enum | `scene`, `presenter`, `transition` |
| `prompt` | string | Image generation prompt |
| `duration_sec` | float | Shot duration in seconds |
| `voice_audio_url` | string? | Pre-generated TTS audio URL (see note below) |
| `agent_face_url` | string? | Reference face for swap |

> **Note on TTS audio:** This orchestrator does **not** generate text-to-speech audio. The `voice_audio_url` fields in the shot list point to pre-generated audio files produced by the client's existing Minimax TTS service. The orchestrator consumes these URLs as inputs for lip-sync and video assembly.

## Configuration

All configuration via environment variables or `PipelineConfig`:

| Variable | Description | Default |
|----------|-------------|---------|
| `COMFYUI_ENDPOINT` | RunPod ComfyUI endpoint URL | required |
| `COMFYUI_API_KEY` | RunPod API key | required |
| `MINIMAX_API_KEY` | Minimax API key for TTS/video | required |
| `S3_BUCKET` | Output storage bucket | required |
| `S3_ACCESS_KEY` | S3 credentials | required |
| `S3_SECRET_KEY` | S3 credentials | required |
| `S3_ENDPOINT` | S3 endpoint | required |
| `MAX_CONCURRENT_SHOTS` | Parallel shot processing | `3` |
| `MAX_RETRIES` | Retries per step | `3` |
| `WEBHOOK_URL` | Completion notification URL | optional |
| `LOG_LEVEL` | Logging verbosity | `INFO` |

## License

MIT
