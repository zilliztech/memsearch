import test from "node:test";
import assert from "node:assert/strict";

import { mergeSystemMemoryContext, MEMSEARCH_SYSTEM_MARKER } from "./index.ts";

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
