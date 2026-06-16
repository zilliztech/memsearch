# Skills from Memory

Most memory systems remember **what happened**. MemSearch goes one step further:
it notices **how you work**, and offers to turn that into capability.

This is the third layer of memory:

| Layer | Question it answers | Where it lives |
| --- | --- | --- |
| Episodic | *What happened?* | `.memsearch/memory/*.md` — raw conversation journals |
| Semantic | *What is true?* | `.memsearch/PROJECT.md`, `.memsearch/USER.md` — durable facts |
| **Procedural** | ***How do I do this?*** | `.memsearch/skill-candidates/` — reusable skills |

A *skill* is just an [Agent Skills](https://agentskills.io)-standard `SKILL.md`: a
short, reusable procedure — how to run the app, how to deploy, how to debug a
class of error. The interesting part isn't the file format; it's where the
procedure comes from. **It comes from your own memory.** A workflow you keep
repeating is, by definition, procedural knowledge you already have — MemSearch
just makes it explicit, reusable, and portable across your agents.

## How you use it

You don't run commands. You talk to your agent:

- *"Make a skill out of what we just did."* — it drafts the procedure (reading the
  original transcript so the steps are exact), saves it as a candidate, and offers
  to install it.
- *"What skill candidates do I have? Install the deploy one."* — it shows what has
  been collected and installs the one you choose, which becomes a real
  `/`-command in that agent.

Enabling and tuning are the same: *"turn on MemSearch skill distillation"* and the
agent configures it for you. The whole surface is a conversation; the CLI exists
underneath, but it's plumbing the agent drives, not something you memorize.

## Design philosophy

A few deliberate stances shape how this behaves — they matter more than any flag.

**Repetition is the signal.** A one-off doesn't deserve to be a skill; a workflow
earns skill-hood by *recurring*. The unattended background pass waits for several
recurrences before it proposes anything. When *you* explicitly ask, your request
*is* the signal — so on-demand capture will gladly make a skill from a single
session.

**Humans decide what becomes real.** Distillation only ever produces *candidates*
— inert drafts in a store no agent reads. Nothing turns into a live, auto-loading
skill until a person installs it. A wrong note is harmless; a wrong skill that
fires on its own is actively harmful, so activation is always a human act:
the machine proposes, you dispose.

**Markdown + git is the source of truth.** The candidate store is a real git
repository. Every distillation and revision is a commit you can diff and revert;
the store keeps evolving (even for skills you've already installed), and
installing simply takes a snapshot out. Because history is never lost, the system
can be aggressive about improving candidates without being dangerous.

**Only generation needs a model.** Turning raw history into a procedure takes
judgment — that single step uses an LLM. Saving a candidate and installing it are
plain file-and-git operations. Keeping that boundary sharp is what lets the same
skill be produced by a background model, by the live agent, or even hand-written,
and stay structurally identical.

**Fidelity comes from the original, not the summary.** The journals are *lossy
summaries*. A skill written from a summary alone tends to be plausible but wrong.
The agent you're talking to can open the original transcripts and recover the
exact commands and paths — so on-demand capture is the high-fidelity path. The
unattended background pass is sandboxed away from those transcripts, so it is held
to a humbler standard: capture only what the summaries clearly state, and never
invent detail. We'd rather it produce a vaguer-but-correct skill than a
confident-but-wrong one — and we tell you to prefer on-demand capture when fidelity
matters.

**Off by default.** Procedural memory that's wrong is worse than none, so the
background pass starts disabled and stays conservative. You opt in.

## Under the hood

Stages: **0** journals → **1** candidate → **2** installed. Candidates are created
two ways — the **background** pass mines recurring workflows on the session-end
cadence (model-driven, opt-in), and **on-demand** capture has the live agent draft
from the originals (no provider config, no recurrence threshold). Installing is
always manual and just copies the candidate's current `SKILL.md` into the agent's
skill directory:

| Agent | Skill directory |
| --- | --- |
| Claude Code | `.claude/skills/` (or `~/.claude/skills/`) |
| Codex / OpenCode / Cursor … | `.agents/skills/` (the shared standard; **not** read by Claude Code) |
| OpenClaw | `.openclaw/skills/` |

A skill can be installed to several directories at once to cover multiple agents.

## Configuration

You normally configure this by asking your agent (it uses the `memory-config`
skill). If you prefer editing files, the settings live under
`[plugins.<agent>.memory_to_skill]` — `enabled` (off by default), `min_occurrences`
(how many recurrences the background pass needs, default 3), `paths` (install
targets), plus the shared `provider` / `model` / `min_interval_hours` / `input_dir`
and a `prompts.memory_to_skill` override. See
[Configuration](configuration.md#skills-from-memory-procedural-memory) for the
exact keys; they mirror the [maintenance tasks](configuration.md#advanced-plugin-maintenance).

The plugin-installed `/memory-to-skill` skill drives the whole flow from natural
language and never enables anything, changes install paths, or installs a
candidate without your go-ahead.
