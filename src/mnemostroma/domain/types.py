# SPDX-License-Identifier: FSL-1.1-MIT
"""Core domain types for Mnemostroma.

Result pattern defines explicit error handling boundaries for ports and adapters.
Requires Python 3.12+ for modern 'type' aliases.
"""

# Result Type Aliases (Python 3.12+ syntax)
type Ok[T] = tuple[T, None]
type Err[E: Exception] = tuple[None, E]
type Result[T, E: Exception] = Ok[T] | Err[E]

# Helpers for creating Results
def ok[T](value: T) -> Ok[T]:
    return (value, None)

def err[E: Exception](error: E) -> Err[E]:
    return (None, error)

# Domain Errors
class StorageError(Exception):
    """Base class for all persistence-related errors."""
    pass

class NotFoundError(StorageError):
    """Raised when an requested entity is not found in storage."""
    pass

class EmbedderError(Exception):
    """Raised when the embedding engine fails."""
    pass

class ToolError(Exception):
    """Base class for errors occurring during tool execution."""
    pass
