# NGOPilot Agent Notes

## Development boundaries

- Treat `algo-dependencies/` as read-only. Never edit, patch, format, or add files
  there; implement all integration and compatibility work in NGOPilot-owned
  adapters so an algorithm dependency can be upgraded by replacing its directory
  with a fresh clone.

## Future extension of tool

Design MCP changes for additive extensibility: adding, replacing, or removing one
tool must not require changes inside another tool's implementation.

- Add every new tool as an independent sibling under
  `MCPcode/src/ngopilot_mcp/tools/<tool_name>/`, following the current four tools
  and the MCP pre-build algorithm design plan.
- Give each tool its own `manifest.py`, `schemas.py`, `controller.py`,
  `validation.py`, `native_adapter.py`, `state.py`, `artifacts.py`, and
  `__init__.py`, plus a matching test directory under `MCPcode/tests/tools/`.
- Expose the standard `MANIFEST` and `CONTROLLER` contract, then connect the tool
  only through composition points such as the host registry, worker dispatch,
  runtime/bootstrap configuration, and packaging. Do not add tool-specific
  branches to an existing tool.
- Keep workflow schemas, validation, state transitions, dependency calls, and
  artifact rules inside the tool package. A tool may use domain-neutral shared
  infrastructure, but it must never import or call another tool implementation.
- Move code into `shared/` only when it is genuinely domain-neutral and used by
  multiple tools; shared code must not encode one tool's workflow assumptions.
- Verify the new tool with isolated contract, validation, adapter, controller,
  artifact, and lifecycle tests. Existing tool tests must continue to pass
  without modification unless a shared public contract intentionally changes.

## Deployment authentication

The local deployment CLIs were authenticated on 2026-08-03:

- Railway: `倪嘉辰（Wilson） <wilson1111223@gmail.com>`
- Render: `Wilsonnijc@outlook.com`
- AWS CLI `default`: account `106189426186`, currently
  `arn:aws:iam::106189426186:root`

Use the existing user-level CLI credentials for deployment work. Before ordinary
NGOPilot deployments, verify only the platforms being deployed:

```sh
railway whoami
render whoami
```

AWS is an optional deployment dependency. Do not require AWS authentication for a
Railway and/or Render deployment that does not change or inspect AWS resources.
Run `aws sts get-caller-identity` before specific AWS work or AWS infrastructure
verification only.

The signed AWS CLI is installed at `~/.local/aws-cli` and exposed through
`~/.local/bin/aws`. The Homebrew AWS CLI is unlinked because its Python runtime
is incompatible with this macOS version.

The user has explicitly authorized the current root session for NGOPilot AWS work.
Use it only for specific, user-requested NGOPilot actions after verifying exact
targets. Do not create root access keys, expose or copy its tokens, or treat this as
authorization for unrelated account-wide changes. Prefer a least-privilege profile
if one is configured later.

Railway, Render, and AWS manage their credentials outside this repository. Never
copy access tokens, credential files, or device authorization codes into the
repository, logs, deployment manifests, or chat output. If a verification command
for a required deployment platform fails, run the corresponding interactive login
flow with the user present. An expired optional AWS session must not block an
otherwise independent Railway or Render deployment.
