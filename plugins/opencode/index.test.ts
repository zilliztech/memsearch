import test from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  getSkillCandidateHint,
  getRecentMemories,
  isDailyJournalFile,
  mergeSystemMemoryContext,
  MEMSEARCH_SYSTEM_MARKER,
} from "./context.ts";

test("plugin entry exposes only the default plugin function", async () => {
  const mod = await import("./index.ts");

  assert.deepEqual(Object.keys(mod), ["default"]);
  assert.equal(typeof mod.default, "function");
});

test("appends memory context when no system entry exists yet", () => {
  const result = mergeSystemMemoryContext(undefined, `${MEMSEARCH_SYSTEM_MARKER} ctx-a`);
  assert.deepEqual(result, [`${MEMSEARCH_SYSTEM_MARKER} ctx-a`]);
});

test("folds memory context into the first entry without growing the array", () => {
  const result = mergeSystemMemoryContext(
    ["You are a helpful assistant."],
    `${MEMSEARCH_SYSTEM_MARKER} ctx-a`
  );
  assert.equal(result.length, 1);
  assert.equal(result[0], `You are a helpful assistant.\n\n${MEMSEARCH_SYSTEM_MARKER} ctx-a`);
});

test("repeated calls with the same context stay idempotent", () => {
  const base = ["You are a helpful assistant."];
  const memoryText = `${MEMSEARCH_SYSTEM_MARKER} ctx-a`;

  const first = mergeSystemMemoryContext(base, memoryText);
  const second = mergeSystemMemoryContext(first, memoryText);
  const third = mergeSystemMemoryContext(second, memoryText);

  assert.equal(third.length, 1);
  assert.equal(third[0], first[0]);
  // Only one occurrence of the marker — no duplicated memsearch block.
  assert.equal(third[0].split(MEMSEARCH_SYSTEM_MARKER).length - 1, 1);
});

test("repeated calls with updated context replace the previous block", () => {
  const base = ["You are a helpful assistant."];
  const first = mergeSystemMemoryContext(base, `${MEMSEARCH_SYSTEM_MARKER} ctx-a`);
  const second = mergeSystemMemoryContext(first, `${MEMSEARCH_SYSTEM_MARKER} ctx-b`);

  assert.equal(second.length, 1);
  assert.equal(second[0], `You are a helpful assistant.\n\n${MEMSEARCH_SYSTEM_MARKER} ctx-b`);
  assert.ok(!second[0].includes("ctx-a"));
});

test("does not disturb additional system entries beyond the first", () => {
  const base = ["Base prompt.", "Second unrelated system entry."];
  const first = mergeSystemMemoryContext(base, `${MEMSEARCH_SYSTEM_MARKER} ctx-a`);
  const second = mergeSystemMemoryContext(first, `${MEMSEARCH_SYSTEM_MARKER} ctx-b`);

  assert.equal(second.length, 2);
  assert.equal(second[1], "Second unrelated system entry.");
  assert.ok(!second[0].includes("ctx-a"));
});

test("recent memories only use dated daily journals", () => {
  assert.equal(isDailyJournalFile("2026-07-13.md"), true);
  assert.equal(isDailyJournalFile("notes.md"), false);
  assert.equal(isDailyJournalFile("recall-staging-123.md"), false);

  const dir = mkdtempSync(join(tmpdir(), "memsearch-opencode-memory-"));
  try {
    writeFileSync(
      join(dir, "2026-07-12.md"),
      "# 2026-07-12\n\n## Session 09:00\n\n### 09:00\n- Daily journal content.\n",
      "utf-8"
    );
    writeFileSync(
      join(dir, "zzz-scratch.md"),
      "# Scratch\n\n## Session 10:00\n\n### 10:00\n- Scratch content should not displace daily journals.\n",
      "utf-8"
    );

    const context = getRecentMemories(dir);

    assert.match(context, /2026-07-12\.md/);
    assert.match(context, /Daily journal content/);
    assert.doesNotMatch(context, /zzz-scratch/);
    assert.doesNotMatch(context, /Scratch content/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("skill candidate hint comes from memsearch status", () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-opencode-skills-"));
  try {
    const bin = join(root, "bin");
    const memsearchDir = join(root, ".memsearch");
    mkdirSync(bin);
    mkdirSync(memsearchDir);
    const fakeMemsearch = join(bin, "memsearch");
    writeFileSync(
      fakeMemsearch,
      "#!/usr/bin/env bash\n" +
        "test \"$MEMSEARCH_DIR\" = \"$1\" && shift\n" +
        "if [ \"$1\" = \"skills\" ] && [ \"$2\" = \"status\" ] && [ \"$3\" = \"--hint\" ]; then\n" +
        "  echo 'SKILLS: 1 candidate skill version(s) pending install - run the memory-to-skill skill to review and install.'\n" +
        "fi\n",
      "utf-8"
    );
    chmodSync(fakeMemsearch, 0o755);

    const hint = getSkillCandidateHint(memsearchDir, `${fakeMemsearch} '${memsearchDir}'`);

    assert.match(hint, /SKILLS: 1 candidate skill version/);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
