# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma: Autonomous memory layer for AI agents."""
from .version import __version__

# Lazy exports
def get_conductor():
    from .conductor import Conductor
    return Conductor()
