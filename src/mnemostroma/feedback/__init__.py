# SPDX-License-Identifier: FSL-1.1-MIT
"""Implicit Feedback Loop v1.5 — signal emission and EMA scoring."""
from .implicit import (
    ImplicitFeedbackTracker,
    record_signal,
    signal_deep_use,
    signal_ignore,
    signal_revisit,
    signal_use,
)

__all__ = [
    "record_signal",
    "signal_use",
    "signal_deep_use",
    "signal_ignore",
    "signal_revisit",
    "ImplicitFeedbackTracker",
]
