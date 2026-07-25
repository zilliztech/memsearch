/**
 * memsearch pi plugin — semantic memory search across sessions.
 *
 * Stage 1 (foundation):
 * - session_start hook: ensure default config + initial background index
 *
 * Memory is shared with the Claude Code, Codex, OpenCode, and OpenClaw plugins:
 * the collection name is derived from the project path via the shared
 * derive-collection.sh, and memories live in <project>/.memsearch/memory/.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getMemsearchDir(projectDir: string): string {
  return join(projectDir, ".memsearch");
}

function getMemoryDir(projectDir: string): string {
  return join(getMemsearchDir(projectDir), "memory");
}

/** Single-quote a string for safe interpolation into a bash command. */
function shellEscape(s: string): string {
  return s.replace(/'/g, "'\\''");
}

/**
 * Detect the memsearch CLI invocation.
 * Checks: PATH -> ~/.local/bin/uvx -> uvx in PATH.
 */
async function detectMemsearchCmd(): Promise<string> {
  const home = process.env.HOME || "";

  try {
    await execFileAsync("which", ["memsearch"]);
    return "memsearch";
  } catch {
    /* not on PATH */
  }

  const uvxPath = join(home, ".local", "bin", "uvx");
  if (existsSync(uvxPath)) {
    return `${uvxPath} --from 'memsearch[onnx]' memsearch`;
  }

  try {
    await execFileAsync("which", ["uvx"]);
    return "uvx --from 'memsearch[onnx]' memsearch";
  } catch {
    /* not on PATH */
  }

  return "memsearch";
}

/**
 * Derive the per-project Milvus collection name via the shared script.
 * Must stay byte-identical to the other plugins' copies so memories are shared.
 */
async function deriveCollectionName(projectDir: string): Promise<string> {
  const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
  try {
    const { stdout } = await execFileAsync("bash", [script, projectDir], {
      timeout: 5000,
    });
    return stdout.trim();
  } catch {
    return "ms_pi_default";
  }
}

// ---------------------------------------------------------------------------
// Extension entry
// ---------------------------------------------------------------------------

export default async function (pi: ExtensionAPI) {
  pi.on("session_start", async (_event, ctx) => {
    const projectDir = ctx.cwd;
    const memoryDir = getMemoryDir(projectDir);
    const home = process.env.HOME || "";

    try {
      const cmd = await detectMemsearchCmd();
      const collection = await deriveCollectionName(projectDir);

      // Ensure default config (onnx provider, no API key needed)
      const globalConfig = join(home, ".memsearch", "config.toml");
      const localConfig = join(projectDir, ".memsearch.toml");
      if (!existsSync(globalConfig) && !existsSync(localConfig)) {
        try {
          await execFileAsync(
            "bash",
            ["-c", `${cmd} config set embedding.provider onnx`],
            { timeout: 5000 }
          );
        } catch {
          /* best-effort */
        }
      }

      // Initial index in the background (fire-and-forget)
      if (existsSync(memoryDir)) {
        execFileAsync(
          "bash",
          [
            "-c",
            `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`,
          ],
          { timeout: 120000 }
        ).catch(() => {
          /* index failures must not break the session */
        });
      }

      ctx.ui.notify(`[memsearch] collection: ${collection}`, "info");
    } catch {
      /* never block session startup */
    }
  });
}
