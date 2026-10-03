"""Environment-only gateway configuration."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "production"
    port: int = Field(default=8080, ge=1, le=65535)
    data_root: Path = Path("/data")
    public_api_url: str = "http://127.0.0.1:8080"
    allowed_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    goose_provider: str = "openrouter"
    goose_model: str = "moonshotai/kimi-k2.6"
    careflow_vision_model: str = "qwen/qwen3-vl-32b-instruct"
    openrouter_api_key: str = ""
    ngopilot_bin: str = "ngopilot"
    ngopilot_mcp_bin: str = "ngopilot-mcp"
    ngopilot_mcp_shared_state_dir: Path = Path("/opt/ngopilot/shared")
    ngopilot_process_startup_seconds: float = Field(default=90, gt=0, le=600)
    ngopilot_process_idle_seconds: float = Field(default=900, ge=0, le=86400)

    database_url: str = ""
    database_pool_min_size: int = Field(default=1, ge=1, le=20)
    database_pool_max_size: int = Field(default=10, ge=1, le=100)
    auth_token_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    ws_ticket_ttl_seconds: int = Field(default=60, ge=5, le=300)
    registration_enabled: bool = True

    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    upload_resolve_timeout_seconds: float = Field(default=30, ge=0, le=300)
    gcs_bucket: str = ""
    gcp_project_id: str = ""
    gcp_service_account_json: SecretStr = SecretStr("")

    @field_validator("data_root", "ngopilot_mcp_shared_state_dir")
    @classmethod
    def absolute_paths(cls, value: Path) -> Path:
        path = value.expanduser()
        if not path.is_absolute():
            raise ValueError("must be an absolute path")
        return path

    @field_validator("public_api_url")
    @classmethod
    def valid_public_url(cls, value: str) -> str:
        parsed = urlsplit(value.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute HTTP(S) URL")
        if parsed.query or parsed.fragment:
            raise ValueError("must not contain a query string or fragment")
        return value.rstrip("/")

    @field_validator("gcs_bucket")
    @classmethod
    def valid_gcs_bucket(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", value):
            raise ValueError("must be a valid 3-63 character GCS bucket name")
        return value

    @field_validator("gcp_project_id")
    @classmethod
    def valid_gcp_project_id(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", value):
            raise ValueError("must be a valid 6-30 character Google Cloud project ID")
        return value

    @field_validator("gcp_service_account_json")
    @classmethod
    def valid_service_account_json(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw:
            return value
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("must contain valid JSON") from error
        required = {"type", "project_id", "private_key", "client_email", "token_uri"}
        if not isinstance(info, dict) or required - info.keys():
            raise ValueError("must contain a complete Google service-account credential")
        if info["type"] != "service_account":
            raise ValueError("must be a Google service-account credential")
        if not isinstance(info["private_key"], str) or not info["private_key"].startswith(
            "-----BEGIN PRIVATE KEY-----"
        ):
            raise ValueError("must contain a service-account private key")
        if not isinstance(info["client_email"], str) or not info["client_email"].endswith(
            ".gserviceaccount.com"
        ):
            raise ValueError("must contain a service-account email")
        return value

    @field_validator("app_env")
    @classmethod
    def valid_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "development", "test", "production"}:
            raise ValueError("must be local, development, test, or production")
        return normalized

    @field_validator("database_pool_max_size")
    @classmethod
    def valid_pool_size(cls, value: int, info: object) -> int:
        # Cross-field validation is also performed by asyncpg; keep the error local.
        minimum = getattr(info, "data", {}).get("database_pool_min_size", 1)
        if value < minimum:
            raise ValueError("must be at least DATABASE_POOL_MIN_SIZE")
        return value

    @model_validator(mode="after")
    def valid_deployment(self) -> "Settings":
        origins = self.cors_origins
        if not origins:
            raise ValueError("ALLOWED_ORIGINS must include at least one exact origin")
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or origin == "*"
            ):
                raise ValueError(f"ALLOWED_ORIGINS contains an invalid origin: {origin}")

        if self.app_env == "production":
            if self.ngopilot_process_idle_seconds <= 0:
                raise ValueError("NGOPILOT_PROCESS_IDLE_SECONDS must be positive in production")
            service_account_json = self.gcp_service_account_json.get_secret_value()
            required = {
                "DATABASE_URL": self.database_url,
                "OPENROUTER_API_KEY": self.openrouter_api_key,
                "GCS_BUCKET": self.gcs_bucket,
                "GCP_PROJECT_ID": self.gcp_project_id,
                "GCP_SERVICE_ACCOUNT_JSON": service_account_json,
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError("missing production settings: " + ", ".join(missing))
            if self.gcp_service_account_info["project_id"] != self.gcp_project_id:
                raise ValueError("GCP_SERVICE_ACCOUNT_JSON project_id must match GCP_PROJECT_ID")
            if self.goose_provider != "openrouter":
                raise ValueError("GOOSE_PROVIDER must be openrouter in production")
            if self.goose_model != "moonshotai/kimi-k2.6":
                raise ValueError("GOOSE_MODEL must be moonshotai/kimi-k2.6 in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        origins = [item.strip().rstrip("/") for item in self.allowed_origins.split(",")]
        return [item for item in origins if item]

    def websocket_ticket_url(self, ticket: str) -> str:
        parsed = urlsplit(self.public_api_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"{parsed.path.rstrip('/')}/acp"
        return urlunsplit((scheme, parsed.netloc, path, f"ticket={ticket}", ""))

    @property
    def gcs_configured(self) -> bool:
        return bool(
            self.gcs_bucket
            and self.gcp_project_id
            and self.gcp_service_account_json.get_secret_value()
        )

    @property
    def gcp_service_account_info(self) -> dict[str, Any]:
        value = json.loads(self.gcp_service_account_json.get_secret_value())
        if not isinstance(value, dict):
            raise ValueError("GCP_SERVICE_ACCOUNT_JSON must contain a JSON object")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
