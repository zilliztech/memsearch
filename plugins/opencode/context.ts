import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/**
 * Summarize the N most recent daily .md files for cold-start context.
 * Extracts recent non-empty session sections so empty SessionStart headings
 * do not crowd out useful context.
 */
function recentMemoryPreviewLines(content: string, maxLines: number): string[] {
  const sections: string[][] = [];
  let current: string[] = [];
  let hasBody = false;

  const flush = () => {
    if (current.length > 0 && hasBody) {
      sections.push(current);
    }
    current = [];
    hasBody = false;
  };

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trimEnd();
    if (/^##\s/.test(line)) {
      flush();
      current = [line];
      continue;
    }
    if (/^#{3,4}\s/.test(line)) {
      current.push(line);
      continue;
    }
    if (line.startsWith("- ") || line.startsWith("[User]") || line.startsWith("[Assistant]")) {
      current.push(line);
      hasBody = true;
    }
  }

  flush();
  return sections.flat().slice(-maxLines);
}

export function isDailyJournalFile(file: string): boolean {
  return /^\d{4}-\d{2}-\d{2}\.md$/.test(file);
}

export function getRecentMemories(
  memDir: string,
  count = 2,
  maxLinesPerFile = 30
): string {
  if (!existsSync(memDir)) return "";

  const files = readdirSync(memDir)
    .filter(isDailyJournalFile)
    .sort()
    .slice(-count);

  if (files.length === 0) return "";

  const summary: string[] = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memDir, file), "utf-8");
      const lines = recentMemoryPreviewLines(content, maxLinesPerFile);
      if (lines.length > 0) {
        summary.push(`[${file}]`, ...lines);
      }
    } catch { /* skip */ }
  }

  if (summary.length === 0) {
    return `You have ${files.length} past memory file(s). Use the memory_search tool when the user's question could benefit from historical context.`;
  }

  return `Recent memories (use memory_search for full search):\n${summary.join("\n")}`;
}

/** Shell-escape a string for safe use inside single quotes. */
export function shellEscape(s: string): string {
  return s.replace(/'/g, "'\\''");
}

export function getSkillCandidateHint(memsearchDir: string, memsearchCmd: string): string {
  try {
    const result = spawnSync(
      "bash",
      [
        "-c",
        `MEMSEARCH_DIR='${shellEscape(memsearchDir)}' ${memsearchCmd} skills status --hint`,
      ],
      { encoding: "utf-8", timeout: 5000 }
    );
    if (result.status !== 0) return "";
    return (result.stdout || "").trim().split("\n")[0] || "";
  } catch {
    return "";
  }
}

/** Marks the start of memsearch's injected block within a system message. */
export const MEMSEARCH_SYSTEM_MARKER = "[memsearch] Memory available.";

/**
 * Merge memsearch's memory context into an `output.system` array without
 * growing it. Some backends (litellm/vllm serving e.g. Qwen models) reject a
 * multi-entry `output.system` array with "system message must be first", so
 * the memory block is folded into the first entry instead of pushed as a new
 * one. If a memsearch block from a previous transform call is already present
 * (identified by MEMSEARCH_SYSTEM_MARKER), it is replaced in place rather than
 * appended again, so repeated calls against the same output stay idempotent.
 */
export function mergeSystemMemoryContext(
  system: string[] | undefined,
  memoryText: string
): string[] {
  if (!Array.isArray(system) || system.length === 0) {
    return [memoryText];
  }
  const result = [...system];
  const existing = result[0];
  const markerIndex = existing.indexOf(MEMSEARCH_SYSTEM_MARKER);
  const base =
    markerIndex === -1 ? existing : existing.slice(0, markerIndex).replace(/\n+$/, "");
  result[0] = base ? `${base}\n\n${memoryText}` : memoryText;
  return result;
}
