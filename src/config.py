"""
Pipeline configuration loaded from environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class ServiceEndpoint:
    """Configuration for an external AI service."""
    url: str
    api_key: str
    timeout_sec: int = 300
    max_retries: int = 3


@dataclass
class StorageConfig:
    """S3-compatible storage configuration."""
    bucket: str
    access_key: str
    secret_key: str
    endpoint: str
    region: str = "auto"


@dataclass
class PipelineConfig:
    """Top-level pipeline configuration."""
    comfyui: ServiceEndpoint
    minimax: ServiceEndpoint
    storage: StorageConfig
    max_concurrent_shots: int = 3
    max_retries: int = 3
    retry_base_delay_sec: float = 2.0
    webhook_url: str | None = None
    log_level: str = "INFO"
    ffmpeg_path: str = "ffmpeg"

    @classmethod
    def from_env(cls) -> PipelineConfig:
        """Load configuration from environment variables."""
        return cls(
            comfyui=ServiceEndpoint(
                url=os.environ["COMFYUI_ENDPOINT"],
                api_key=os.environ["COMFYUI_API_KEY"],
                timeout_sec=int(os.environ.get("COMFYUI_TIMEOUT", "300")),
            ),
            minimax=ServiceEndpoint(
                url=os.environ.get("MINIMAX_ENDPOINT", "https://api.minimaxi.chat/v1"),
                api_key=os.environ["MINIMAX_API_KEY"],
                timeout_sec=int(os.environ.get("MINIMAX_TIMEOUT", "300")),
            ),
            storage=StorageConfig(
                bucket=os.environ["S3_BUCKET"],
                access_key=os.environ["S3_ACCESS_KEY"],
                secret_key=os.environ["S3_SECRET_KEY"],
                endpoint=os.environ["S3_ENDPOINT"],
                region=os.environ.get("S3_REGION", "auto"),
            ),
            max_concurrent_shots=int(os.environ.get("MAX_CONCURRENT_SHOTS", "3")),
            max_retries=int(os.environ.get("MAX_RETRIES", "3")),
            webhook_url=os.environ.get("WEBHOOK_URL"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
