from types import SimpleNamespace

import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.tools.careflow_government_forms.provider_adapter import (
    ExtractionClient,
)


@pytest.mark.parametrize(
    "content,finish", [(None, "length"), ("", "stop"), ('{"name":', "length")]
)
def test_empty_or_truncated_response_is_not_a_successful_empty_profile(content, finish):
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason=finish
            )
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    with pytest.raises(ToolError, match="未完整"):
        ExtractionClient(client).create(max_tokens=1500)


def test_complete_profile_and_request_are_preserved():
    calls = []
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"name_en":{"family":"TEST"}}'),
                finish_reason="stop",
            )
        ]
    )

    def create(**kwargs):
        calls.append(kwargs)
        return response

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    assert (
        ExtractionClient(client).create(
            model="test",
            max_tokens=1500,
            messages=[{"role": "user", "content": "TEST"}],
        )
        is response
    )
    assert (
        calls[0]["max_tokens"] == 6000 and calls[0]["messages"][0]["content"] == "TEST"
    )
