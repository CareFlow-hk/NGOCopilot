from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ngopilot_gateway.config import Settings


def test_websocket_ticket_url_uses_secure_scheme() -> None:
    settings = Settings(
        app_env="test",
        public_api_url="https://api.example.test/base",
        allowed_origins="https://app.example.test",
    )

    assert settings.websocket_ticket_url("ticket-value") == (
        "wss://api.example.test/base/acp?ticket=ticket-value"
    )


def test_production_requires_cloud_secrets() -> None:
    with pytest.raises(ValidationError, match="missing production settings"):
        Settings(
            app_env="production",
            public_api_url="https://api.example.test",
            allowed_origins="https://app.example.test",
        )


def service_account_json(project_id: str = "ngopilot-project") -> str:
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project_id,
            "private_key": "-----BEGIN PRIVATE KEY-----\ntest\n-----END PRIVATE KEY-----\n",
            "client_email": f"storage@{project_id}.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def test_production_accepts_complete_gcs_configuration() -> None:
    settings = Settings(
        app_env="production",
        public_api_url="https://api.example.test",
        allowed_origins="https://app.example.test",
        database_url="postgresql://example.test/ngopilot",
        foundry_api_key="model-secret",
        gcs_bucket="ngopilot-prod-example",
        gcp_project_id="ngopilot-project",
        gcp_service_account_json=service_account_json(),
    )

    assert settings.gcs_configured is True


def test_production_requires_process_idle_grace() -> None:
    with pytest.raises(
        ValidationError, match="NGOPILOT_PROCESS_IDLE_SECONDS must be positive in production"
    ):
        Settings(
            app_env="production",
            public_api_url="https://api.example.test",
            allowed_origins="https://app.example.test",
            database_url="postgresql://example.test/ngopilot",
            foundry_api_key="model-secret",
            gcs_bucket="ngopilot-prod-example",
            gcp_project_id="ngopilot-project",
            gcp_service_account_json=service_account_json(),
            ngopilot_process_idle_seconds=0,
        )


def test_gcs_credentials_must_be_service_account_json() -> None:
    with pytest.raises(ValidationError, match="service-account credential"):
        Settings(app_env="test", gcp_service_account_json="{}")


def test_gcs_credentials_must_match_project() -> None:
    with pytest.raises(ValidationError, match="project_id must match"):
        Settings(
            app_env="production",
            public_api_url="https://api.example.test",
            allowed_origins="https://app.example.test",
            database_url="postgresql://example.test/ngopilot",
            foundry_api_key="model-secret",
            gcs_bucket="ngopilot-prod-example",
            gcp_project_id="ngopilot-project",
            gcp_service_account_json=service_account_json("another-project"),
        )


@pytest.mark.parametrize(
    "origin",
    ["*", "https://app.example.test/path", "https://app.example.test?query=1"],
)
def test_cors_requires_exact_origins(origin: str) -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(
            app_env="test",
            public_api_url="https://api.example.test",
            allowed_origins=origin,
        )
