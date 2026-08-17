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

// ---------------------------------------------------------------------------
// Turn extraction
// ---------------------------------------------------------------------------

/** Lines that are structural or log noise rather than conversation content. */
const NOISE_PATTERNS = [
  /^\[memsearch\]/,
  /^Recent memories \(use memory_search/,
  /^```[a-z]*$/,
  /^WARNING:/,
  /^Error:/,
  /^# \d{4}-\d{2}-\d{2}$/,
  /^## Session \d{2}:\d{2}$/,
  /^### \d{2}:\d{2}$/,
  /^<!-- session:/,
];

export function isNoiseLine(line: string): boolean {
  const trimmed = line.trim();
  return NOISE_PATTERNS.some((pattern) => pattern.test(trimmed));
}

/** Extract meaningful text from a message's content blocks, dropping noise. */
export function extractText(content: unknown): string {
  let raw: string;
  if (typeof content === "string") {
    raw = content;
  } else if (Array.isArray(content)) {
    raw = content
      .filter((block: any) => block?.type === "text")
      .map((block: any) => block.text || "")
      .join("\n");
  } else {
    return "";
  }

  return raw
    .split("\n")
    .filter((line) => !isNoiseLine(line))
    .join("\n")
    .trim();
}

export function tailTruncate(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `...(truncated to tail)\n${text.slice(-maxChars)}`;
}

/**
 * Format the most recent user+assistant exchange from session entries.
 *
 * Takes entries rather than raw messages because pi sessions are a tree —
 * callers should pass `sessionManager.buildContextEntries()`, which resolves
 * the active branch and applies compaction. Returns null when there is no
 * substantive turn to capture.
 */
export function extractLastTurn(entries: any[]): string | null {
  const messages = entries
    .filter((entry) => entry?.type === "message" && entry.message)
    .map((entry) => entry.message);

  let lastUserIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role !== "user") continue;
    if (extractText(messages[i].content).length > 10) {
      lastUserIdx = i;
      break;
    }
  }
  if (lastUserIdx === -1) return null;

  const parts: string[] = [];
  for (let i = lastUserIdx; i < messages.length; i++) {
    const message = messages[i];
    const text = extractText(message?.content);
    if (!text || text.length < 5) continue;

    if (message.role === "user") {
      parts.push(`[User]: ${text}`);
    } else if (message.role === "assistant") {
      parts.push(`[Assistant]: ${tailTruncate(text, 3000)}`);
    }
  }

  return parts.length > 0 ? parts.join("\n\n") : null;
}
