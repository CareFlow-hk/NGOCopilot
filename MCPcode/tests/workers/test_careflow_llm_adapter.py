from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Any

from ngopilot_mcp.workers.careflow_llm_adapter import (
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_OPENROUTER_VISION_MODEL,
    install_careflow_llm_adapter,
)


def _native_client_module() -> ModuleType:
    module = ModuleType("careflow_client")
    module.get_text_client = lambda: "native-text"
    module.get_vision_client = lambda: "native-vision"
    module.get_client = lambda provider=None: "native-legacy"
    module.resolve_model = lambda kind: f"native-{kind}"
    return module


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        deepseek_api_key="",
        azure_openai_api_key="",
        azure_openai_endpoint="",
        deepseek_text_model="native-text",
        openai_vision_model="native-vision",
        azure_openai_model="native-vision",
        azure_openai_deployment="native-vision",
        llm_text_model="native-text",
        llm_vision_model="native-vision",
    )


def _fake_client(
    calls: list[dict[str, Any]], *, response_model: str = "moonshotai/kimi-k2.6"
) -> SimpleNamespace:
    def create(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(model=response_model)

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


def test_shared_agent_key_routes_text_and_vision_to_separate_models() -> None:
    client_module = _native_client_module()
    settings = _settings()
    factory_calls: list[dict[str, str]] = []
    completion_calls: list[dict[str, Any]] = []
    shared_client = _fake_client(completion_calls)

    def client_factory(**kwargs: str) -> object:
        factory_calls.append(kwargs)
        return shared_client

    adapter = install_careflow_llm_adapter(
        settings,
        client_module,
        environ={
            "OPENROUTER_API_KEY": "test-key",
            "GOOSE_MODEL": "moonshotai/kimi-k2.6",
        },
        client_factory=client_factory,
    )

    assert adapter.enabled is True
    assert adapter.provider == "openrouter"
    assert adapter.model == "moonshotai/kimi-k2.6"
    assert adapter.vision_model == DEFAULT_OPENROUTER_VISION_MODEL
    assert client_module.get_text_client() is shared_client
    assert client_module.get_client() is shared_client
    vision_client = client_module.get_vision_client()
    assert vision_client is not shared_client
    response = vision_client.chat.completions.create(
        model=client_module.resolve_model("vision"),
        messages=[],
    )
    assert response.model == "moonshotai/kimi-k2.6"
    assert factory_calls == [
        {"api_key": "test-key", "base_url": DEFAULT_OPENROUTER_BASE_URL}
    ]
    assert completion_calls == [
        {
            "model": DEFAULT_OPENROUTER_VISION_MODEL,
            "messages": [],
            "extra_body": {
                "models": [
                    DEFAULT_OPENROUTER_VISION_MODEL,
                    "moonshotai/kimi-k2.6",
                ],
                "route": "fallback",
            },
        }
    ]
    assert client_module.resolve_model("text") == "moonshotai/kimi-k2.6"
    assert client_module.resolve_model("vision") == DEFAULT_OPENROUTER_VISION_MODEL
    assert client_module.resolve_model("asr") == "native-asr"
    assert settings.deepseek_api_key == "provided-by-ngopilot-adapter"
    assert settings.azure_openai_api_key == "provided-by-ngopilot-adapter"


def test_missing_agent_key_preserves_native_careflow_routes() -> None:
    client_module = _native_client_module()
    settings = _settings()

    adapter = install_careflow_llm_adapter(
        settings,
        client_module,
        environ={"GOOSE_MODEL": "moonshotai/kimi-k2.6"},
    )

    assert adapter.enabled is False
    assert client_module.get_text_client() == "native-text"
    assert client_module.get_vision_client() == "native-vision"
    assert settings.deepseek_api_key == ""
    assert settings.azure_openai_api_key == ""


def test_late_bound_vision_functions_use_adapter_and_report_openrouter() -> None:
    client_module = _native_client_module()
    completion_calls: list[dict[str, Any]] = []
    adapter = install_careflow_llm_adapter(
        _settings(),
        client_module,
        environ={
            "OPENROUTER_API_KEY": "test-key",
            "GOOSE_MODEL": "moonshotai/kimi-k2.6",
            "CAREFLOW_VISION_MODEL": "qwen/qwen3-vl-32b-instruct",
        },
        client_factory=lambda **kwargs: _fake_client(completion_calls),
    )
    vision = ModuleType("app.llm.vision")
    vision.get_vision_client = lambda: "native-vision"
    vision.resolve_model = lambda kind: f"native-{kind}"

    def extract() -> dict[str, Any]:
        client = vision.get_vision_client()
        client.chat.completions.create(
            model=vision.resolve_model("vision"),
            messages=[],
        )
        return {"_meta": {"provider": "azure_openai", "model": "legacy"}}

    vision.extract_volunteer_form = extract

    adapter.bind(vision)
    result = vision.extract_volunteer_form()

    assert vision.get_vision_client() is vision.get_client()
    assert vision.resolve_model("vision") == "qwen/qwen3-vl-32b-instruct"
    assert result["_meta"] == {
        "provider": "openrouter",
        "model": "moonshotai/kimi-k2.6",
        "requested_model": "qwen/qwen3-vl-32b-instruct",
    }
    assert completion_calls[0]["extra_body"] == {
        "models": ["qwen/qwen3-vl-32b-instruct", "moonshotai/kimi-k2.6"],
        "route": "fallback",
    }
