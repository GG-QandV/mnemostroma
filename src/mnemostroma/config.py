# SPDX-License-Identifier: FSL-1.1-MIT
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Dict

@dataclass(frozen=True)
class ResourcesConfig:
    session_window_size: int
    content_max_blocks: int
    ram_soft_limit_mb: int
    ram_hard_limit_mb: int
    ram_eviction_threshold: float
    window_min: int
    sqlite_cache_mb: int
    sqlite_mmap_mb: int
    db_growth_budget_mb_per_day: float

@dataclass(frozen=True)
class ScoreConfig:
    weight_relevance: float
    weight_temporal: float
    weight_importance: float
    temporal_decay_lambda: float
    weight_relevance_search: float
    weight_temporal_search: float
    weight_importance_search: float

@dataclass(frozen=True)
class ImportanceConfig:
    weight_critical: float
    weight_important: float
    weight_background: float
    weight_principle: float
    ner_score_threshold: float
    tag_verification_threshold: float
    anchor_ttl_importance_multiplier_critical: float
    anchor_ttl_importance_multiplier_important: float
    anchor_ttl_importance_multiplier_background: float

@dataclass(frozen=True)
class TemporalConfig:
    age_threshold_fresh_days: int
    age_threshold_actual_days: int
    age_threshold_stale_days: int
    age_threshold_archive_days: int

@dataclass(frozen=True)
class DissolverConfig:
    lambda_critical: float
    lambda_important: float
    lambda_background: float
    lambda_principle: float
    use_factor_coefficient: float
    prog_factor_max_successors: int
    prog_factor_weight: float
    resolution_floor_milestone: float
    resolution_floor_principle: float
    consolidation_interval_sec: int
    content_max_blocks: int
    content_evict_batch: int
    content_hot_protect_hours: int
    content_active_protect: bool

@dataclass(frozen=True)
class HNSWConfig:
    session_M: int
    session_ef_construction: int
    session_ef: int
    session_max_elements: int
    content_M: int
    content_ef_construction: int
    content_ef: int
    content_max_elements: int
    top_k_candidates: int
    embedding_dim: int

@dataclass(frozen=True)
class ObserverConfig:
    min_text_length: int
    ner_call_rate_target: float
    brief_max_chars: int
    active_variables_max: int
    tags_max_per_session: int
    tags_min_for_search: int
    urgency_score_modifier_expired: float
    urgency_score_modifier_principle: float
    session_type_classify_after_n: int
    gliner_mode: str
    gliner_auto_switch_precision_threshold: float
    gliner_auto_switch_after_sessions: int

@dataclass(frozen=True)
class TunerConfig:
    conflict_signal_threshold: float
    semantic_drift_threshold: float
    anchor_ttl_days_default: int
    anchor_ttl_days_decision: int
    anchor_ttl_days_principle: int
    recalibration_drift_threshold: float
    check_interval_sec: int
    conflict_hold_max_days: int

@dataclass(frozen=True)
class UrgencyConfig:
    check_interval_sec: int
    expired_score_penalty: float
    principle_score_boost: float
    default_hours_ahead: int
    bare_entity_compress_delay_sec: int

@dataclass(frozen=True)
class StorageConfig:
    sqlite_synchronous: str
    sqlite_auto_vacuum: str
    sqlite_compress_threshold_mb: int
    sqlite_archive_cutoff_years: int
    async_flush_interval_sec: int
    batch_flush_size: int

@dataclass(frozen=True)
class ExperienceConfig:
    layer_enabled: bool
    process_vec_enabled: bool
    process_vec_step_flush_every_n: int
    negative_exp_lambda: float
    negative_exp_resolution_floor: float
    cluster_min_samples: int
    intuition_fire_threshold: float

@dataclass(frozen=True)
class ModelDefinition:
    path: str
    tokenizer_path: Optional[str] = None
    dim: Optional[int] = None
    max_length: Optional[int] = None
    pooling: Optional[str] = None

@dataclass(frozen=True)
class ModelManifest:
    active_models: Dict[str, ModelDefinition]

    @classmethod
    def load(cls, path: str | Path) -> 'ModelManifest':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        models = {}
        for name, m_data in data['active_models'].items():
            models[name] = ModelDefinition(**m_data)
        return cls(active_models=models)

@dataclass(frozen=True)
class ModelsConfig:
    embedding_session: str
    embedding_content: str
    ner: str
    reranker: str
    bge_m3_lazy_load: bool

@dataclass(frozen=True)
class CalibrationConfig:
    enabled: bool
    max_sessions: int
    source: Optional[str]
    save_history: bool

@dataclass(frozen=True)
class SecurityConfig:
    verify_models_on_bootstrap: bool
    manifest_path: str
    principle_confirmation_required: bool
    max_principles_per_session: int
    sanitize_input: bool

@dataclass(frozen=True)
class CloudSyncConfig:
    enabled: bool
    endpoint: Optional[str]
    layers: List[str]
    interval_sec: int
    encrypted: bool
    device_id: Optional[str]

@dataclass(frozen=True)
class FeedbackConfig:
    weights: Dict[str, float]
    ema_alpha: float
    ignore_window_sec: float
    revisit_threshold: int

@dataclass(frozen=True)
class Config:
    resources: ResourcesConfig
    score: ScoreConfig
    importance: ImportanceConfig
    temporal: TemporalConfig
    dissolver: DissolverConfig
    hnsw: HNSWConfig
    observer: ObserverConfig
    tuner: TunerConfig
    urgency: UrgencyConfig
    storage: StorageConfig
    experience: ExperienceConfig
    models: ModelsConfig
    calibration: CalibrationConfig
    security: SecurityConfig
    cloud_sync: CloudSyncConfig
    feedback: FeedbackConfig
    manifest: Optional[ModelManifest] = None

    @classmethod
    def load(cls, path: str | Path) -> 'Config':
        """Load configuration from JSON file.
        
        Args:
            path: Path to config.json file.
            
        Returns:
            Config instance populated with data.
        """
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return cls(
            resources=ResourcesConfig(**data['resources']),
            score=ScoreConfig(**data['score']),
            importance=ImportanceConfig(**data['importance']),
            temporal=TemporalConfig(**data['temporal']),
            dissolver=DissolverConfig(**data['dissolver']),
            hnsw=HNSWConfig(**data['hnsw']),
            observer=ObserverConfig(**data['observer']),
            tuner=TunerConfig(**data['tuner']),
            urgency=UrgencyConfig(**data['urgency']),
            storage=StorageConfig(**data['storage']),
            experience=ExperienceConfig(**data['experience']),
            models=ModelsConfig(**data['models']),
            calibration=CalibrationConfig(**data['calibration']),
            security=SecurityConfig(**data['security']),
            cloud_sync=CloudSyncConfig(**data['cloud_sync']),
            feedback=FeedbackConfig(**data['feedback']),
            manifest=ModelManifest.load(Path(path).parent / "models_manifest.json") if (Path(path).parent / "models_manifest.json").exists() else None
        )
