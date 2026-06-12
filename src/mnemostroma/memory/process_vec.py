# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np

def build_process_vec(step_log: list[dict], embedder) -> np.ndarray:
    """Build a process vector summarising a session's step pattern.

    Encodes the sequence of importance levels and dominant tags into a
    single embedding that captures *how* the session progressed, not what
    it was about. Used as training signal for Pattern Encoder v3.0.

    Args:
        step_log: List of step entries with keys 'importance', 'tags'.
        embedder: Embedder instance with .encode(text) -> np.ndarray.

    Returns:
        384-dim float32 ndarray (multilingual-e5-small output).
    """
    pattern = " ".join(e["importance"] for e in step_log)
    all_tags = [t for e in step_log for t in e.get("tags", [])]
    tag_summary = " ".join(dict.fromkeys(all_tags[:10]))  # dedup, сохранить порядок
    process_text = f"process: {pattern} topics: {tag_summary}"
    return embedder.encode(process_text)
