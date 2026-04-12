# memsearch - TODO

> **Last Updated:** 2026-04-08

---

## ✅ Completed

- [x] Clone upstream `zilliztech/memsearch` into `/home/node/workplace/AWCLOUD/TEMPLATE/PLUGIN/memsearch` for local development.
- [x] Establish a local design/changelog baseline for expanding the Claude Code plugin skill surface beyond `memory-recall`.

---

## 📋 Tasks To Do

### Claude Code Plugin Skill Expansion
- [x] Add a bounded `search` skill for direct semantic chunk lookup.
- [x] Add a bounded `expand` skill for chosen chunk hashes.
- [x] Add a bounded `session-recall` skill for session-specific memory recall.
- [x] Add `stats` and `config-check` skills for operator diagnostics.
- [x] Add a bounded `memory-router` orchestration skill that chooses the correct memsearch retrieval path before broader fallback behavior and checks retrieval readiness when config/index health may be the real blocker.
- [ ] Re-evaluate whether a broader memory navigator agent is still needed after the direct skills plus orchestration skill exist.

---

## 📜 History

| Date | Changes |
|------|---------|
| 2026-04-12 | Added `memory-router` as a bounded orchestration/front-door wrapper skill so Claude-facing retrieval can choose the correct memsearch path first and check retrieval readiness when config/index health may be the real blocker. |
| 2026-04-08 | Cloned upstream `zilliztech/memsearch` for local development, inspected the current Claude Code plugin surface, and created a local design/changelog/TODO/phase baseline for expanding bounded Claude-facing skill access to memsearch commands. |
