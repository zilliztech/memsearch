import { execFile, spawnSync } from "node:child_process";
import { accessSync, constants, existsSync } from "node:fs";
import { delimiter, join } from "node:path";
import { homedir } from "node:os";

export type Command = readonly [string, ...string[]];

export function detectCommand(): Command {
  for (const name of ["memsearch", "uvx"]) {
    for (const dir of [...(process.env.PATH ?? "").split(delimiter), join(homedir(), ".local/bin")]) {
      const file = join(dir, name);
      try {
        accessSync(file, constants.X_OK);
        return name === "memsearch" ? [file] : [file, "--from", "memsearch[onnx]", "memsearch"];
      } catch { /* Try the next installed executable. */ }
    }
  }
  throw new Error("MemSearch CLI unavailable. Install with uv tool install 'memsearch[onnx]'.");
}

export function run(command: Command, args: string[], cwd: string, signal?: AbortSignal, timeout = 120_000): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(command[0], [...command.slice(1), ...args], {
      cwd, signal, timeout, maxBuffer: 2 * 1024 * 1024, encoding: "utf8",
      env: { ...process.env, MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DIR: join(cwd, ".memsearch") },
    }, (error, stdout) => {
      // Provider errors may contain request details. Keep these out of host context.
      if (error) reject(new Error(`MemSearch ${args[0] ?? "command"} failed; check CLI/configuration and .memsearch/.index-state.json.`));
      else resolve(stdout.trim());
    });
  });
}

/** Keep the plugin's zero-config embedding default without writing shared configuration. */
export function embeddingArgs(root: string): string[] {
  return !existsSync(join(homedir(), ".memsearch/config.toml")) && !existsSync(join(root, ".memsearch.toml"))
    ? ["--provider", "onnx"] : [];
}

export function projectRoot(directory: string): string {
  const result = spawnSync("git", ["-C", directory, "rev-parse", "--show-toplevel"], { encoding: "utf8", timeout: 5000 });
  return result.status === 0 ? result.stdout.trim() : directory;
}
