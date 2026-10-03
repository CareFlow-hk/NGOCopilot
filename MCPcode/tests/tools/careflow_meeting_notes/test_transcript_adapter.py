import pytest
from ngopilot_mcp.tools.careflow_meeting_notes.transcript_adapter import read_transcript
from ngopilot_mcp.tools.careflow_meeting_notes.validation import validate_start_files
from ngopilot_mcp.tools.careflow_meeting_notes.schemas import StartInput


def test_supplied_transcript_is_preserved_and_audio_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "meeting.txt"
    path.write_text("房間未確認。\n統籌：十月六日前核對。", encoding="utf-8-sig")
    assert read_transcript(str(path)) == "房間未確認。\n統籌：十月六日前核對。"
    with pytest.raises(ValueError, match="不支援錄音"):
        read_transcript(str(tmp_path / "meeting.wav"))
    monkeypatch.setenv("NGOPILOT_AI_PROVIDER", "foundry")
    with pytest.raises(ValueError, match="不支援錄音"):
        validate_start_files(
            StartInput(
                title="test",
                mode="internal_meeting",
                audio_path=str(tmp_path / "meeting.wav"),
                template_path=str(tmp_path / "template.docx"),
            )
        )
