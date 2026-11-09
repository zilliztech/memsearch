import { execFile, spawnSync } from "node:child_process";
import { accessSync, constants, existsSync, statSync } from "node:fs";
import { delimiter, join, resolve } from "node:path";
import { homedir } from "node:os";

export type Command = readonly [string, ...string[]];

function findExecutable(name: string, directories: string[]): string | undefined {
  for (const dir of directories.filter(Boolean)) {
    const file = resolve(dir.replace(/^"|"$/g, ""), process.platform === "win32" ? name + ".exe" : name);
    try {
      accessSync(file, constants.X_OK);
      if (statSync(file).isFile()) return file;
    } catch { /* Try the next directory. */ }
  }
}

export function detectCommand(): Command {
  const dirs = [...(process.env.PATH ?? "").split(delimiter), join(homedir(), ".local/bin")];
  const cli = findExecutable("memsearch", dirs);
  if (cli) return [cli];
  const uvx = findExecutable("uvx", dirs);
  if (uvx) return [uvx, "--from", "memsearch[onnx]", "memsearch"];
  throw new Error("MemSearch CLI unavailable. Install with uv tool install 'memsearch[onnx]'.");
}

let windowsPython: string | undefined;

export function pythonExecutable(): string {
  if (process.platform !== "win32") return "python3";
  if (windowsPython) return windowsPython;
  const dirs = (process.env.PATH ?? "").split(delimiter);
  for (const name of ["python3", "python", "py"]) {
    const launcher = findExecutable(name, dirs);
    if (!launcher) continue;
    // Ask the launcher for the interpreter; Store aliases may exist without an installation.
    const probe = spawnSync(launcher, [...(name === "py" ? ["-3"] : []), "-c",
      "import sys; assert sys.version_info >= (3, 11); print(sys.executable)"], {
      encoding: "utf8", env: pythonEnv(), windowsHide: true, timeout: 3000,
    });
    if (probe.status === 0 && probe.stdout.trim()) {
      windowsPython = probe.stdout.trim();
      return windowsPython;
    }
  }
  throw new Error("MemSearch requires Python 3.11 or later on PATH (python3, python or py -3).");
}

// The plugin exchanges UTF-8 over pipes, including when a helper starts the CLI.
export function pythonEnv() {
  return { ...process.env, PYTHONIOENCODING: "utf-8" };
}

export function run(command: Command, args: string[], cwd: string, signal?: AbortSignal, timeout = 120_000): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(command[0], [...command.slice(1), ...args], {
      cwd, signal, timeout, maxBuffer: 2 * 1024 * 1024, encoding: "utf8",
      env: { ...pythonEnv(), MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DIR: join(cwd, ".memsearch") },
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
