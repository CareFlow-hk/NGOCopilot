---
name: careflow-paper-forms-to-excel
description: Convert attached JPG, JPEG, or PNG images of completed CareFlow volunteer-visit forms directly into an Excel workbook. Use for paper-form extraction and export; exclude government forms, audio, and existing spreadsheets.
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
   `export` already appears in `next_operations`.
3. Extracted records are approved automatically. Do not show a review step and
   do not ask the user for confirmation.
4. When `export` appears in `next_operations`, call `export` immediately with the
   same `job_id`. The user's original request for an Excel workbook is sufficient
   authorization; do not ask for another confirmation.

Later operations use these shapes:

```json
{"operation":"status","job_id":"<job_id>"}
```

```json
{"operation":"export","job_id":"<job_id>"}
```

## Return the workbook

After a successful export, make the final assistant output exactly one Excel
download link using the promoted `.xlsx` entry in `artifacts` (normally
`artifacts[0].path`), for example:
   `**Download Excel**: [Download batch.xlsx](</absolute/artifact/path/batch.xlsx>)`.
Wrap the absolute artifact path in angle brackets inside the Markdown link. Do
not display `download_url`, `native_path`, or `output_path` as user-facing text.
If the export response has no verified Excel artifact, report the returned error
instead of inventing a link.

Only that final output should contain the artifact link. Do not repeat artifact
paths in intermediate messages; the frontend turns the final link into the
clickable `Download result` action.

Follow the MCP schema for every call.
