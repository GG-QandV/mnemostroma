# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma: Autonomous memory layer for AI agents."""
from .conductor import Conductor
from .core import SystemContext

__version__ = "0.1.0"

# Global conductor instance for ease of use
conductor = Conductor()
# ctx and content are typically accessed via conductor.ctx after start()
