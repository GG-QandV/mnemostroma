# Direct measurement of one SessionBrief weight in RAM

**Date:** 2026-07-28  
**Method:** Using `tracemalloc` to measure memory increase when creating 200 `SessionBrief` objects (without embeddings or content fields).  
**Environment:** Python 3.11.15 (system), but measurement should be representative.

## Measurement Procedure

```python
import sys
sys.path.insert(0, "/home/gg/projects/Project_mnemostroma/src")
import tracemalloc
from mnemostroma.memory.session_index import SessionBrief
import time

tracemalloc.start()
snap1 = tracemalloc.take_snapshot()

sessions = []
now = int(time.time())
for i in range(200):
    sb = SessionBrief(
        session_id=f"test_{i}",
        brief="Test session brief text of typical length for realistic measurement purposes here",
        tags=["tag1", "tag2", "tag3"],
        importance="background",
        score=0.5,
        resolution=1.0,
        created_at=now - i,
    )
    sessions.append(sb)

snap2 = tracemalloc.take_snapshot()
stats = snap2.compare_to(snap1, "lineno")
total = sum(stat.size_diff for stat in stats)
print(f"200 sessions total: {total/1024/1024:.2f} MB")
print(f"Per session: {total/200/1024:.2f} KB")
```

## Result

- **200 sessions total:** 0.08 MB  
- **Per session:** 0.41 KB

## Interpretation

This figure reflects only the memory overhead of the `SessionBrief` dataclass instance itself (its fields: strings, lists, integers, floats, optional fields). It does **not** include:

- The embedding vector (`np.ndarray` of shape (384,) dtype float32) → 384 × 4 bytes = **1.5 KB** per session.
- Potentially large `content_full` or `brief` strings (if longer than the test string).
- Any internal overhead of the container storing these sessions (e.g., list, dict, or custom index structure).

Therefore, a realistic in‑RAM session (with embedding and typical text) is likely in the range:

```
SessionBrief base          ~0.4 KB
Embedding (float32[384])   ~1.5 KB
Brief/tags/other strings   ~1‑2 KB (depending on length)
-------------------------------------------------
Total per session estimate ~3‑4 KB
```

For the configured `session_window_size = 200`, this contributes roughly **0.6‑0.8 MB** to RAM — far less than the earlier rough estimate of 2‑20 MB. The dominant variable memory consumers are likely the **content block store** (`content_max_blocks = 500`) and any additional caching layers, not the session descriptors themselves.

## Conclusion

The direct measurement shows that the `SessionBrief` object is very lightweight (~0.4 KB). The main variable memory usage under load must come from other stored data (embeddings, content blocks, or other cached structures). This helps clarify that the observed 600‑700 MB RSS under load is not driven by the session descriptors but by larger blobs such as embeddings and content blocks.

---
*Recorded in the audit folder for reference.*