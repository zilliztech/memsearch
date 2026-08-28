import test from "node:test";
import assert from "node:assert/strict";

import { deriveCollectionNameFromScript } from "./derive-collection.ts";

const SCRIPT_PATH = "/opt/memsearch/scripts/derive-collection.sh";

for (const projectDir of [
  "/tmp/project",
  "/tmp/project with spaces",
  "/tmp/project's",
  "/tmp/project\"name",
  String.raw`/tmp/project\segment`,
  "-leading-dash",
  "/tmp/项目-α",
]) {
  test(`passes the project path as one literal argv entry: ${JSON.stringify(projectDir)}`, () => {
    const calls: Array<{ file: string; args: string[]; options: unknown }> = [];
    const result = deriveCollectionNameFromScript(
      SCRIPT_PATH,
      projectDir,
      (file, args, options) => {
        calls.push({ file, args: [...args], options });
        return "ms_recorded_12345678\n";
      }
    );

    assert.equal(result, "ms_recorded_12345678");
    assert.deepEqual(calls, [
      {
        file: "bash",
        args: [SCRIPT_PATH, projectDir],
        options: { encoding: "utf-8", timeout: 5000 },
      },
    ]);
  });
}

test("returns the existing fallback when collection derivation fails", () => {
  const result = deriveCollectionNameFromScript(
    SCRIPT_PATH,
    "/tmp/project",
    () => {
      throw new Error("recorded failure");
    }
  );

  assert.equal(result, "ms_opencode_default");
});
