# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np

def subconscious_evaluate(content_vec: np.ndarray, exp_index, config, now_ts: int) -> dict | None:
    """Run Subconscious Evaluator v1.5 (scripted cosine baseline).

    Compares content_vec against positive/negative experience vectors
    stored in ExperienceCluster instances. Applies exponential decay
    to negative vectors (negative_exp_lambda, floor=negative_exp_resolution_floor).

    Returns a signal dict {'signal': 'confidence'|'caution', 'score': float, 'tag': str}
    if max cosine exceeds intuition_fire_threshold, else None.

    Budget: ≤0.5ms (vectorised matmul, no per-vector loops).
    """
    if not exp_index or not config.experience.layer_enabled:
        return None

    min_samples = config.experience.cluster_min_samples
    lam = config.experience.negative_exp_lambda
    floor = config.experience.negative_exp_resolution_floor
    threshold = config.experience.intuition_fire_threshold

    best_confidence = 0.0
    best_confidence_tag = None

    best_caution = 0.0
    best_caution_tag = None

    for cluster in exp_index.all_clusters():
        if cluster.session_count < min_samples:
            continue

        # Evaluate positive vectors
        if cluster.positive_vecs:
            pos_matrix = np.stack([v[0] for v in cluster.positive_vecs])
            cosines = pos_matrix.dot(content_vec)
            max_pos = float(np.max(cosines))
            if max_pos > best_confidence:
                best_confidence = max_pos
                best_confidence_tag = cluster.tag

        # Evaluate negative vectors
        if cluster.negative_vecs:
            neg_matrix = np.stack([v[0] for v in cluster.negative_vecs])
            cosines = neg_matrix.dot(content_vec)
            
            w0_arr = np.array([v[1] for v in cluster.negative_vecs], dtype=np.float32)
            ts_arr = np.array([v[2] for v in cluster.negative_vecs], dtype=np.float32)
            
            age_days = (now_ts - ts_arr) / 86400.0
            decay = np.exp(-lam * age_days)
            weights = np.maximum(floor, w0_arr * decay)
            
            max_neg = float(np.max(cosines * weights))
            if max_neg > best_caution:
                best_caution = max_neg
                best_caution_tag = cluster.tag

    if best_caution >= threshold and best_caution >= best_confidence:
        return {"signal": "caution", "score": best_caution, "tag": best_caution_tag}
    elif best_confidence >= threshold:
        return {"signal": "confidence", "score": best_confidence, "tag": best_confidence_tag}

    return None
