# Installation

## Prerequisites

- OpenClaw >= 2026.3.22
- Python 3.10+
- memsearch installed: `uv tool install "memsearch[onnx]"`

## Install

```bash
# 1. Clone the memsearch repo (if not already)
git clone https://github.com/zilliztech/memsearch.git

# 2. Install the OpenClaw plugin
openclaw plugins install ./memsearch/plugins/openclaw

# 3. Restart the gateway
openclaw gateway restart
```

## Configuration

```bash
openclaw plugins config memsearch
```

| Setting | Default | Description |
|---------|---------|-------------|
| `provider` | `onnx` | Embedding provider |
| `autoCapture` | `true` | Auto-capture conversations |
| `autoRecall` | `true` | Auto-inject recent memories on agent start |

For Milvus backend configuration, run `memsearch config set milvus.uri <uri>`.

## Uninstall

```bash
openclaw plugins uninstall memsearch
openclaw gateway restart
```
