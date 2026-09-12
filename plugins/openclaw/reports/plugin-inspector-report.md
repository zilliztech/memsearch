# OpenClaw Plugin Compatibility Report

Generated: deterministic
Status: PASS

## Summary

| Metric                     | Value |
| -------------------------- | ----- |
| Fixtures                   | 1     |
| High-priority fixtures     | 1     |
| Hard breakages             | 0     |
| Warnings                   | 2     |
| Compatibility suggestions  | 2     |
| Issue findings             | 4     |
| Open issue findings        | 4     |
| Runtime-covered findings   | 0     |
| Runtime-partial findings   | 0     |
| P0 issues                  | 0     |
| P1 issues                  | 2     |
| Open P0 issues             | 0     |
| Open P1 issues             | 2     |
| Live issues                | 0     |
| Live P0 issues             | 0     |
| Compat gaps                | 1     |
| Deprecation warnings       | 0     |
| Inspector gaps             | 2     |
| Open inspector gaps        | 2     |
| Runtime coverage artifacts | 0     |
| Upstream metadata          | 1     |
| Contract probes            | 3     |
| Decision rows              | 4     |

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

## Hard Breakages

_none_

## Target OpenClaw Compat Records

| Metric                    | Value                                          |
| ------------------------- | ---------------------------------------------- |
| Configured path           | npm:openclaw@2026.9.4                          |
| Status                    | ok                                             |
| Requested version         | 2026.9.4                                       |
| Resolved version          | 2026.9.4                                       |
| Range eligibility version | 2026.9.4                                       |
| Source                    | npm:openclaw                                   |
| NPM dist-tag              | -                                              |
| Prepared cache            | hit                                            |
| Compat registry           | -                                              |
| Compat records            | 0                                              |
| Compat status counts      | -                                              |
| Record ids                | -                                              |
| Hook registry             | dist/agent-harness-runtime-BvaKEkqR.d.ts       |
| Hook names                | 42                                             |
| API builder               | dist/agent-harness-runtime-BvaKEkqR.d.ts       |
| API registrars            | 57                                             |
| Captured registration     | dist/agent-harness-runtime-BvaKEkqR.d.ts       |
| Captured registrars       | 57                                             |
| Package metadata          | package.json                                   |
| Plugin SDK exports        | 338                                            |
| Manifest types            | dist/install-security-scan.types-DTKUtHF_.d.ts |
| Manifest fields           | 53                                             |
| Manifest contract fields  | 22                                             |

## Warnings

| Fixture   | Code                     | Level   | Message                                                                                       | Evidence                                           | Compat record                     |
| --------- | ------------------------ | ------- | --------------------------------------------------------------------------------------------- | -------------------------------------------------- | --------------------------------- |
| memsearch | manifest-name-missing    | warning | openclaw.plugin.json does not declare a display name                                          | openclaw.plugin.json                               | -                                 |
| memsearch | conversation-access-hook | warning | fixture observes raw model or conversation content and needs privacy-boundary contract probes | agent_end @ index.js:604, agent_end @ index.ts:818 | hook.llm-observer.privacy-payload |

## Suggestions To OpenClaw Compat Layer

| Fixture   | Code                  | Level      | Message                                                                                           | Evidence                                                                                                                                                                     | Compat record                     |
| --------- | --------------------- | ---------- | ------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| memsearch | runtime-tool-capture  | suggestion | tool shape is only visible after runtime registration capture                                     | registerTool @ index.js:322, registerTool @ index.js:370, registerTool @ index.js:413, registerTool @ index.ts:464, registerTool @ index.ts:523, registerTool @ index.ts:576 | -                                 |
| memsearch | missing-compat-record | suggestion | fixture depends on a compatibility behavior that is not represented in the target compat registry | hook.llm-observer.privacy-payload                                                                                                                                            | hook.llm-observer.privacy-payload |

## Issue Findings

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

## Fixture Seam Inventory

| Fixture   | Priority | Seams          | Hooks                                         | Registrations             | Manifest contracts |
| --------- | -------- | -------------- | --------------------------------------------- | ------------------------- | ------------------ |
| memsearch | high     | plugin-runtime | agent_end, before_prompt_build, session_start | registerCli, registerTool | -                  |

## Decision Matrix

| Fixture   | Decision            | Seam                | Action                                                                                                         | Evidence                                      |
| --------- | ------------------- | ------------------- | -------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| memsearch | plugin-upstream-fix | manifest-metadata   | Ask the plugin to declare openclaw.plugin.json name so registries and tools can derive a human-readable title. | openclaw.plugin.json                          |
| memsearch | inspector-follow-up | conversation-access | Add synthetic llm_input/llm_output/agent_end probes before tightening hook payloads or redaction behavior.     | agent_end                                     |
| memsearch | inspector-follow-up | tool-schema         | Capture registered tool schemas from plugin register() before judging tool compatibility.                      | registerTool without manifest contracts.tools |
| memsearch | core-compat-adapter | compat-registry     | Add or restore a machine-readable OpenClaw compat record before changing this plugin-facing behavior.          | hook.llm-observer.privacy-payload             |

## Raw Logs

| Fixture   | Code                    | Level | Message                                                                          | Evidence                                                                                                          | Compat record |
| --------- | ----------------------- | ----- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------------- |
| memsearch | seam-inventory          | log   | observed 3 hooks, 2 registrations, and 0 manifest contracts                      | hook:agent_end, hook:before_prompt_build, hook:session_start, registration:registerCli, registration:registerTool | -             |
| memsearch | hook-names-present      | log   | all observed hooks exist in the target OpenClaw hook registry                    | agent_end, before_prompt_build, session_start                                                                     | -             |
| memsearch | api-registrars-present  | log   | all observed api.register* calls exist in the target OpenClaw plugin API builder | registerCli, registerTool                                                                                         | -             |
| memsearch | manifest-fields-checked | log   | plugin manifest fields were compared with target OpenClaw manifest types         | openclaw.plugin.json                                                                                              | -             |
| memsearch | package-metadata        | log   | selected package metadata for plugin contract checks                             | package.json, memsearch, version:0.3.19                                                                           | -             |
