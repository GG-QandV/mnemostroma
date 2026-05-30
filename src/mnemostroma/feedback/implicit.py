# SPDX-License-Identifier: FSL-1.1-MIT
"""Implicit Feedback Loop — v1.5 implementation.

Observes agent behavior to infer session usefulness without requiring
any explicit agent-side feedback calls. Signals are captured at the
tool layer and fed into an EMA-based implicit_score per session.

Spec: feedback_loop_v1.5.md
"""
import logging
import time

from ..core import SystemContext

logger = logging.getLogger("mnemostroma.feedback")

# Threshold for rapid re-query detection (seconds)
# Now managed via ctx.config.feedback


async def record_signal(
    session_id: str,
    signal: str,
    ctx: SystemContext,
) -> None:
    """Record an implicit feedback signal for a session and update implicit_score.

    Applies an EMA update per spec (v1.5 § 5):
        new_score = old * 0.9 + (0.5 + weight * 0.1)
    Score is clamped to [0.0, 1.0].
    """
    if session_id not in ctx.ram_index:
        return

    sb = ctx.ram_index[session_id]
    
    # Read from central config
    config = ctx.config.feedback
    alpha = config.ema_alpha
    weights = config.weights
    
    weight = weights.get(signal, 0.0)
    old_score = getattr(sb, "implicit_score", 0.5)

    # EMA update exactly as per feedback_loop_v1.5.md § 5 (Corrected for baseline scaling)
    # Formula: new_score = current * 0.9 + (0.5 + w) * 0.1
    new_score = old_score * (1 - alpha) + (0.5 + weight) * alpha
    sb.implicit_score = max(0.0, min(1.0, new_score))

    # Increment use_count for USE / REVISIT signals
    if signal in ("USE", "DEEP_USE", "REVISIT"):
        sb.use_count = getattr(sb, "use_count", 0) + 1


    logger.debug(
        f"Feedback {signal} for {session_id}: "
        f"implicit_score {old_score:.3f} → {sb.implicit_score:.3f}"
    )


async def signal_use(session_id: str, ctx: SystemContext) -> None:
    """Emit a USE signal — session was retrieved and likely acted upon."""
    await record_signal(session_id, "USE", ctx)


async def signal_deep_use(session_id: str, ctx: SystemContext) -> None:
    """Emit a DEEP_USE signal — agent requested full session content."""
    await record_signal(session_id, "DEEP_USE", ctx)


async def signal_ignore(session_id: str, ctx: SystemContext) -> None:
    """Emit an IGNORE signal — session appeared in results but agent re-queried quickly."""
    await record_signal(session_id, "IGNORE", ctx)


async def signal_revisit(session_id: str, ctx: SystemContext) -> None:
    """Emit a REVISIT signal — same session retrieved 3+ times in current working session."""
    await record_signal(session_id, "REVISIT", ctx)


class ImplicitFeedbackTracker:
    """Stateful tracker that detects rapid re-query (IGNORE) and REVISIT patterns.

    Attach one instance to the SystemContext; feed it tool call events
    so it can derive IGNORE and REVISIT signals automatically.

    Args:
        ctx: System context.
        ignore_window_sec: Seconds within which a second semantic query triggers IGNORE.
        revisit_threshold: Number of retrievals within a session to trigger REVISIT.
    """

    def __init__(
        self,
        ctx: SystemContext,
        ignore_window_sec: float | None = None,
        revisit_threshold: int | None = None,
    ) -> None:
        self.ctx = ctx
        config = ctx.config.feedback
        self.ignore_window_sec = ignore_window_sec if ignore_window_sec is not None else config.ignore_window_sec
        self.revisit_threshold = revisit_threshold if revisit_threshold is not None else config.revisit_threshold

        # {session_id: list[ts]} — tracks retrieval timestamps in this working session
        self._retrieval_history: dict[str, list] = {}
        self._last_semantic_ts: float | None = None
        self._last_semantic_ids: list = []

    async def on_semantic_query(self, returned_ids: list) -> None:
        """Called after ctx.semantic() completes with the returned session IDs.

        Detects IGNORE (rapid re-query): if a second semantic query arrives
        within the window, mark previously returned sessions as IGNORE.
        Records USE for sessions from the previous call that survived the window.
        """
        now = time.time()

        if (
            self._last_semantic_ts is not None and
            (now - self._last_semantic_ts) < self.ignore_window_sec
        ):
            # Rapid re-query → IGNORE all sessions from last call
            for sid in self._last_semantic_ids:
                await signal_ignore(sid, self.ctx)
        else:
            # Sufficient gap → treat previous results as implicitly used
            for sid in self._last_semantic_ids:
                await self._record_retrieval(sid)

        self._last_semantic_ts = now
        self._last_semantic_ids = list(returned_ids)

    async def on_get(self, session_id: str) -> None:
        """Called after ctx.get() completes. Emits USE or REVISIT."""
        await self._record_retrieval(session_id)

    async def _record_retrieval(self, session_id: str) -> None:
        """Track retrieval and emit USE or REVISIT depending on frequency."""
        now = time.time()
        if session_id not in self._retrieval_history:
            self._retrieval_history[session_id] = []

        self._retrieval_history[session_id].append(now)
        count = len(self._retrieval_history[session_id])

        if count >= self.revisit_threshold:
            await signal_revisit(session_id, self.ctx)
        else:
            await signal_use(session_id, self.ctx)

    async def on_response(self, text: str, injected_ids: list) -> None:
        """Detect implicit USE signals from LLM response text.

        Called after the LLM reply is collected by the Observer pipeline.
        If the response text contains a session_id that was previously injected
        into the system prompt, we emit a USE signal for that session.

        Remaining injected sessions that are not mentioned do NOT generate an
        IGNORE signal — response brevity is not evidence of non-use.

        Expected latency: <1ms (pure string search, no ONNX).

        Args:
            text: Full LLM response text collected by the proxy.
            injected_ids: Session IDs that were included in the last inject() call.
        """
        if not injected_ids or not text:
            return
        text_lower = text.lower()
        for sid in injected_ids:
            if sid.lower() in text_lower:
                await signal_use(sid, self.ctx)

    def reset_session(self) -> None:
        """Reset per-working-session state (call at start of each new agent turn)."""
        self._retrieval_history.clear()
        self._last_semantic_ts = None
        self._last_semantic_ids = []
