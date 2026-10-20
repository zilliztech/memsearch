import { Plugin, Skill } from "@opencode/plugin";
import { Schema } from "effect";
import { readFileSync, realpathSync } from "node:fs";
import { join } from "node:path";

export function loadSkills(pluginDir: string): Skill.Info[] {
  return ["memory-recall", "memory-config", "memory-to-skill"].map(name => {
    const path = realpathSync(join(pluginDir, "skills", name, "SKILL.md"));
    const raw = readFileSync(path, "utf8");
    const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
    if (!match) throw new Error(`Missing skill frontmatter: ${name}`);
    const value = match[1].match(/^description:\s*(.+)$/m)?.[1] ?? name;
    const description = value.startsWith('"') ? JSON.parse(value) : value;
    return Schema.decodeUnknownSync(Skill.Info)({ id: `memsearch:${name}`, name, path, description, content: match[2], autoinvoke: true });
  });
}

export async function registerSkills(ctx: Plugin.Context, pluginDir: string) {
  const skills = loadSkills(pluginDir);
  return ctx.skill.transform(editor => {
    for (const skill of skills) {
      // One deterministic packaged definition even when an older filesystem copy is discovered.
      for (const prior of editor.list()) if (prior.name === skill.name) editor.remove(String(prior.id));
      editor.add(skill);
    }
  });
}
