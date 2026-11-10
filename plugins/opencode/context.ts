import type { SystemPart } from "@opencode/ai";
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

/** Marks the start of memsearch's injected block within a system message. */
export const MEMSEARCH_SYSTEM_MARKER = "[memsearch] Memory available.";

/** Fold into the first system part, retaining host metadata and idempotency. */
export function mergeSystemMemoryContext(system: SystemPart[] | undefined, memoryText: string): SystemPart[] {
  if (!system?.length) return [{ type: "text", text: memoryText }];
  const result = [...system];
  const first = result[0];
  const marker = first.text.indexOf(MEMSEARCH_SYSTEM_MARKER);
  const base = marker === -1 ? first.text : first.text.slice(0, marker).trimEnd();
  result[0] = { ...first, text: base ? `${base}\n\n${memoryText}` : memoryText };
  return result;
}
