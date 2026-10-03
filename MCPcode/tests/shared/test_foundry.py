from types import SimpleNamespace as NS
import pytest
from ngopilot_mcp.shared.foundry import FoundryClient, configuration


def test_responses_uses_one_deployment_and_no_legacy_fallback():
    calls = []

    def create(**kw):
        calls.append(kw)
        return NS(
            status="completed",
            output_text='{"name":"TEST"}',
            model="gpt-6-luna",
            usage=None,
        )

    client = FoundryClient(
        environ={"FOUNDRY_API_KEY": "test-key", "DEEPSEEK_API_KEY": "old"},
        client=NS(responses=NS(create=create)),
    )
    result = client.create(
        model="legacy-model",
        temperature=0.1,
        max_tokens=1500,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract JSON"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA=="},
                    },
                ],
            }
        ],
    )
    assert result.choices[0].message.content == '{"name":"TEST"}'
    assert calls[0]["model"] == "gpt-6-luna"
    assert calls[0]["store"] is False
    assert calls[0]["input"][0]["content"][1]["type"] == "input_image"
    assert "temperature" not in calls[0] and "extra_body" not in calls[0]
    assert calls[0]["max_output_tokens"] >= 8000
    assert next(client.create(messages=[], stream=True)).choices[0].delta.content


def test_missing_key_never_uses_other_provider_credentials():
    client = FoundryClient(
        environ={
            "DEEPSEEK_API_KEY": "old",
            "OPENROUTER_API_KEY": "old",
            "AZURE_OPENAI_API_KEY": "old",
        }
    )
    with pytest.raises(RuntimeError, match="尚未設定"):
        client.create(messages=[])


@pytest.mark.parametrize("status,text", [("incomplete", "partial"), ("completed", "")])
def test_incomplete_results_are_not_accepted(status, text):
    client = FoundryClient(
        environ={},
        client=NS(
            responses=NS(create=lambda **kw: NS(status=status, output_text=text))
        ),
    )
    with pytest.raises(RuntimeError, match="不完整"):
        client.create(messages=[])


def test_credential_bearing_endpoint_is_validated():
    for endpoint in (
        "https://example.com/openai/v1",
        "https://careflow-vps.services.ai.azure.com/api/projects/CareFlow-VPS",
        "http://careflow-vps.services.ai.azure.com/openai/v1",
    ):
        with pytest.raises(ValueError):
            configuration({"FOUNDRY_ENDPOINT": endpoint})
