"""Single Foundry deployment for text and image inference; never falls back."""

from __future__ import annotations

import os
from types import SimpleNamespace
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = "https://CareFlow-VPS.services.ai.azure.com/openai/v1"
DEFAULT_MODEL = "gpt-6-luna"


def configuration(environ=None):
    env = os.environ if environ is None else environ
    endpoint = (env.get("FOUNDRY_ENDPOINT") or DEFAULT_ENDPOINT).rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith((".services.ai.azure.com", ".openai.azure.com"))
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("FOUNDRY_ENDPOINT 必須是 Azure Foundry 的 HTTPS 模型接口。")
    if parsed.path in ("", "/"):
        endpoint += "/openai/v1"
    elif parsed.path != "/openai/v1":
        raise ValueError("請使用 /openai/v1 模型接口，而非 /api/projects 項目地址。")
    model = (env.get("FOUNDRY_DEPLOYMENT") or DEFAULT_MODEL).strip()
    return endpoint, model, env.get("FOUNDRY_API_KEY", "").strip()


class FoundryClient:
    """Adapt legacy non-tool Chat Completions callers to Responses text/images."""

    def __init__(self, *, environ=None, client=None):
        self.endpoint, self.model, self.key = configuration(environ)
        self._client = client
        self.chat = SimpleNamespace(completions=self)

    def with_options(self, **kwargs):
        return self  # bounded timeout/retries are owned by this adapter

    def create(self, **kwargs):
        if self._client is None:
            if not self.key:
                raise RuntimeError("尚未設定 Foundry API Key；沒有呼叫其他模型。")
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.key, base_url=self.endpoint, timeout=180, max_retries=0
            )
        messages = []
        for message in kwargs.get("messages", []):
            role = message["role"]
            content = message.get("content", "")
            if isinstance(content, list):
                converted = []
                for part in content:
                    if part.get("type") == "text":
                        converted.append({"type": "input_text", "text": part["text"]})
                    elif part.get("type") == "image_url":
                        image = part["image_url"]
                        converted.append(
                            {
                                "type": "input_image",
                                "image_url": image["url"],
                                "detail": image.get("detail", "auto"),
                            }
                        )
                    else:
                        raise ValueError(
                            "Luna 工具只接受文字與圖片；錄音請先提供轉寫文字稿。"
                        )
                content = converted
            messages.append({"role": role, "content": content})
        body = {
            "model": self.model,
            "input": messages,
            "store": False,
            "max_output_tokens": max(
                8000,
                int(
                    kwargs.get("max_completion_tokens")
                    or kwargs.get("max_tokens")
                    or 16000
                ),
            ),
        }
        if kwargs.get("response_format", {}).get("type") == "json_object":
            body["text"] = {"format": {"type": "json_object"}}
        try:
            response = self._client.responses.create(**body)
        except Exception as error:
            code = getattr(error, "status_code", None)
            raise RuntimeError(
                f"Foundry Luna 請求失敗{f'（HTTP {code}）' if code else ''}；請檢查設定、配額或連線。沒有切換到其他模型。"
            ) from None
        text = getattr(response, "output_text", "")
        if getattr(response, "status", None) != "completed" or not text.strip():
            raise RuntimeError(
                "Foundry Luna 結果不完整或為空；請重試，沒有儲存假結果。"
            )
        choice = SimpleNamespace(
            message=SimpleNamespace(content=text), finish_reason="stop"
        )
        if kwargs.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
                    )
                ]
            )
        return SimpleNamespace(
            choices=[choice],
            model=response.model,
            usage=getattr(response, "usage", None),
        )
