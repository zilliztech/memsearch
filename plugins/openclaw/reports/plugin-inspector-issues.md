# OpenClaw Plugin Issue Findings

Generated: deterministic
Status: PASS

## Triage Summary

| Metric                     | Value |
| -------------------------- | ----- |
| Issue findings             | 4     |
| Open issue findings        | 4     |
| Runtime-covered findings   | 0     |
| Runtime-partial findings   | 0     |
| P0                         | 0     |
| P1                         | 2     |
| Open P0                    | 0     |
| Open P1                    | 2     |
| Live issues                | 0     |
| Live P0 issues             | 0     |
| Compat gaps                | 1     |
| Deprecation warnings       | 0     |
| Inspector gaps             | 2     |
| Open inspector gaps        | 2     |
| Runtime coverage artifacts | 0     |
| Upstream metadata          | 1     |
| Contract probes            | 3     |

## Triage Overview

| Class               | Count | P0 | Meaning                                                                                                                                                  |
| ------------------- | ----- | -- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| live-issue          | 0     | 0  | Potential runtime breakage in the target OpenClaw/plugin pair. P0 only when it is not a deprecated compat seam.                                          |
| compat-gap          | 1     | -  | Compatibility behavior is needed but missing from the target OpenClaw compat registry.                                                                   |
| deprecation-warning | 0     | -  | Plugin uses a supported but deprecated compatibility seam; keep it wired while migration exists.                                                         |
| inspector-gap       | 2     | -  | Plugin Inspector needs stronger capture/probe evidence before making contract judgments. Runtime-covered rows are proof-backed and not open report work. |
| upstream-metadata   | 1     | -  | Plugin package or manifest metadata should improve upstream; not a target OpenClaw live break by itself.                                                 |
| fixture-regression  | 0     | -  | Fixture no longer exposes an expected seam; investigate fixture pin or scanner drift.                                                                    |

## P0 Live Issues

_none_

## Other Live Issues

_none_

## Compat Gaps

- P1 **memsearch** `compat-gap` `core-compat-adapter`
  - **missing-compat-record**: memsearch: compat-dependent behavior lacks registry coverage
  - state: open · compat:missing
  - evidence:
    - hook.llm-observer.privacy-payload

## Deprecation Warnings

_none_

## Inspector Proof Gaps

- P1 **memsearch** `inspector-gap` `inspector-follow-up`
  - **conversation-access-hook**: memsearch: conversation-access hooks need privacy-boundary probes
  - state: open · compat:untracked
  - evidence:
    - agent_end @ index.js:604
    - agent_end @ index.ts:818

- P2 **memsearch** `inspector-gap` `inspector-follow-up`
  - **runtime-tool-capture**: memsearch: runtime tool schema needs registration capture
  - state: open · compat:none
  - evidence:
    - registerTool @ index.js:322
    - registerTool @ index.js:370
    - registerTool @ index.js:413
    - registerTool @ index.ts:464
    - registerTool @ index.ts:523
    - registerTool @ index.ts:576

## Runtime-Covered Inspector Gaps

_none_

## Upstream Metadata Issues

- P2 **memsearch** `upstream-metadata` `plugin-upstream-fix`
  - **manifest-name-missing**: memsearch: manifest display name is missing
  - state: open · compat:none
  - evidence:
    - openclaw.plugin.json
  - author remediation:
    - Add a display name to the plugin manifest.
    - docs: https://docs.openclaw.ai/clawhub/plugin-validation-fixes#manifest-name-missing

## Issues

- P1 **memsearch** `inspector-gap` `inspector-follow-up`
  - **conversation-access-hook**: memsearch: conversation-access hooks need privacy-boundary probes
  - state: open · compat:untracked
  - evidence:
    - agent_end @ index.js:604
    - agent_end @ index.ts:818

- P1 **memsearch** `compat-gap` `core-compat-adapter`
  - **missing-compat-record**: memsearch: compat-dependent behavior lacks registry coverage
  - state: open · compat:missing
  - evidence:
    - hook.llm-observer.privacy-payload

- P2 **memsearch** `upstream-metadata` `plugin-upstream-fix`
  - **manifest-name-missing**: memsearch: manifest display name is missing
  - state: open · compat:none
  - evidence:
    - openclaw.plugin.json
  - author remediation:
    - Add a display name to the plugin manifest.
    - docs: https://docs.openclaw.ai/clawhub/plugin-validation-fixes#manifest-name-missing

- P2 **memsearch** `inspector-gap` `inspector-follow-up`
  - **runtime-tool-capture**: memsearch: runtime tool schema needs registration capture
  - state: open · compat:none
  - evidence:
    - registerTool @ index.js:322
    - registerTool @ index.js:370
    - registerTool @ index.js:413
    - registerTool @ index.ts:464
    - registerTool @ index.ts:523
    - registerTool @ index.ts:576

## Contract Probe Backlog

- P1 **memsearch** `hook-runner`
  - contract: LLM observer hooks receive documented prompt/output fields with expected redaction behavior.
  - id: `hook.llm-observer.privacy-payload:memsearch`
  - evidence:
    - agent_end @ index.js:604
    - agent_end @ index.ts:818

- P2 **memsearch** `manifest-loader`
  - contract: OpenClaw plugin manifests declare a human-readable display name for registry and tooling metadata.
  - id: `manifest.metadata.name:memsearch`
  - evidence:
    - openclaw.plugin.json

- P2 **memsearch** `tool-runtime`
  - contract: Registered runtime tools expose stable names, input schemas, and result metadata.
  - id: `tool.registration.schema-capture:memsearch`
  - evidence:
    - registerTool @ index.js:322
    - registerTool @ index.js:370
    - registerTool @ index.js:413
    - registerTool @ index.ts:464
    - registerTool @ index.ts:523
    - registerTool @ index.ts:576
