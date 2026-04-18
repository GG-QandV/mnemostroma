"""Memory protocol block — injected into agent config files."""

PROTOCOL_MARKER = "# [mnemostroma-protocol]"

PROTOCOL_BLOCK = f"""{PROTOCOL_MARKER}
## Memory Protocol (Mnemostroma)

Tools available via MCP. Agent decides usage. Continuity via injected <memorycontext>.
Agent may call ctx.semantic if needed — or reason from context alone.
{PROTOCOL_MARKER}-end
"""


def get_block() -> str:
    """Return the full protocol block ready for injection."""
    return PROTOCOL_BLOCK
