import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import { posix } from "node:path";

type CollectionCommandRunner = (
  file: string,
  args: string[],
  options: { encoding: "utf-8"; timeout: number }
) => string;

const runCollectionCommand: CollectionCommandRunner = (file, args, options) =>
  execFileSync(file, args, options);

export function deriveCollectionNameFromScript(
  script: string,
  projectDir: string,
  run: CollectionCommandRunner = runCollectionCommand
): string {
  try {
    return run("bash", [script, projectDir], {
      encoding: "utf-8",
      timeout: 5000,
    }).trim();
  } catch {
    if (process.platform === "win32") {
      // Match Git Bash's physical /c/path spelling when bash is unavailable.
      const physical = realpathSync.native(projectDir).replaceAll("\\", "/");
      const path = physical.replace(/^([a-z]):\//i, (_, drive: string) => "/" + drive.toLowerCase() + "/")
        .replace(/\/$/, "");
      const slug = posix.basename(path).replace(/[A-Z]/g, c => c.toLowerCase()).replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
      const hash = createHash("sha256").update(path).digest("hex").slice(0, 8);
      return `ms_${slug}_${hash}`;
    }
    throw new Error("Could not derive a project-specific memory collection; refusing a shared fallback.");
  }
}
