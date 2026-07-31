import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { getMemsearchDir, getCollectionScopeDir } from "./index.ts";

function withEnv(key: string, value: string | undefined, fn: () => void): void {
  const prev = process.env[key];
  if (value === undefined) {
    delete process.env[key];
  } else {
    process.env[key] = value;
  }
  try {
    fn();
  } finally {
    if (prev === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = prev;
    }
  }
}

test("getMemsearchDir: defaults to <projectDir>/.memsearch", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-"));
  try {
    withEnv("MEMSEARCH_DIR", undefined, () => {
      assert.equal(getMemsearchDir(dir), join(dir, ".memsearch"));
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("getMemsearchDir: MEMSEARCH_DIR overrides projectDir", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-"));
  const shared = mkdtempSync(join(tmpdir(), "memsearch-openclaw-shared-"));
  try {
    withEnv("MEMSEARCH_DIR", shared, () => {
      assert.equal(getMemsearchDir(dir), shared);
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(shared, { recursive: true, force: true });
  }
});

test("getCollectionScopeDir: defaults to projectDir", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-"));
  try {
    withEnv("MEMSEARCH_DIR", undefined, () => {
      assert.equal(getCollectionScopeDir(dir), dir);
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("getCollectionScopeDir: two projects with same MEMSEARCH_DIR share scope", () => {
  const a = mkdtempSync(join(tmpdir(), "memsearch-openclaw-a-"));
  const b = mkdtempSync(join(tmpdir(), "memsearch-openclaw-b-"));
  const shared = mkdtempSync(join(tmpdir(), "memsearch-openclaw-shared-"));
  try {
    withEnv("MEMSEARCH_DIR", shared, () => {
      assert.equal(getCollectionScopeDir(a), getCollectionScopeDir(b));
      assert.equal(getCollectionScopeDir(a), shared);
    });
  } finally {
    rmSync(a, { recursive: true, force: true });
    rmSync(b, { recursive: true, force: true });
    rmSync(shared, { recursive: true, force: true });
  }
});

test("getCollectionScopeDir: two projects without MEMSEARCH_DIR have isolated scope", () => {
  const a = mkdtempSync(join(tmpdir(), "memsearch-openclaw-a-"));
  const b = mkdtempSync(join(tmpdir(), "memsearch-openclaw-b-"));
  try {
    withEnv("MEMSEARCH_DIR", undefined, () => {
      assert.notEqual(getCollectionScopeDir(a), getCollectionScopeDir(b));
    });
  } finally {
    rmSync(a, { recursive: true, force: true });
    rmSync(b, { recursive: true, force: true });
  }
});
