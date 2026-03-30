# For Agent Developers

Build memory into your own agents using the memsearch CLI and Python API.

## Install

```bash
# pip
pip install memsearch

# or uv (recommended)
uv add memsearch
```

<details>
<summary><b>Optional embedding providers</b></summary>

```bash
pip install "memsearch[onnx]"    # Local ONNX (recommended, no API key)
# or: uv add "memsearch[onnx]"

# Other options: [openai], [google], [voyage], [ollama], [local], [all]
```

</details>

## Quick Example

```python
from memsearch import MemSearch

mem = MemSearch(paths=["./memory"])

# Index markdown files
await mem.index()

# Search
results = await mem.search("Redis config", top_k=3)
for r in results:
    print(r["heading"], r["score"])
```

## CLI

```bash
memsearch index ./memory                    # index markdown files
memsearch search "batch size" --top-k 5     # semantic search
memsearch expand <chunk_hash>               # expand a chunk
memsearch watch ./memory                    # live file watcher
```

See the full [CLI Reference →](../cli.md) and [Python API →](../python-api.md).

## How Plugins Use the API

All 4 platform plugins are built on top of the same CLI/API:

```
Plugin Capture:  conversation → LLM summary → append daily.md → memsearch index
Plugin Recall:   memsearch search → memsearch expand → parse-transcript
```

If you're building a plugin for a new platform, see the [Architecture](../architecture.md) and existing plugin source code in `plugins/`.
