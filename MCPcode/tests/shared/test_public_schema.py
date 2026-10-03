import jsonschema
import pytest

from ngopilot_mcp.host.server import create_server


@pytest.mark.asyncio
async def test_agent_can_discover_operation_inputs_without_guessing(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("NGOPILOT_MCP_STATE_DIR", str(tmp_path))
    tools = {tool.name: tool for tool in await create_server().list_tools()}
    calls = {
        "careflow_meeting_notes": {
            "operation": "start",
            "input": {
                "title": "Test",
                "mode": "internal_meeting",
                "audio_path": "/a.wav",
                "template_path": "/t.docx",
            },
        },
        "careflow_government_forms": {"operation": "list_templates"},
        "roster_copilot": {"operation": "status", "job_id": "job_1"},
        "careflow_paper_forms_to_excel": {
            "operation": "review",
            "job_id": "job_1",
            "input": {"confirm_all": True},
        },
    }
    for name, call in calls.items():
        schema = tools[name].inputSchema
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(call, schema)
        assert schema["properties"]["input"]["properties"]
    assert (
        "audio_path"
        in tools["careflow_meeting_notes"].inputSchema["properties"]["input"][
            "properties"
        ]
    )
    assert (
        "source"
        in tools["careflow_government_forms"].inputSchema["properties"]["input"][
            "properties"
        ]
    )
    assert (
        "hc_workbook_path"
        in tools["roster_copilot"].inputSchema["properties"]["input"]["properties"]
    )
