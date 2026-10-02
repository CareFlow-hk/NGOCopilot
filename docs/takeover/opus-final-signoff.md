# CareFlow PM sign-off: supervised local trial

**Basis:** I don't have the original review in this session. I haven't run or inspected anything this turn. This sign-off rests on your reported evidence, checked against the P0s as you described them.

## P0 status

**P0-1 (auto-approval): Closed.**
- The approval path is removed, not just disabled. Start and status never call review.
- Negative tests cover the right cases: export before review, missing reviewer or checkbox, and bulk `confirm_all`.
- The live check is the right proof: a real Azure job reaches `pending_review` with only status and review as next operations, and no export button appears.
- Keeping explicit Agent review public is acceptable because it still requires a deliberate review action.

**P0-2 (weekday/count integrity): Closed.**
- A mismatch is now a deterministic issue that the confirmation API refuses.
- Drafts are excluded from the catalogue and from selection.
- The manual corrections keep the originals, and the 20 confirmed / 5 draft / 1 excluded split is distinguishable.

## Decision

**APPROVED for supervised local trial only**, on these conditions:

1. **Docker rebuild.** The original-Agent Docker rebuild must finish and pass the same smoke checks before it is used in the trial. Until then, the trial runs on the verified local product only.
2. **Pin the tested state.** The git snapshot I can see shows the relevant changes uncommitted. Record the exact commit or tree hash you tested in the evidence pack, so the trial runs on what was verified.
3. **Supervision.** A named supervisor is present for every session. All trial outputs are treated as drafts that need human review before any operational use.
4. **NGO validation stays NOT_READY.** No public deployment, adoption claims, or competition claims follow from this sign-off.

## Out of scope

- Production readiness
- Unsupervised use
- Real beneficiary data beyond what the trial supervisor approves
- Any new features

Re-review is needed for any change to the review/export gate or to the confirmation rules.

Verified canonical model: claude-opus-5-5; effort medium; 2026-10-02.
