# src/mnemostroma/observer/steps/base.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from mnemostroma.core import SystemContext
    from mnemostroma.memory.session_index import SessionBrief
    from mnemostroma.subconscious.anchor import Anchor


@dataclass
class IOEvent:
    """Input event for the observer pipeline."""
    text: str
    session_id: str
    intent_vector: Optional[np.ndarray] = None


@dataclass
class PipelineContext:
    """Carries state through the Observer StepChain."""
    event: IOEvent
    ctx: "SystemContext"  # Added to ensure steps have access to models/config
    
    importance: Optional[str] = None
    entities: List[Dict[str, Any]] = field(default_factory=list)
    embedding: Optional[bytes] = None  # Stored as bytes for persistence compatibility
    score: Optional[float] = None
    
    should_abort: bool = False  # Flow control: True stops the pipeline
    
    # Internal shared state for legacy compatibility during extraction
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    
    # Output objects
    sb: Optional["SessionBrief"] = None
    anchor: Optional["Anchor"] = None


class Step(Protocol):
    """Protocol for a single pipeline step."""
    async def run(self, pctx: PipelineContext) -> PipelineContext:
        """Execute the step logic and update context."""
        ...
