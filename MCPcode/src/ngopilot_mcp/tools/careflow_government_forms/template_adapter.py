"""Corrections to legacy template metadata, without changing the dependency.

The bundled JoyYou page 2 date line belongs to the declaration/signature. Its
legacy metadata incorrectly mapped date_of_birth onto that line.
"""

from copy import deepcopy

DATE_KEYS = {
    "dob_day": ("signature_date_day", "日"),
    "dob_month": ("signature_date_month", "月"),
    "dob_year": ("signature_date_year", "年"),
}
MANUAL_KEYS = {new for new, _ in DATE_KEYS.values()}


def corrected_template(template):
    if template.get("id") != "joyyou":
        return template
    result = deepcopy(template)
    for field in result.get("fields", []):
        if field.get("key") in DATE_KEYS:
            original = field["key"]
            field["key"], unit = DATE_KEYS[original]
            field["label_zh"] = f"簽署日期（{unit}；未簽署請留空）"
            field["elder_profile_path"] = "signature_date." + original.removeprefix(
                "dob_"
            )
    return result


def require_manual_signature_date(template_id, preview):
    if template_id != "joyyou":
        return
    for field in preview.get("mappings", []):
        if field.get("key") in MANUAL_KEYS:
            field.update(
                value="",
                source="missing",
                confidence=0.0,
                reason="簽署日期須由使用者核對；不能使用出生日期代填。",
            )
    if isinstance(preview.get("summary"), dict):
        for source in ("direct", "llm", "default", "missing"):
            preview["summary"][source] = sum(
                field.get("source") == source for field in preview["mappings"]
            )
