from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROJECT_ENDPOINT = (
    "https://mcasalaina-4iqs-2612-resource.services.ai.azure.com/api/projects/"
    "mcasalaina-4iqs-2612"
)
DEFAULT_MODEL = "gpt-5.4-mini"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    model: str
    approval_timeout_seconds: float

    @classmethod
    def load(cls, root: Path | None = None) -> Settings:
        project_root = root or Path.cwd()
        _load_dotenv(project_root / ".env")
        try:
            approval_timeout = float(os.getenv("APPROVAL_TIMEOUT_SECONDS", "300"))
        except ValueError as exc:
            raise ValueError("APPROVAL_TIMEOUT_SECONDS must be a positive number.") from exc
        if not math.isfinite(approval_timeout) or approval_timeout <= 0:
            raise ValueError("APPROVAL_TIMEOUT_SECONDS must be a positive number.")
        return cls(
            project_endpoint=(
                os.getenv("FOUNDRY_PROJECT_ENDPOINT")
                or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
                or DEFAULT_PROJECT_ENDPOINT
            ),
            model=(
                os.getenv("FOUNDRY_MODEL")
                or os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME")
                or DEFAULT_MODEL
            ),
            approval_timeout_seconds=approval_timeout,
        )
