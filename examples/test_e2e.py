import asyncio
import time
from memsearch import MemSearch

mem = MemSearch(
    paths=["./examples/sample-memory/"],
    milvus_uri="http://10.100.30.11:19530",
)

# 首先索引现有文件
asyncio.run(mem.index())

# 开始监视
def on_event(event_type, summary, file_path):
    print(f"[{event_type}] {summary}")

watcher = mem.watch(on_event=on_event)
print("Watching for changes... (Ctrl+C to stop)")
print("Try editing examples/sample-memory/memory/2026-02-08.md in another terminal")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    watcher.stop()
    mem.close()