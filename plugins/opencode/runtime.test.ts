import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deriveCollectionNameFromScript } from "./derive-collection.ts";
import { detectCommand, pythonExecutable } from "./runtime.ts";

test("Windows discovers runnable CLI launchers and a native Python 3", { skip: process.platform !== "win32" }, t => {
  const temp = mkdtempSync(join(tmpdir(), "memsearch launchers-"));
  const original = process.env.PATH;
  const profile = process.env.USERPROFILE!;
  t.after(() => {
    process.env.PATH = original;
    process.env.USERPROFILE = profile;
    rmSync(temp, { recursive: true, force: true });
  });
  const python = pythonExecutable();
  assert.equal(execFileSync(python, ["-c", "print(42)"], { encoding: "utf8" }).trim(), "42");

  const cli = execFileSync("where.exe", ["memsearch.exe"], { encoding: "utf8" }).trim().split(/\r?\n/)[0];
  const uvx = execFileSync("where.exe", ["uvx.exe"], { encoding: "utf8" }).trim().split(/\r?\n/)[0];
  process.env.PATH = temp;
  process.env.USERPROFILE = temp;
  assert.throws(detectCommand, /CLI unavailable/);
  copyFileSync(uvx, join(temp, "uvx.exe"));
  assert.deepEqual(detectCommand(), [join(temp, "uvx.exe"), "--from", "memsearch[onnx]", "memsearch"]);
  process.env.PATH = [temp, dirname(cli)].join(";");
  assert.deepEqual(detectCommand(), [cli]);
  assert.match(execFileSync(detectCommand()[0], ["--version"], { encoding: "utf8" }), /memsearch, version/);
});

test("Windows without bash uses the same collection as Git Bash", { skip: process.platform !== "win32" }, t => {
  const project = mkdtempSync(join(tmpdir(), "Project 中文-"));
  t.after(() => rmSync(project, { recursive: true, force: true }));
  const script = fileURLToPath(new URL("./scripts/derive-collection.sh", import.meta.url));
  const bash = join(process.env.ProgramFiles!, "Git", "bin", "bash.exe");
  const legacy = execFileSync(bash, [script, project], { encoding: "utf8" }).trim();
  const fallback = deriveCollectionNameFromScript(script, project, () => { throw new Error("bash unavailable"); });
  assert.equal(fallback, legacy);
});
