"""Runtime provider adapter for the immutable CareFlow dependency."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from functools import lru_cache, wraps
from types import ModuleType
from typing import Any

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_TEXT_MODEL = "moonshotai/kimi-k2.6"
DEFAULT_OPENROUTER_VISION_MODEL = "openai/gpt-4.1-mini"
PROVIDER_NAME = "openrouter"
_READINESS_SENTINEL = "provided-by-ngopilot-adapter"
_RESULT_FUNCTIONS = {
    "extract_volunteer_form": "vision",
    "auto_complete_fields": "vision",
    "review_volunteer_extraction": "text",
}

ClientFactory = Callable[..., Any]


class CareFlowLLMAdapter:
    """Installed OpenRouter bridge plus late-import module binding helpers."""

    def __init__(
        self,
        *,
        enabled: bool,
        text_model: str,
        vision_model: str,
        get_text_client: Callable[[], Any],
        get_vision_client: Callable[[], Any],
        resolve_model: Callable[[str], str],
        vision_response_model: ContextVar[str | None] | None = None,
    ) -> None:
        self.enabled = enabled
        self.provider = PROVIDER_NAME if enabled else "native"
        # ``model`` remains the text-model alias used by meeting-note metadata.
        self.model = text_model
        self.text_model = text_model
        self.vision_model = vision_model
        self._get_text_client = get_text_client
        self._get_vision_client = get_vision_client
        self._resolve_model = resolve_model
        self._vision_response_model = vision_response_model

    def bind(self, *modules: ModuleType) -> None:
        """Rebind functions copied from CareFlow's client during module import."""
        if not self.enabled:
            return
        for module in modules:
            namespace = vars(module)
            if "get_text_client" in namespace:
                module.get_text_client = self._get_text_client
            if "get_vision_client" in namespace:
                module.get_vision_client = self._get_vision_client
                # CareFlow 0.4.8's vision auto-complete path references this
                # legacy name without importing it.
                module.get_client = self._get_vision_client
            if "resolve_model" in namespace:
                module.resolve_model = self._resolve_model
            for name, kind in _RESULT_FUNCTIONS.items():
                self._wrap_result_metadata(module, name, kind)

    def _wrap_result_metadata(self, module: ModuleType, name: str, kind: str) -> None:
        function = getattr(module, name, None)
        if not callable(function) or getattr(function, "_ngopilot_adapted", False):
            return

        @wraps(function)
        def adapted(*args: Any, **kwargs: Any) -> Any:
            if kind == "vision" and self._vision_response_model is not None:
                self._vision_response_model.set(None)
            result = function(*args, **kwargs)
            if isinstance(result, dict):
                metadata = result.get("_meta")
                if isinstance(metadata, dict) and metadata.get("provider") not in {
                    "mock",
                    "noop",
                }:
                    metadata["provider"] = PROVIDER_NAME
                    requested_model = (
                        self.vision_model if kind == "vision" else self.text_model
                    )
                    actual_model = requested_model
                    if kind == "vision" and self._vision_response_model is not None:
                        actual_model = (
                            self._vision_response_model.get() or requested_model
                        )
                    metadata["model"] = actual_model
                    if actual_model != requested_model:
                        metadata["requested_model"] = requested_model
            return result

        adapted._ngopilot_adapted = True  # type: ignore[attr-defined]
        setattr(module, name, adapted)


def install_careflow_llm_adapter(
    settings: Any,
    client_module: ModuleType,
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> CareFlowLLMAdapter:
    """Route CareFlow text and vision through the agent's OpenRouter client."""
    env = os.environ if environ is None else environ
    api_key = env.get("OPENROUTER_API_KEY", "").strip()
    text_model = env.get("GOOSE_MODEL", "").strip() or DEFAULT_OPENROUTER_TEXT_MODEL
    vision_model = (
        env.get("CAREFLOW_VISION_MODEL", "").strip() or DEFAULT_OPENROUTER_VISION_MODEL
    )
    native_resolve_model = client_module.resolve_model

    if not api_key:
        return CareFlowLLMAdapter(
            enabled=False,
            text_model=text_model,
            vision_model=vision_model,
            get_text_client=client_module.get_text_client,
            get_vision_client=client_module.get_vision_client,
            resolve_model=native_resolve_model,
        )

    base_url = (
        env.get("OPENROUTER_BASE_URL", "").strip() or DEFAULT_OPENROUTER_BASE_URL
    ).rstrip("/")
    factory = client_factory or _openrouter_client
    vision_response_model: ContextVar[str | None] = ContextVar(
        "careflow_vision_response_model", default=None
    )

    @lru_cache(maxsize=1)
    def get_text_client() -> Any:
        return factory(api_key=api_key, base_url=base_url)

    @lru_cache(maxsize=1)
    def get_vision_client() -> Any:
        models = tuple(dict.fromkeys((vision_model, text_model)))
        return _VisionRoutingClient(
            get_text_client(),
            models=models,
            response_model=vision_response_model,
        )

    def resolve_model(kind: str) -> str:
        if kind == "text":
            return text_model
        if kind == "vision":
            return vision_model
        return native_resolve_model(kind)

    client_module.get_text_client = get_text_client
    client_module.get_vision_client = get_vision_client
    client_module.get_client = lambda provider=None: get_text_client()
    client_module.resolve_model = resolve_model

    # CareFlow's mock switches still inspect its retired provider settings.
    # Sentinels enable the native code paths without duplicating the real key.
    settings.deepseek_api_key = _READINESS_SENTINEL
    settings.azure_openai_api_key = _READINESS_SENTINEL
    settings.azure_openai_endpoint = base_url
    settings.deepseek_text_model = text_model
    settings.openai_vision_model = vision_model
    settings.azure_openai_model = vision_model
    settings.azure_openai_deployment = vision_model
    settings.llm_text_model = text_model
    settings.llm_vision_model = vision_model

    return CareFlowLLMAdapter(
        enabled=True,
        text_model=text_model,
        vision_model=vision_model,
        get_text_client=get_text_client,
        get_vision_client=get_vision_client,
        resolve_model=resolve_model,
        vision_response_model=vision_response_model,
    )


class _VisionRoutingCompletions:
    def __init__(
        self,
        inner: Any,
        *,
        models: tuple[str, ...],
        response_model: ContextVar[str | None],
    ) -> None:
        self._inner = inner
        self._models = models
        self._response_model = response_model

    def create(self, **kwargs: Any) -> Any:
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body.update({"models": list(self._models), "route": "fallback"})
        kwargs["extra_body"] = extra_body
        response = self._inner.create(**kwargs)
        model = getattr(response, "model", None)
        if isinstance(model, str) and model:
            self._response_model.set(model)
        return response


class _VisionRoutingChat:
    def __init__(
        self,
        inner: Any,
        *,
        models: tuple[str, ...],
        response_model: ContextVar[str | None],
    ) -> None:
        self.completions = _VisionRoutingCompletions(
            inner.completions,
            models=models,
            response_model=response_model,
        )


class _VisionRoutingClient:
    """Inject OpenRouter's ordered GPT-to-agent-model fallback route."""

    def __init__(
        self,
        inner: Any,
        *,
        models: tuple[str, ...],
        response_model: ContextVar[str | None],
    ) -> None:
        self._inner = inner
        self._models = models
        self._response_model = response_model
        self.chat = _VisionRoutingChat(
            inner.chat,
            models=models,
            response_model=response_model,
        )

    def with_options(self, **kwargs: Any) -> _VisionRoutingClient:
        return _VisionRoutingClient(
            self._inner.with_options(**kwargs),
            models=self._models,
            response_model=self._response_model,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _openrouter_client(*, api_key: str, base_url: str) -> Any:
    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=180.0,
        max_retries=0,
    )
