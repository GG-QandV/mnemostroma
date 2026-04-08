"""Memory protocol block — injected into agent config files."""

PROTOCOL_MARKER = "# [mnemostroma-protocol]"

PROTOCOL_BLOCK = f"""{PROTOCOL_MARKER}
## Memory Protocol (Mnemostroma)

You have persistent memory tools. This is not optional guidance —
this is how you operate.

REQUIRED at session start (before your first response):
  → call ctx_active()

REQUIRED when user references past work, decisions, or prior context:
  → call ctx_semantic(query) or ctx_search(tags)

REQUIRED before session ends (if any decisions made or work continues):
  → call ctx_bridge()

Rules:
- Never say "I don't have context from previous sessions"
  without first calling ctx_active()
- Not using memory tools when they are available is an error
- The user expects continuity across sessions
{PROTOCOL_MARKER}-end
"""


def get_block() -> str:
    """Return the full protocol block ready for injection."""
    return PROTOCOL_BLOCK
