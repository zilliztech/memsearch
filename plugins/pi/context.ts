/**
 * Pure helpers for building cold-start memory context.
 * Kept free of process spawning so they stay easy to test.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

/** Marks memsearch's injected block within the system prompt. */
export const MEMSEARCH_HINT = "[memsearch] Memory available.";

/**
 * Pick the most informative lines from a daily journal.
 * Sections without a body are dropped so empty session headings do not
 * crowd out useful context.
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
    if (line.startsWith("- ")) {
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

/** Summarize the N most recent daily journals for cold-start context. */
export function getRecentMemories(
  memoryDir: string,
  count = 2,
  maxLinesPerFile = 30
): string {
  if (!existsSync(memoryDir)) return "";

  const files = readdirSync(memoryDir)
    .filter(isDailyJournalFile)
    .sort()
    .slice(-count);

  if (files.length === 0) return "";

  const summary: string[] = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memoryDir, file), "utf-8");
      const lines = recentMemoryPreviewLines(content, maxLinesPerFile);
      if (lines.length > 0) {
        summary.push(`[${file}]`, ...lines);
      }
    } catch {
      /* skip unreadable files */
    }
  }

  if (summary.length === 0) {
    return (
      `You have ${files.length} past memory file(s). ` +
      `Use memory_search when the user's question could benefit from historical context.`
    );
  }

  return `Recent memories (use memory_search for full search):\n${summary.join("\n")}`;
}

/** Single-quote a string for safe interpolation into a bash command. */
export function shellEscape(s: string): string {
  return s.replace(/'/g, "'\\''");
}
