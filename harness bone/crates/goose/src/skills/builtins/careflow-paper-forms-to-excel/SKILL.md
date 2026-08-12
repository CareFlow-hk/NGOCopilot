---
name: careflow-paper-forms-to-excel
description: Convert attached JPG, JPEG, or PNG images of completed CareFlow volunteer-visit forms into a reviewed Excel workbook. Use for paper-form extraction, review, and export; exclude government forms, audio, and existing spreadsheets.
---

# CareFlow Paper Forms to Excel

Call `careflow_paper_forms_to_excel` immediately. Pass every relevant JPG, JPEG,
or PNG path from `Attachments:` unchanged in `input.image_paths`. Never ask the
user to find or retype an attachment path.

Start with the smallest valid call:

```json
{
  "operation": "start",
  "input": {
    "image_paths": ["/absolute/form-01.jpg"]
  }
}
```

`input.title`, `input.volunteer_team`, `input.visit_date`, and `input.note` are
optional. Include them only when the user supplied them; the tool generates a
title when omitted.

## Follow the returned state

1. Save the `job_id` returned by `start`. Use that exact value for every later
   call to this tool.
2. If `state` is `running`, call `status` with that `job_id`. Do not poll when
   the response already contains records ready for review.
3. If `state` is `pending_review`, show every record's `final_fields` to the user
   and ask for corrections or confirmation. Do not call `review` before the user
   has checked the extracted values.
4. After confirmation with no corrections, call `review` once with
   `input: {"confirm_all": true}`. The tool safely copies every complete,
   unreviewed `final_fields` object from the job. If the user gives corrections,
   use `input.reviews` instead: for each item, copy the returned record `id` into
   `record_id` and its complete 13-key `final_fields` object, then apply only the
   user's corrections. Never omit keys, submit a partial patch, or invent a value.
5. When review succeeds and `export` appears in `next_operations`, call `export`
   immediately with the same `job_id`. The user's original request for an Excel
   workbook is sufficient authorization; do not ask for a second export
   confirmation.

Later operations use these shapes:

```json
{"operation":"status","job_id":"<job_id>"}
```

```json
{
  "operation": "review",
  "job_id": "<job_id>",
  "input": {"confirm_all": true}
}
```

```json
{"operation":"export","job_id":"<job_id>"}
```

## Return the workbook

After a successful export, return exactly one Excel download link using the
promoted `.xlsx` entry in `artifacts` (normally `artifacts[0].path`), for example:
   `**Download Excel**: [Download batch.xlsx](</absolute/artifact/path/batch.xlsx>)`.
Wrap the absolute artifact path in angle brackets inside the Markdown link. Do
not display `download_url`, `native_path`, or `output_path` as user-facing text.
If the export response has no verified Excel artifact, report the returned error
instead of inventing a link.

Follow the MCP schema for every call.
