# For Agent Users

Pick your platform, install the plugin, and you're done. memsearch captures conversations, indexes them, and recalls relevant context — all automatically.

## Choose Your Platform

| Platform | Install | Maturity |
|----------|---------|----------|
| [**Claude Code**](../platforms/claude-code/index.md) | Marketplace or `--plugin-dir` | Most mature |
| [**OpenClaw**](../platforms/openclaw/index.md) | `openclaw plugins install` | Stable |
| [**OpenCode**](../platforms/opencode/index.md) | Add to `opencode.json` plugin array | Stable |
| [**Codex CLI**](../platforms/codex/index.md) | `bash install.sh` | Stable |

## What Happens Automatically

Once installed, the plugin handles everything:

| When | What |
|------|------|
| **Session starts** | Recent memories injected as context |
| **Each turn ends** | Conversation summarized and saved to daily `.md` |
| **You ask about history** | Agent searches memory via built-in tools/skill |

## How Recall Works (3 Layers)

Plugins use **progressive disclosure** — the agent decides how deep to go:

1. **L1 (search)** — find relevant chunks via semantic + keyword hybrid search
2. **L2 (expand)** — get full markdown sections around a match
3. **L3 (transcript)** — drill into the original conversation for exact dialogue

Simple questions stop at L1. Complex questions go deeper.

## Platform Details

Each platform adapts the same architecture to its own plugin system:

- **Claude Code**: [Full guide →](../platforms/claude-code/index.md)
- **OpenClaw**: [Full guide →](../platforms/openclaw/index.md)
- **OpenCode**: [Full guide →](../platforms/opencode/index.md)
- **Codex CLI**: [Full guide →](../platforms/codex/index.md)

See the [Platform Comparison](../platforms/index.md) for a detailed feature matrix.
