# Product manager review brief

You are the user's explicitly requested Claude Opus 5.5 product manager. Codex is the implementation lead. Make independent product and UX decisions and challenge the engineering recommendation where evidence warrants it. Reply in Traditional Chinese. This is a design discussion, not authorization to send messages, publish, purchase, or access credentials. Do not claim to have inspected files not supplied to you.

## Outcome and deadline

On 2026-10-02 the user authorized a complete takeover of NGOPilot, created by a former collaborator. They need usable software alongside the existing CareFlow Atlas for the 2026-10-07 Tencent LIGHT Top 50 to Top 20 review. They want us to decide whether the NGO community-activity Scheduler belongs inside NGOPilot or should become a separate CareFlow Scheduler repository under Projects. If separate, deliver two usable projects; otherwise one integrated project. The user will not manage routine decisions. Selection and adoption cannot be guaranteed or fabricated.

CareFlow is the umbrella team/product collection. CareFlow Documents, Atlas field outreach, community-activity selection and care-worker Roster are different workflows. Historical materials are explicitly not new instructions. Claims of NGO interest or deployment do not establish current active use. The latest context says several earlier contacts stopped replying; no fresh adoption evidence is available.

## Verified current code

- NGOPilot uses a Rust Goose-derived agent harness, desktop React UI reused in a Vite browser build, and FastAPI gateway. Cloud configuration involves PostgreSQL, GCS and local runtime snapshots. Runtime isolation is per user, not an established shared organisation workspace.
- Four independent stateful MCP tools: paper volunteer forms to XLSX; audio plus DOCX template to reviewed notes; elder information plus a configured government form to PDF; HC/escort workbooks to reviewed care-worker roster.
- Tool packages separate schema, validation, controller, adapter, state and artifacts. `algo-dependencies/` is immutable; integration fixes must live in NGOPilot adapters. Runtime normally executes vendored payloads in two isolated Python environments, not the newest sibling CareFlow source.
- The visible existing “Scheduler” is cron/recipe automation. There is no activity brochure importer, monthly activity catalogue, activity selection or timetable clash checker in this checkout.
- Current paper-form workflow automatically approves model extraction. This conflicts with the original Documents product's human-review principle. Audio/government/roster have explicit review concepts.
- Current UI still includes generic agent features: recipes, skills, apps, extensions, model/provider settings, and cron scheduler. Browser authentication is English while much of the product locale is zh-HK.
- Atlas in the primary checkout is a synthetic-data React/localStorage spatial workbench. It should not be described as production resident-data software or forced to acquire AI to justify the competition entry.
- Technical baseline: 138 MCP tests passed before changes; 66 gateway tests plus one real temporary PostgreSQL integration test passed. Browser build passed; a type-resolution defect is being fixed. These are not live-provider or NGO usability evidence.
- Codex has independently patched credential-bearing diagnostics and is validating it. No final product split has been made.

## Supplied requirement and source input

The short requirement names Caritas Mok Cheung Sui Kun Community Centre. It says registrations happen offline, and workers cannot easily check clashes across the chosen activities. Its diagrams request: upload a brochure (a sketch says roughly 30 pages), extract dates/times/content, open a monthly calendar, search by name/date, select activities and generate an individual schedule. It proposes a two-minute demonstration and a five-point staff feedback scale. It does not establish an online-registration, CRM, payment, staff-optimisation or capacity-reservation requirement.

The attached “Experiment” PDF is actually an 84-page public activity brochure, issue 125, mainly July–September 2026 with some later classes. It is a historical input, not an outcome experiment. Activities include discrete dates, weekly ranges, skipped dates, age eligibility, quoted capacity and fees. The page images contain “FULL” stamps absent from text extraction. The text layer also contains stale hidden template rows and some inconsistent date/weekday/session-count values. Extraction alone cannot assert live availability, infer cancelled dates or silently repair contradictions.

The old document says security is unimportant because the brochure is public. This cannot extend to participant identities. A first useful release can potentially check a temporary selection without collecting names, phone numbers or membership records. Even an exported timetable is a planning aid, not confirmed enrolment.

## Engineering recommendation to debate

Consider a separate, structured CareFlow Scheduler UI for “brochure → review → searchable activities/calendar → selection → conflict explanation → printable/ICS timetable”, with a narrow optional integration from Pilot later. Keep a usable, focused Pilot for document workflows. This avoids confusing activity scheduling with cron and care-worker allocation. But weigh honestly the maintenance cost and the limited pre-deadline window; an integrated route may be better if it materially reuses reliable code without exposing agent settings.

For AI evidence, propose real runtime extraction with source page references and human correction, plus deterministic conflict calculations. Clearly label historical sample dates, unknown capacity, mocked/offline demonstration and live model results. No automatic reservation, outbound notification, or invented NGO savings. Source review must handle visual “FULL” marks and contradictions. Do not rely on a curated sample alone and call it general extraction.

## Decisions requested

1. Choose one or two deliverables, explain why, and distinguish community activities from staff rosters.
2. Define primary user, first useful task, navigation, first-run experience, and explicit scope cuts.
3. Define the smallest complete end-to-end acceptance contract for NGO trial, including review, date recurrence, clashes, export, persistence, corrections and failure recovery.
4. Decide how Pilot's existing tools and generic features should be presented and what to do about automatic paper-form approval.
5. Specify demo vs live AI behavior, evidence to capture for October 7, and claims we must not make.
6. Give a ranked implementation order and challenge any unrealistic part of Codex's proposal. Prefer actionable decisions over a broad roadmap. Do not invent budget, traction, official judging rules or facts about unseen code.
