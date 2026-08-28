import { execFileSync } from "node:child_process";

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
    return "ms_opencode_default";
  }
}
