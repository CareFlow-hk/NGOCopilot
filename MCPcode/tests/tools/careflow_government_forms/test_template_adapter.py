import json
from copy import deepcopy
from pathlib import Path

from ngopilot_mcp.tools.careflow_government_forms.template_adapter import (
    corrected_template,
    require_manual_signature_date,
)


def test_joyyou_declaration_date_never_uses_birth_date():
    path = (
        Path(__file__).resolve().parents[3]
        / "src/ngopilot_mcp/payloads/careflow/backend/data/form_templates/joyyou.json"
    )
    original = json.loads(path.read_text())
    before = deepcopy(original)
    corrected = corrected_template(original)
    assert original == before
    assert not any(field["key"].startswith("dob_") for field in corrected["fields"])
    fields = {field["key"]: field for field in corrected["fields"]}
    assert fields["signature_date_year"]["elder_profile_path"] == "signature_date.year"
    preview = {
        "mappings": [
            {
                "key": "signature_date_year",
                "value": "1950",
                "source": "llm",
                "confidence": 0.9,
            },
            {"key": "family_name_en", "value": "TEST", "source": "direct"},
        ],
        "summary": {},
    }
    require_manual_signature_date("joyyou", preview)
    assert preview["mappings"][0]["value"] == ""
    assert preview["mappings"][1]["value"] == "TEST"
    assert preview["summary"]["missing"] == 1 and preview["summary"]["llm"] == 0


def test_other_form_is_unchanged():
    template = {
        "id": "oala",
        "fields": [{"key": "dob_year", "elder_profile_path": "date_of_birth.year"}],
    }
    assert corrected_template(template) is template
