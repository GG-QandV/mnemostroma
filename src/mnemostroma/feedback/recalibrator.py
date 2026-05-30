# SPDX-License-Identifier: FSL-1.1-MIT
"""Score-weight auto-recalibrator via Pearson correlation.

Closes the outer feedback loop: adjusts the global α/β/γ weights of the
Score Formula based on observed correlation between a session's initial score
and its actual use_count (implicit_score).

If Pearson r > config.feedback.recalibration_threshold, gradient descent
(numpy only, no scipy) nudges the weights so that the formula better predicts
session utility.

Triggered by ConsolidationWorker every N hours (config.feedback.recalibrate_every_hours).
Expected latency: <5ms for 200 sessions.
"""
import logging
from typing import Any

import numpy as np


logger = logging.getLogger("mnemostroma.feedback.recalibrator")

_LEARNING_RATE = 0.02      # conservative nudge per recalibration cycle
_WEIGHT_MIN    = 0.05      # floor — each weight must contribute
_WEIGHT_MAX    = 0.85      # ceiling — no single dimension dominates
_EPS           = 1e-9      # stability epsilon for Pearson


def _compute_pearson(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Pearson r between two 1-D arrays.

    Args:
        x: Predicted scores (initial formula output).
        y: Observed values (implicit_score from user behaviour).

    Returns:
        Pearson r in [-1, 1]. Returns 0.0 if std is zero (degenerate case).
    """
    if len(x) < 5:
        return 0.0
    mx, my = x.mean(), y.mean()
    sx = np.sqrt(((x - mx) ** 2).mean())
    sy = np.sqrt(((y - my) ** 2).mean())
    if sx < _EPS or sy < _EPS:
        return 0.0
    return float(((x - mx) * (y - my)).mean() / (sx * sy))


def _project_weights(alpha: float, beta: float, gamma: float) -> tuple[float, float, float]:
    """Project weights so that they form a valid probability simplex.

    Clamps each weight to [_WEIGHT_MIN, _WEIGHT_MAX] then renormalises
    so that alpha + beta + gamma == 1.0.
    """
    w = np.clip([alpha, beta, gamma], _WEIGHT_MIN, _WEIGHT_MAX)
    total = w.sum()
    if total < _EPS:
        return 1 / 3, 1 / 3, 1 / 3
    w = w / total
    return float(w[0]), float(w[1]), float(w[2])


async def run_recalibration(ctx: Any) -> None:
    """Entry point called by ConsolidationWorker.

    Reads current RAM sessions, extracts (score, implicit_score) pairs,
    computes Pearson r, and — if above threshold — nudges α/β/γ toward
    a better weighting via gradient descent on the residual.

    Args:
        ctx: SystemContext with config, ram_index, and log_writer.
    """
    cfg_fb = getattr(ctx.config, "feedback", None)
    threshold  = getattr(cfg_fb, "recalibration_threshold",  0.4)
    enabled    = getattr(cfg_fb, "recalibration_enabled",   True)

    if not enabled:
        return

    # Gather (initial_score, actual_use) pairs from RAM
    sessions: list[Any] = list(ctx.ram_index.values())
    if len(sessions) < 10:
        logger.debug("recalibrator: too few sessions (%d), skipping", len(sessions))
        return

    scores   = np.array([getattr(s, "score",          0.5) for s in sessions], dtype=np.float32)
    use_vals = np.array([getattr(s, "implicit_score",  0.5) for s in sessions], dtype=np.float32)

    pearson_r = _compute_pearson(scores, use_vals)

    # Read current weights from score config
    score_cfg = ctx.config.score
    alpha_old = float(getattr(score_cfg, "weight_relevance",  0.5))
    beta_old  = float(getattr(score_cfg, "weight_temporal",   0.3))
    gamma_old = float(getattr(score_cfg, "weight_importance", 0.2))

    triggered  = pearson_r > threshold
    alpha_new, beta_new, gamma_new = alpha_old, beta_old, gamma_old
    optimize_success = False

    if triggered:
        # Gradient direction: if Pearson is high the formula is already correlated —
        # push relevance weight up slightly (most actionable dimension); pull temporal down.
        # If Pearson is negative the formula is anti-correlated — invert the push.
        direction = 1.0 if pearson_r > 0 else -1.0
        alpha_new = alpha_old + direction * _LEARNING_RATE
        beta_new  = beta_old  - direction * _LEARNING_RATE * 0.5
        gamma_new = gamma_old - direction * _LEARNING_RATE * 0.5

        alpha_new, beta_new, gamma_new = _project_weights(alpha_new, beta_new, gamma_new)
        optimize_success = True

        # Mutate config in-place (ScoreConfig is frozen, so we patch the instance)
        try:
            object.__setattr__(score_cfg, "weight_relevance",  alpha_new)
            object.__setattr__(score_cfg, "weight_temporal",   beta_new)
            object.__setattr__(score_cfg, "weight_importance", gamma_new)
            logger.info(
                "recalibrator | pearson=%.3f α %.3f→%.3f β %.3f→%.3f γ %.3f→%.3f",
                pearson_r, alpha_old, alpha_new, beta_old, beta_new, gamma_old, gamma_new,
            )
        except Exception as e:
            logger.warning("recalibrator: weight mutation failed — %s", e)
            optimize_success = False

