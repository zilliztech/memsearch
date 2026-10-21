// Optional integration contract: node scripts/session-sdk-contract.mjs /path/to/openclaw
// Supply the installed host's redaction export module after the package directory
// to also exercise its actual model-facing tool-output redaction.
// Uses only task-owned synthetic sessions and public SDK exports. No model/TUI,
// authentication, network delivery or real MemSearch indexing is invoked.
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const host = resolve(process.argv[2] || "");
assert.ok(process.argv[2], "Supply an installed OpenClaw package directory");
const root = mkdtempSync(join(tmpdir(), "memsearch-session-sdk-"));
let retainFixture = false;
process.on("exit", () => { if (!retainFixture) rmSync(root, { recursive: true, force: true }); });
const state = join(root, "profile"), workspaceDir = join(root, "workspace");
process.env.OPENCLAW_STATE_DIR = state;
process.env.OPENCLAW_CONFIG_PATH = join(state, "openclaw.json");
process.env.OPENCLAW_PROFILE = "memsearch-session-sdk-fixture";
process.env.MEMSEARCH_DIR = join(workspaceDir, ".memsearch");
delete process.env.MEMSEARCH_NO_WATCH;
mkdirSync(join(state, "workspace"), { recursive: true });
mkdirSync(workspaceDir, { recursive: true });
const pluginPath = join(root, "plugin");
cpSync(resolve(dirname(fileURLToPath(import.meta.url)), ".."), pluginPath, {
  recursive: true, filter: path => !path.split("/").includes("node_modules"),
});
mkdirSync(join(pluginPath, "node_modules"));
symlinkSync(host, join(pluginPath, "node_modules/openclaw"), "dir");
const requireHost = createRequire(join(host, "package.json"));
const sdkImport = name => import(pathToFileURL(requireHost.resolve(`openclaw/plugin-sdk/${name}`)).href);
const sdk = await sdkImport("session-transcript-runtime");
const stores = await sdkImport("session-store-runtime");
const visibility = await sdkImport("session-visibility");
const { default: plugin, createTranscriptAccess } = await import(pathToFileURL(join(pluginPath, "index.js")));
const agentId = "review";
let cfg = { agents: { defaults: { workspace: workspaceDir } } };
const runtime = { state: { resolveStateDir: () => state }, agent: { session: {
  resolveStorePath: stores.resolveStorePath, getSessionEntryAsync: stores.getSessionEntryAsync,
} } };
const access = createTranscriptAccess(runtime, cfg);
const messages = [
  { role: "user", content: [{ type: "text", text: "Synthetic SDK contract fact: the copper pipit calibration code is 746." }], timestamp: Date.now() },
  { role: "assistant", content: [{ type: "text", text: "Recorded the synthetic copper pipit calibration code 746." }], timestamp: Date.now() },
];
async function session(label, metadata = {}) {
  const scope = { agentId, sessionId: randomUUID(), sessionKey: `agent:${agentId}:${label}`,
    storePath: stores.resolveStorePath(undefined, { agentId }) };
  await stores.upsertSessionEntry({ ...scope, entry: { sessionId: scope.sessionId, updatedAt: Date.now(), ...metadata } });
  for (const message of messages) await sdk.appendSessionTranscriptMessageByIdentity({ ...scope, message, cwd: workspaceDir });
  return scope;
}
const source = await session("capture"), fresh = await session("fresh");
let expired = false;
const caller = { ...fresh, workspaceDir, getRuntimeConfig: () => cfg,
  assertInvocationCurrent() { if (expired) throw new Error("fixture invocation expired"); } };
assert.equal("memoryAudience" in caller, false);
const hooks = new Map(), tools = new Map(), warnings = [];
plugin.register({ config: cfg, pluginConfig: {}, logger: { warn: message => warnings.push(message) }, runtime: {
  ...runtime, system: { async runCommandWithTimeout(argv) {
    const command = argv.join(" ");
    const stdout = argv[0] === "which" ? "/fixture/memsearch" :
      command.includes("derive-collection") ? "ms_sdk_fixture" :
      command.includes("config get") && command.includes("summarize.provider") ? "fixture" :
      command.includes("summarize --plugin") ? "- Synthetic copper pipit calibration code: 746." : "";
    return { stdout, stderr: "", code: 0 };
  } },
}, registerTool(factory, meta) { tools.set(meta.name, factory); }, registerCli() {},
  on(name, handler) { hooks.set(name, handler); } });
await hooks.get("agent_end")({ success: true, messages }, { ...source, workspaceDir });
const memoryDir = join(workspaceDir, ".memsearch/memory");
const memory = readFileSync(join(memoryDir, readdirSync(memoryDir).find(name => name.endsWith(".md"))), "utf8");
const reference = memory.match(/<!-- session:\S+ transcript:(\S+) -->/)?.[1];
assert.ok(reference?.startsWith("openclaw-session:"), JSON.stringify({ memory, warnings }));
assert.equal(existsSync(join(dirname(source.storePath), `${source.sessionId}.jsonl`)), false);
assert.ok(existsSync(join(state, `agents/${agentId}/agent/openclaw-agent.sqlite`)));
const tool = tools.get("memory_transcript")(caller);
const checks = [];
function record(name) { checks.push(name); }
async function allowed(name, ref = reference, ctx = caller) {
  const text = await access.read(ref, ctx);
  assert.match(text, /\[User\]:.*copper pipit/); assert.match(text, /\[Assistant\]:.*746/);
  record(name);
}
async function denied(name, ref = reference, ctx = caller, pattern = /./) {
  await assert.rejects(access.read(ref, ctx), pattern); record(name);
}
assert.equal(visibility.resolveEffectiveSessionToolsVisibility({ cfg, sandboxed: false }), "all");
const toolResult = await tool.execute("fresh-no-audience", { transcript_path: reference });
assert.match(toolResult.content[0].text, /\[User\]:.*copper pipit/);
record("hook-generated SQLite reference -> fresh session tool, default all, no audience");
if (process.argv[3]) {
  const { redactModelVisibleToolPayloadTextWithConfig: redact } = await import(pathToFileURL(resolve(process.argv[3])));
  assert.equal(typeof redact, "function", "Supply the host's named redaction export module");
  const credentialQuery = new URL(reference);
  credentialQuery.searchParams.delete("sessionKey");
  credentialQuery.searchParams.set("key", source.sessionKey);
  assert.notEqual(redact(credentialQuery.href, {}), credentialQuery.href,
    "The real credential-query redactor must remain active");
  for (const [name, payload] of [
    ["memory_get", memory],
    ["memory_search", JSON.stringify([{ chunk_hash: "fixture", content: memory }])],
  ]) {
    const visible = redact(payload, {});
    assert.equal(visible, payload, `${name} must preserve the emitted reference`);
    const content = name === "memory_search" ? JSON.parse(visible)[0].content : visible;
    const modelReference = content.match(/<!-- session:\S+ transcript:(\S+) -->/)?.[1];
    assert.equal(modelReference, reference);
    assert.equal(new URL(modelReference).searchParams.get("sessionKey"), source.sessionKey);
    const result = await tool.execute(`redacted-${name}`, { transcript_path: modelReference });
    assert.match(result.content[0].text, /\[User\]:.*copper pipit/);
    assert.match(result.content[0].text, /\[Assistant\]:.*746/);
    record(`${name} -> actual host redaction -> unchanged reference -> fresh transcript tool`);
  }
}
await allowed("default all");
cfg.tools = { sessions: { visibility: "agent" } }; await allowed("agent policy");
cfg.tools.sessions.visibility = "self";
await denied("self rejects historical key", reference, caller, /restricted/);
await allowed("self accepts exact current key/id", reference, { ...caller, ...source });
cfg.tools.sessions.visibility = "tree";
await denied("tree rejects unrelated session", reference, caller, /restricted/);
for (const field of ["spawnedBy", "parentSessionKey", "ownerSessionKey"]) {
  const child = await session(`child-${field.toLowerCase()}`, { [field]: fresh.sessionKey });
  await allowed(`tree accepts durable ${field}`, await access.capture(child));
}
await allowed("tree accepts canonical main requester", reference, { ...caller, sessionKey: "agent:review:main" });
const forgedOwnership = new URL(reference); forgedOwnership.searchParams.set("spawnedBy", fresh.sessionKey);
await denied("URI ownership does not grant tree access", forgedOwnership.href);
cfg.tools.sessions.visibility = "all";
for (const metadata of [{ visibility: "draft" }, { visibility: "read-only" }, { incognito: true }]) {
  const hidden = await session(`hidden-${checks.length}`, metadata);
  await denied(`reject target ${JSON.stringify(metadata)}`, await access.capture(hidden), caller, /metadata/);
}
const missing = new URL(reference); missing.searchParams.set("sessionKey", "agent:review:missing");
await denied("unknown exact key", missing.href, caller, /metadata/);
const forgedId = new URL(reference); forgedId.pathname = `/${fresh.sessionId}`;
await denied("forged target id", forgedId.href, caller, /metadata/);
const forgedKey = new URL(reference); forgedKey.searchParams.set("sessionKey", fresh.sessionKey);
await denied("existing key with another incarnation id", forgedKey.href, caller, /metadata/);
for (const [key, value] of [["store", "/foreign/profile/sessions.json"], ["sessionKey", "agent:other:capture"], ["sessionKey", "agent:review:incognito:fixture"]]) {
  const forged = new URL(reference); forged.searchParams.set(key, value);
  await denied(`forged ${key}=${value}`, forged.href);
}
await denied("foreign agent URI", reference.replace("//review/", "//other/"));
cfg.gateway = { roles: { reviewer: { sessionCap: "none" } } };
await denied("role-controlled cross-session access", reference, caller, /Role-controlled/);
cfg.gateway.roles = {};
await denied("configured empty roles still requires host authorization", reference, caller, /Role-controlled/);
delete cfg.gateway;
for (const override of [{ sandboxed: true }, { fsPolicy: { workspaceOnly: true } },
  { sessionKey: "agent:review:subagent:fixture" }, { sessionKey: "agent:review:acp:fixture" }]) {
  await denied(`unsupported caller ${JSON.stringify(override)}`, reference, { ...caller, ...override });
}
cfg.session = { scope: "global" }; await denied("global scope", reference, caller, /auxiliary\/global/); delete cfg.session;
expired = true; await denied("expired invocation", reference, caller, /expired/); expired = false;
const abort = new AbortController(); abort.abort(new Error("fixture aborted"));
const aborted = await tool.execute("aborted", { transcript_path: reference }, abort.signal);
assert.match(aborted.content[0].text, /fixture aborted/); record("tool abort signal");
const legacy = join(dirname(source.storePath), "fixture.jsonl");
mkdirSync(dirname(legacy), { recursive: true }); writeFileSync(legacy, messages.map(message => JSON.stringify({ message })).join("\n"));
await denied("modern host rejects JSONL policy bypass", legacy, caller, /SDK-generated/);
// The exact metadata accessor must remain available; SDK identity alone is insufficient.
const noMetadata = createTranscriptAccess({ ...runtime, agent: { session: { resolveStorePath: stores.resolveStorePath } } }, cfg);
await assert.rejects(noMetadata.read(reference, caller), /confirm target session metadata/); record("missing metadata accessor fails closed");
const result = { status: "PASS", hostVersion: JSON.parse(readFileSync(join(host, "package.json"))).version,
  validation: "Synthetic public SDK SQLite + real policy + plugin hook/tool contract; no model/TUI E2E", checks,
  source, fresh, referenceGeneratedByHook: reference, state, workspaceDir, warnings };
console.log(JSON.stringify(result, null, 2));
// An optional test-artifact output retains only these synthetic sessions for a
// separate actual-host-loader check. Normal invocations remove their temp root.
if (process.env.MEMSEARCH_SDK_TEST_RESULT) {
  writeFileSync(process.env.MEMSEARCH_SDK_TEST_RESULT, JSON.stringify(result, null, 2));
  retainFixture = true;
}
process.exit(0);
