import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.shared.human_confirmation import HumanConfirmations


def test_agent_cannot_confirm_or_change_approved_values(tmp_path):
    approvals = HumanConfirmations(tmp_path)
    task = dict(tool="test", job_id="job_1", operation="review")
    revision = {"source": "original"}
    with pytest.raises(ToolError, match="confirm"):
        approvals.require(**task, payload={"name": "draft"}, revision=revision)
    assert approvals.proposal(**task, revision=revision) == {"name": "draft"}
    approvals.grant(
        **task, payload={"name": "corrected"}, revision=revision, reviewer="Tester"
    )
    approvals.require(**task, payload={"name": "corrected"}, revision=revision)
    with pytest.raises(ToolError):
        approvals.require(**task, payload={"name": "draft"}, revision=revision)
    with pytest.raises(ToolError):
        approvals.require(
            **task, payload={"name": "corrected"}, revision={"source": "changed"}
        )
    with pytest.raises(ToolError):
        approvals.require(
            **{**task, "job_id": "job_2"},
            payload={"name": "corrected"},
            revision=revision,
        )
