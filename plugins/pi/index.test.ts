import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  extractLastTurn,
  extractText,
  getRecentMemories,
  isDailyJournalFile,
  isNoiseLine,
  shellEscape,
  tailTruncate,
} from "./context.ts";

test("plugin entry exposes only the default extension function", async () => {
  const mod = await import("./index.ts");

  assert.deepEqual(Object.keys(mod), ["default"]);
  assert.equal(typeof mod.default, "function");
});

test("only dated journal files are treated as memory", () => {
  assert.equal(isDailyJournalFile("2026-07-25.md"), true);
  assert.equal(isDailyJournalFile("PROJECT.md"), false);
  assert.equal(isDailyJournalFile("2026-7-5.md"), false);
});

test("noise lines cover structure and injected hints", () => {
  assert.equal(isNoiseLine("## Session 17:32"), true);
  assert.equal(isNoiseLine("<!-- session:abc turn:def -->"), true);
  assert.equal(isNoiseLine("[memsearch] Memory available."), true);
  assert.equal(isNoiseLine("```json"), true);
  assert.equal(isNoiseLine("- User asked about caching"), false);
});

test("text extraction keeps text blocks and drops noise", () => {
  const content = [
    { type: "text", text: "[memsearch] Memory available.\nreal content" },
    { type: "thinking", thinking: "internal reasoning" },
  ];
  assert.equal(extractText(content), "real content");
  assert.equal(extractText("plain string"), "plain string");
  assert.equal(extractText(42), "");
});

test("tail truncation marks that the head was dropped", () => {
  assert.equal(tailTruncate("short", 10), "short");
  const long = tailTruncate("abcdefghij", 4);
  assert.ok(long.startsWith("...(truncated to tail)"));
  assert.ok(long.endsWith("ghij"));
});

test("shell escaping closes and reopens single quotes", () => {
  assert.equal(shellEscape("it's"), "it'\\''s");
});

test("last turn stops at the most recent user message", () => {
  const entries = [
    { type: "message", id: "1", parentId: null, message: { role: "user", content: "first question" } },
    { type: "message", id: "2", parentId: "1", message: { role: "assistant", content: [{ type: "text", text: "first answer" }] } },
    { type: "message", id: "3", parentId: "2", message: { role: "user", content: "second question here" } },
    { type: "message", id: "4", parentId: "3", message: { role: "assistant", content: [{ type: "text", text: "second answer" }] } },
  ];

  const turn = extractLastTurn(entries);

  assert.ok(turn);
  assert.ok(!turn.includes("first question"));
  assert.ok(turn.includes("[User]: second question here"));
  assert.ok(turn.includes("[Assistant]: second answer"));
});

test("last turn skips tool results and non-message entries", () => {
  const entries = [
    { type: "message", id: "1", parentId: null, message: { role: "user", content: "explain the plan" } },
    { type: "model_change", id: "2", parentId: "1" },
    { type: "message", id: "3", parentId: "2", message: { role: "toolResult", content: [{ type: "text", text: "raw tool output" }] } },
    { type: "message", id: "4", parentId: "3", message: { role: "assistant", content: [{ type: "text", text: "here is the plan" }] } },
  ];

  const turn = extractLastTurn(entries);

  assert.ok(turn);
  assert.ok(!turn.includes("raw tool output"));
  assert.ok(turn.includes("here is the plan"));
});

test("no user message means nothing to capture", () => {
  const entries = [
    { type: "message", id: "1", parentId: null, message: { role: "assistant", content: [{ type: "text", text: "unprompted" }] } },
  ];

  assert.equal(extractLastTurn(entries), null);
  assert.equal(extractLastTurn([]), null);
});

test("recent memories summarize the latest journals", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-pi-"));
  try {
    writeFileSync(
      join(dir, "2026-07-24.md"),
      "# 2026-07-24\n\n## Session 09:00\n\n### 09:00\n- older note\n",
      "utf-8"
    );
    writeFileSync(
      join(dir, "2026-07-25.md"),
      "# 2026-07-25\n\n## Session 10:00\n\n### 10:00\n- newer note\n",
      "utf-8"
    );

    const context = getRecentMemories(dir);

    assert.ok(context.includes("- newer note"));
    assert.ok(context.includes("[2026-07-25.md]"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("sessions without a body do not crowd out the preview", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-pi-"));
  try {
    writeFileSync(
      join(dir, "2026-07-25.md"),
      "# 2026-07-25\n\n## Session 09:00\n\n### 09:00\n- real note\n\n## Session 11:00\n\n",
      "utf-8"
    );

    const context = getRecentMemories(dir);

    assert.ok(context.includes("- real note"));
    assert.ok(!context.includes("## Session 11:00"));
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("an absent memory directory yields no context", () => {
  assert.equal(getRecentMemories(join(tmpdir(), "memsearch-pi-does-not-exist")), "");
});
