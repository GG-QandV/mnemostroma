from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Protocol, Sequence

logger = logging.getLogger("mnemostroma.tools.anchor_replay")


# ---------------------------------------------------------------------------
# Repo adapter section — wired for real Mnemostroma repo
# ---------------------------------------------------------------------------

# Real imports from repo
import time
from mnemostroma.config import Config
from mnemostroma.core import SystemContext, ModelRegistry
from mnemostroma.conductor import Conductor
from mnemostroma.observer.pipeline import observer_pipeline
from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.subconscious.anchor_index import AnchorIndex


class SessionLike(Protocol):
    session_id: str


class AnchorLike(Protocol):
    anchor_id: str
    session_id: str
    brief: str
    anchor_type: str
    key_facts: Any
    flags: Any
    decay_level: int
    access_count: int
    last_accessed_at: int
    t_rel: Any
    created_at: int
    updated_at: int
    embedding: Any


@dataclass(slots=True)
class ReplayHooks:
    build_context: Callable[[Optional[str]], Awaitable[Any]]
    load_session_ids: Callable[[Any, Optional[Path], Optional[int]], Awaitable[List[str]]]
    load_session: Callable[[Any, str], Awaitable[Any]]
    clone_context_for_variant: Callable[[Any, Dict[str, Any]], Awaitable[Any]]
    run_observer_pipeline: Callable[[Any, Any], Awaitable[Any]]
    build_anchor_from_observer: Callable[[Any, Any, Any], Awaitable[Any]]
    persist_anchor_if_needed: Callable[[Any, Any, Any], Awaitable[None]]


# ===== Adapter implementations =====

async def build_context(config_path: Optional[str]) -> SystemContext:
    """Build SystemContext from config."""
    conductor = Conductor()
    config_file = Path(config_path) if config_path else Path.home() / ".mnemostroma" / "config.json"
    ctx = await conductor.start(config_path=config_file)
    logger.info(f"Built context from {config_file}")
    return ctx


async def load_session_ids(ctx: SystemContext, sessions_file: Optional[Path], limit: Optional[int]) -> List[str]:
    """Load session ids from file or persistence."""
    if sessions_file:
        ids = [line.strip() for line in sessions_file.read_text().splitlines() if line.strip()]
        logger.info(f"Loaded {len(ids)} session ids from {sessions_file}")
    else:
        # Load from persistence (load briefs)
        if not ctx.persistence:
            raise ValueError("No sessions_file and no persistence available")
        briefs = await ctx.persistence.get_all_session_briefs()
        ids = [b.session_id for b in briefs]
        logger.info(f"Loaded {len(ids)} session ids from persistence")

    if limit:
        ids = ids[:limit]
    return ids


async def load_session(ctx: SystemContext, session_id: str) -> Any:
    """Load session from RAM or persistence."""
    if session_id in ctx.ram_index:
        return ctx.ram_index[session_id]
    # Load from SQLite
    session = await ctx.load(session_id)
    if session:
        ctx.ram_index[session_id] = session
    return session


async def clone_context_for_variant(ctx: Any, overrides: Dict[str, Any]) -> Any:
    """Robust config override для frozen dataclasses."""
    import copy
    import json
    import tempfile
    import shutil
    from pathlib import Path
    from mnemostroma.config import Config
    
    # 1. Базовый config как dict
    # Примечание: используем to_dict() если есть, или __dict__
    if hasattr(ctx.config, "to_dict"):
        base_config = ctx.config.to_dict()
    else:
        base_config = copy.deepcopy(ctx.config.__dict__)
    
    # 2. Deep merge overrides
    def deep_merge(target: Dict, source: Dict) -> Dict:
        for key, value in source.items():
            if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                deep_merge(target[key], value)
            else:
                target[key] = value
        return target
    
    # Поддержка nested JSON и dotted notation
    for k, v in overrides.items():
        if '.' in k:  # dotted notation
            keys = k.split('.')
            ptr = base_config
            for i in range(len(keys)-1):
                ptr = ptr.setdefault(keys[i], {})
            ptr[keys[-1]] = v
        else:  # nested dict
            deep_merge(base_config, {k: v})
    
    # 3. Создаем временный файл, так как Conductor.start в v1.8.4 требует путь
    tmp_dir = Path(tempfile.mkdtemp(prefix="mnemo_replay_final_"))
    manifest_src = Path("models_manifest.json")
    if manifest_src.exists():
        shutil.copy(manifest_src, tmp_dir / "models_manifest.json")
    
    tmp_config_path = tmp_dir / "config.json"
    with open(tmp_config_path, "w", encoding="utf-8") as f:
        json.dump(base_config, f)
        
    # 4. Новый context
    db_path = getattr(ctx, "db_path", "mnemostroma.db")
    new_conductor = Conductor()
    new_ctx = await new_conductor.start(config_path=tmp_config_path, db_path=db_path)
    return new_ctx


async def run_observer_pipeline(ctx: SystemContext, session: Any) -> Any:
    """Run real observer pipeline, returns SessionBrief."""
    # Load full session content from persistence if available
    if hasattr(session, 'content_full') and session.content_full:
        text = session.content_full
    elif isinstance(session, dict) and session.get('content_full'):
        text = session['content_full']
    else:
        # Fallback to brief if full content not available
        text = getattr(session, 'brief', '') or session.get('brief', '')
        if not text:
            logger.warning(f"No content_full or brief available for session")
            return None

    session_id = session.session_id if hasattr(session, 'session_id') else str(session.get('session_id', ''))

    output = await observer_pipeline(text, session_id, ctx)
    logger.debug(f"Observer pipeline completed for session {session_id}")
    return output


async def build_anchor_from_observer(ctx: SystemContext, session: Any, observer_output: Any) -> Any:
    """Build anchor using real observer/persist_step logic."""
    session_id = session.session_id if hasattr(session, 'session_id') else str(session.get('session_id', ''))

    # Extract from observer_output (SessionBrief from observer_pipeline)
    entities = getattr(observer_output, 'entities', []) or []
    importance = getattr(session, 'importance', 'background')
    brief = getattr(observer_output, 'brief', '')
    tags = getattr(observer_output, 'tags', []) or []
    created_at = int(time.time())

    # Infer anchor_type and build key_facts (as in persist_step.py)
    anchor_type = AnchorIndex.infer_anchor_type(importance, entities)
    key_facts = AnchorIndex.build_key_facts(entities, max_facts=5)

    # Simplified flags (subset of observer flag detection)
    flags = {
        "is_new_entity": True,
        "continuation_of": None,
        "continuation_depth": 0,
        "mention_type": "focus",
        "outcome": "pending",
        "user_pin": False,
        "multi_session": False,
    }

    # Temporal relations (empty for replay)
    t_rel = {"after": [], "before": [], "caused_by": [], "during": []}

    # Create Anchor (no embedding for replay baseline)
    anchor = Anchor(
        anchor_id=session_id,
        session_id=session_id,
        brief=brief,
        anchor_type=anchor_type,
        key_facts=key_facts,
        flags=flags,
        t_rel=t_rel,
        decay_level=0,
        access_count=0,
        last_accessed_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        embedding=None,
    )

    logger.debug(f"Built anchor {anchor.anchor_id} (type={anchor.anchor_type})")
    return anchor


async def persist_anchor_if_needed(ctx: SystemContext, session: Any, anchor: Any) -> None:
    """Persist anchor via AnchorIndex and persistence layer."""
    # Put into index (may evict older one)
    evicted = ctx.anchor_index.put(anchor)

    # If evicted, persist it
    if evicted and ctx.persistence:
        await ctx.persistence.save_anchor(evicted)
        logger.debug(f"Persisted evicted anchor {evicted.anchor_id}")

    # Also persist the new anchor
    if ctx.persistence:
        await ctx.persistence.save_anchor(anchor)


DEFAULT_HOOKS = ReplayHooks(
    build_context=build_context,
    load_session_ids=load_session_ids,
    load_session=load_session,
    clone_context_for_variant=clone_context_for_variant,
    run_observer_pipeline=run_observer_pipeline,
    build_anchor_from_observer=build_anchor_from_observer,
    persist_anchor_if_needed=persist_anchor_if_needed,
)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReplayVariant:
    name: str
    overrides: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReplayConfig:
    output_dir: Path
    config_path: Optional[str] = None
    sessions_file: Optional[Path] = None
    limit: Optional[int] = None
    variants: List[ReplayVariant] = field(default_factory=list)


@dataclass(slots=True)
class AnchorSnapshot:
    variant: str
    session_id: str
    anchor_id: str
    anchor_type: str
    brief: str
    decay_level: int
    access_count: int
    last_accessed_at: int
    created_at: int
    updated_at: int
    key_facts_count: int
    t_rel_count: int
    flags_json: str
    key_facts_json: str
    t_rel_json: str
    embedding_present: bool


@dataclass(slots=True)
class SessionDiff:
    session_id: str
    baseline_anchor_type: str
    variant_anchor_type: str
    changed_type: bool
    baseline_key_facts_count: int
    variant_key_facts_count: int
    key_facts_delta: int
    baseline_t_rel_count: int
    variant_t_rel_count: int
    t_rel_delta: int
    baseline_decay_level: int
    variant_decay_level: int
    decay_delta: int
    baseline_flags_json: str
    variant_flags_json: str
    flags_changed: bool
    baseline_brief: str
    variant_brief: str
    brief_changed: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stable_json(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))



def _to_plain(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(v) for v in value]
    return value



def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)



def _count_t_rel(value: Any) -> int:
    plain = _to_plain(value) or {}
    if not isinstance(plain, dict):
        return 0
    total = 0
    for rel_values in plain.values():
        if isinstance(rel_values, (list, tuple, set)):
            total += len(rel_values)
    return total



def _count_key_facts(value: Any) -> int:
    plain = _to_plain(value) or []
    if isinstance(plain, list):
        return len(plain)
    return 0



def _snapshot_anchor(variant: str, anchor: Any) -> AnchorSnapshot:
    flags = _to_plain(_safe_get(anchor, "flags", {})) or {}
    key_facts = _to_plain(_safe_get(anchor, "key_facts", [])) or []
    t_rel = _to_plain(_safe_get(anchor, "t_rel", {})) or {}
    embedding = _safe_get(anchor, "embedding")
    return AnchorSnapshot(
        variant=variant,
        session_id=str(_safe_get(anchor, "session_id", "")),
        anchor_id=str(_safe_get(anchor, "anchor_id", _safe_get(anchor, "session_id", ""))),
        anchor_type=str(_safe_get(anchor, "anchor_type", "")),
        brief=str(_safe_get(anchor, "brief", "")),
        decay_level=int(_safe_get(anchor, "decay_level", 0) or 0),
        access_count=int(_safe_get(anchor, "access_count", 0) or 0),
        last_accessed_at=int(_safe_get(anchor, "last_accessed_at", 0) or 0),
        created_at=int(_safe_get(anchor, "created_at", 0) or 0),
        updated_at=int(_safe_get(anchor, "updated_at", 0) or 0),
        key_facts_count=_count_key_facts(key_facts),
        t_rel_count=_count_t_rel(t_rel),
        flags_json=_stable_json(flags),
        key_facts_json=_stable_json(key_facts),
        t_rel_json=_stable_json(t_rel),
        embedding_present=embedding is not None,
    )



def _write_csv(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    
    # Для dataclass
    if is_dataclass(rows[0]):
        fieldnames = [f for f in asdict(rows[0]).keys()]
        serializable_rows = [asdict(row) for row in rows]
    else:
        fieldnames = list(rows[0].keys())
        serializable_rows = list(rows)
    
    # Escape JSON fields for CSV
    json_fields = {'flags_json', 'key_facts_json', 't_rel_json'}
    for row in serializable_rows:
        for field in json_fields & set(row):
            row[field] = '"' + row[field].replace('"', '""') + '"'
    
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(serializable_rows)



def _summarize_variant(rows: Sequence[AnchorSnapshot]) -> Dict[str, Any]:
    type_counts: Dict[str, int] = {}
    for row in rows:
        type_counts[row.anchor_type] = type_counts.get(row.anchor_type, 0) + 1
    return {
        "anchors_total": len(rows),
        "sessions_total": len({row.session_id for row in rows}),
        "type_counts": dict(sorted(type_counts.items())),
        "embedding_present": sum(1 for row in rows if row.embedding_present),
    }



def _build_session_diffs(
    baseline_rows: Sequence[AnchorSnapshot],
    variant_rows: Sequence[AnchorSnapshot],
) -> List[SessionDiff]:
    baseline_map = {row.session_id: row for row in baseline_rows}
    variant_map = {row.session_id: row for row in variant_rows}
    session_ids = sorted(set(baseline_map) | set(variant_map))
    diffs: List[SessionDiff] = []
    for session_id in session_ids:
        base = baseline_map.get(session_id)
        var = variant_map.get(session_id)
        if base is None or var is None:
            continue
        diffs.append(
            SessionDiff(
                session_id=session_id,
                baseline_anchor_type=base.anchor_type,
                variant_anchor_type=var.anchor_type,
                changed_type=base.anchor_type != var.anchor_type,
                baseline_key_facts_count=base.key_facts_count,
                variant_key_facts_count=var.key_facts_count,
                key_facts_delta=var.key_facts_count - base.key_facts_count,
                baseline_t_rel_count=base.t_rel_count,
                variant_t_rel_count=var.t_rel_count,
                t_rel_delta=var.t_rel_count - base.t_rel_count,
                baseline_decay_level=base.decay_level,
                variant_decay_level=var.decay_level,
                decay_delta=var.decay_level - base.decay_level,
                baseline_flags_json=base.flags_json,
                variant_flags_json=var.flags_json,
                flags_changed=base.flags_json != var.flags_json,
                baseline_brief=base.brief,
                variant_brief=var.brief,
                brief_changed=base.brief != var.brief,
            )
        )
    return diffs


# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------


async def run_variant(
    hooks: ReplayHooks,
    base_context: Any,
    session_ids: Sequence[str],
    variant: ReplayVariant,
) -> List[AnchorSnapshot]:
    logger.info("Running variant '%s' on %d sessions", variant.name, len(session_ids))
    if variant.name == "baseline":
        ctx = base_context
    else:
        ctx = await hooks.clone_context_for_variant(base_context, deepcopy(variant.overrides))

    snapshots: List[AnchorSnapshot] = []
    for session_id in session_ids:
        session = await hooks.load_session(ctx, session_id)
        observer_output = await hooks.run_observer_pipeline(ctx, session)
        anchor = await hooks.build_anchor_from_observer(ctx, session, observer_output)
        await hooks.persist_anchor_if_needed(ctx, session, anchor)
        snapshots.append(_snapshot_anchor(variant.name, anchor))
    return snapshots


async def run_replay(config: ReplayConfig, hooks: ReplayHooks = DEFAULT_HOOKS) -> Dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    base_context = await hooks.build_context(config.config_path)
    session_ids = await hooks.load_session_ids(base_context, config.sessions_file, config.limit)
    if not session_ids:
        raise ValueError("No session ids provided or loaded for replay")

    variant_rows: Dict[str, List[AnchorSnapshot]] = {}
    for variant in config.variants:
        rows = await run_variant(hooks, base_context, session_ids, variant)
        variant_rows[variant.name] = rows
        _write_csv(config.output_dir / f"anchors_{variant.name}.csv", rows)

    baseline_name = config.variants[0].name
    baseline_rows = variant_rows[baseline_name]
    summary: Dict[str, Any] = {
        "baseline": _summarize_variant(baseline_rows),
        "variants": {},
    }

    for variant in config.variants[1:]:
        rows = variant_rows[variant.name]
        diffs = _build_session_diffs(baseline_rows, rows)
        _write_csv(config.output_dir / f"diff_{baseline_name}_vs_{variant.name}.csv", diffs)
        changed_type = sum(1 for diff in diffs if diff.changed_type)
        flags_changed = sum(1 for diff in diffs if diff.flags_changed)
        summary["variants"][variant.name] = {
            "summary": _summarize_variant(rows),
            "sessions_compared": len(diffs),
            "changed_type": changed_type,
            "flags_changed": flags_changed,
        }

    summary_path = config.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------



def _parse_variant(raw: str) -> ReplayVariant:
    if "=" not in raw:
        return ReplayVariant(name=raw, overrides={})
    name, payload = raw.split("=", 1)
    return ReplayVariant(name=name.strip(), overrides=json.loads(payload))



def parse_args() -> ReplayConfig:
    parser = argparse.ArgumentParser(description="Replay session corpus through anchor logic and diff variants.")
    parser.add_argument("--config-path", dest="config_path", default=None, help="Optional repo config path")
    parser.add_argument("--sessions-file", dest="sessions_file", default=None, help="Text file with session ids, one per line")
    parser.add_argument("--limit", dest="limit", type=int, default=None, help="Limit number of sessions")
    parser.add_argument("--output-dir", dest="output_dir", required=True, help="Directory for CSV/JSON artifacts")
    parser.add_argument(
        "--variant",
        dest="variants",
        action="append",
        default=[],
        help=(
            "Variant definition. First one should be baseline. "
            "Format: baseline or candidate={\"tuner\":{\"decision_threshold\":0.65}}"
        ),
    )
    args = parser.parse_args()

    variants = [_parse_variant(raw) for raw in args.variants] or [ReplayVariant(name="baseline")]
    if variants[0].name != "baseline":
        variants = [ReplayVariant(name="baseline")] + variants

    return ReplayConfig(
        output_dir=Path(args.output_dir),
        config_path=args.config_path,
        sessions_file=Path(args.sessions_file) if args.sessions_file else None,
        limit=args.limit,
        variants=variants,
    )


async def amain() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    config = parse_args()
    summary = await run_replay(config)
    logger.info("Replay finished: %s", _stable_json(summary))
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
