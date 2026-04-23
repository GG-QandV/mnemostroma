# SPDX-License-Identifier: FSL-1.1-MIT
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core import SystemContext
from ..tools.read import ctx_semantic

@dataclass
class MemoryBlock:
    """Represents the memory context injected into the LLM prompt."""
    context: str
    tools: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

PROTOCOL_BLOCK = (
    "<agent_protocol>\n"
    "MANDATORY — past work / decisions referenced: "
    "ctx_semantic(q) · ctx_anchors(type) · ctx_search(tags)\n"
    "MANDATORY — session end with decision or open task: ctx_bridge()\n"
    "FORBIDDEN: claim no context without ctx_semantic() first.\n"
    "You do not write memory. You only read. Reading is not optional.\n"
    "</agent_protocol>"
)


class ConductorProxy:
    """Middleware proxy that guarantees continuous memory context injection.
    
    Generates a structured XML memory block containing static cached elements 
    (principles, decisions, active variables) and dynamic semantic search results.
    """
    def __init__(self, ctx: SystemContext):
        self.ctx = ctx
        self._static_cache: str = ""
        self._cache_updated_at: float = 0
        self._cache_valid_for_ms: float = 5000  # 5 seconds minimal cache
        self._last_message_count: int = 0
        
    def _build_static_cache(self) -> str:
        """Build the static part of the XML context."""
        decisions = []
        principles = []
        conflicts = []
        
        # Scan RAM index for relevant flags
        sessions = list(self.ctx.ram_index.values())
        # Sort by creation time descending (newest first)
        sessions.sort(key=lambda x: x.created_at, reverse=True)
        
        for sb in sessions:
            if sb.conflict_flag:
                conflicts.append(f"- {sb.brief}")
            
            if sb.importance == "principle":
                principles.append(f"- {sb.brief}")
            elif sb.importance in ("critical", "important"):
                decisions.append(f"- {sb.brief}")
                
        # Limit quantities 
        decisions = decisions[:7]
        
        # Deadlines
        deadlines = []
        for uid, urgency_obj in self.ctx.urgency_index.items():
            if urgency_obj.get("expired"): continue
            
            title = urgency_obj.get("title", uid)
            dts = urgency_obj.get("deadline_ts")
            if dts:
                dt_str = datetime.fromtimestamp(dts).isoformat()
                deadlines.append(f"- {title} (Due: {dt_str})")
            else:
                deadlines.append(f"- {title}")
                
        # XML Assembly
        xml = [PROTOCOL_BLOCK]
        if decisions:
            xml.append("<decisions>\n" + "\n".join(decisions) + "\n</decisions>")
        if principles:
            xml.append("<principles>\n" + "\n".join(principles) + "\n</principles>")
        if conflicts:
            xml.append("<conflicts>\n" + "\n".join(conflicts) + "\n</conflicts>")
        if deadlines:
            xml.append("<deadlines>\n" + "\n".join(deadlines) + "\n</deadlines>")
            
        # Last session
        if sessions:
            last_session = sessions[0].brief
            xml.append("<last_session>\n" + last_session + "\n</last_session>")
        
        return "\n\n".join(xml)

    async def inject(self, user_message: str, max_tokens: int = 600, include_tools: bool = True) -> MemoryBlock:
        """Generate the memory block for the LLM prompt.
        
        Args:
            user_message: The latest prompt from the user to base semantic search on.
            max_tokens: Limit output size (approximate constraints).
            include_tools: Whether to return the memory MCP tools definitions.
        """
        start_time = time.time()
        
        pure_mode = self.ctx.config.integration.pure_context
        include_tools = include_tools and not pure_mode
        
        # 1. Update static cache if necessary
        # We rebuild if more than N seconds have passed since last interaction 
        # (simulating the `cache_static_every_n_messages` concept).
        if time.time() - self._cache_updated_at > 5.0 or not self._static_cache:
            self._static_cache = self._build_static_cache()
            self._cache_updated_at = time.time()
            cached = False
        else:
            cached = True
            
        # 2. Dynamic Semantic Search
        relevant_xml = ""
        # We ask for a small list to not flood the context
        relevant_sessions = await ctx_semantic(user_message, self.ctx, k=10, top_n=3)
        if relevant_sessions:
            # GAP 2: record which session IDs were injected for implicit feedback analysis
            self.ctx._last_injected_ids = [sb.session_id for sb in relevant_sessions]
            lines = [f"- {sb.session_id}: {sb.brief}" for sb in relevant_sessions]
            relevant_xml = "<relevant>\n" + "\n".join(lines) + "\n</relevant>"
        else:
            self.ctx._last_injected_ids = []
            
        # 2b. Intuition Signals from Experience Layer
        intuition_xml = ""
        if getattr(self.ctx, 'experience_index', None) and self.ctx.config.experience.layer_enabled:
            active_tags = []
            for sb in list(self.ctx.ram_index.values())[-10:]:
                active_tags.extend(sb.tags)
            active_tags = list(dict.fromkeys(active_tags))[:15]  # dedup, cap
            signals = self.ctx.experience_index.intuition_signals(active_tags)
            if signals:
                lines = [f'  <signal type="{s["type"]}">{s["message"]}</signal>' for s in signals]
                intuition_xml = "<intuition>\n" + "\n".join(lines) + "\n</intuition>"
                # Log each fired signal for watch/dashboard observability
                for s in signals:
                    cluster = self.ctx.experience_index.get(s["tag"])

        # 3. Assemble Full XML
        from datetime import timezone
        now_str = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if not self._static_cache and not relevant_xml:
            context_string = f'<memory_context updated="{now_str}">\n<status>First session. Memory is empty — learning from this conversation.</status>\n</memory_context>'
        else:
            context_string = f'<memory_context updated="{now_str}">\n'
            context_string += self._static_cache + "\n\n"
            if relevant_xml:
                context_string += relevant_xml + "\n"
            if intuition_xml:
                context_string += intuition_xml + "\n"
            context_string += '</memory_context>'
            
        # 4. Tools payload
        tools = self._get_tool_definitions() if (include_tools and self.ctx.config.tools.enabled) else []
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Log Injection (v1.0 spec — Point #14)
        sections = ["decisions", "principles", "conflicts", "deadlines"]
        if relevant_xml: sections.append("relevant")
        

        return MemoryBlock(
            context=context_string,
            tools=tools,
            stats={
                "cached": cached,
                "semantic_ms": round(latency_ms, 2),
                "tokens": len(context_string) // 4  # heuristic approximation
            }
        )
        
    def _get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return the MCP JSON tool schemas supported by Mnemostroma Context Manager."""
        return [
            {
                "name": "ctx_semantic",
                "description": "Search memory by meaning. Use when memory_context doesn't have enough detail on a topic. Returns relevant past sessions.",
                "parameters": {
                    "query": {"type": "string", "description": "Topic to remember"},
                    "top_n": {"type": "integer", "default": 5}
                }
            },
            {
                "name": "ctx_anchors",
                "description": "Find exact facts: phone numbers, URLs, decisions, dates. Use when you need a precise value.",
                "parameters": {
                    "type": {"type": "string", "enum": ["decision","phone","address","person","number","date","link"]},
                    "query": {"type": "string"}
                }
            },
            {
                "name": "ctx_precision",
                "description": "Find verbatim artifacts: links, formulas, quotes, code snippets stored exactly as recorded.",
                "parameters": {
                    "type": {"type": "string", "enum": ["link","concept","quote","formula","data"]},
                    "query": {"type": "string"}
                }
            },
            {
                "name": "ctx_full",
                "description": "Get complete session transcript. Use only when you need exact wording — this is expensive.",
                "parameters": {
                    "session_id": {"type": "string"}
                }
            },
            {
                "name": "ctx_principles",
                "description": "List all permanent rules. These must NEVER be violated.",
                "parameters": {}
            },
            {
                "name": "ctx_urgent",
                "description": "List active deadlines and urgent items.",
                "parameters": {}
            },
            {
                "name": "content_search",
                "description": "Search past code, chapters, configs with version history.",
                "parameters": {
                    "query": {"type": "string"},
                    "content_type": {"type": "string", "enum": ["function","class","chapter","scene","config"]}
                }
            },
            {
                "name": "ctx_get",
                "description": "Get details of a specific session by ID. Use when memory_context references a session you need more info about.",
                "parameters": {
                    "session_id": {"type": "string"}
                }
            },
            {
                "name": "ctx_search",
                "description": "Search memory by tags. Faster than semantic but requires exact tag match.",
                "parameters": {
                    "tags": {"type": "array", "items": {"type": "string"}}
                }
            }
        ]
