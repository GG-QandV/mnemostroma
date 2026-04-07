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
    onnx_inter_threads: int = 2
    onnx_intra_threads: int = 2

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
class AnchorDecayConfig:
    enabled: bool = True
    interval_min: int = 60          # how often the decay worker runs
    threshold_days: int = 30        # days of inactivity before decay triggers
    rate: float = 0.1               # reserved for future importance reduction

@dataclass(frozen=True)
class DreamerConfig:
    enabled: bool = True
    idle_threshold_min: int = 5     # minutes of silence before dreamer activates
    max_anchors_per_cycle: int = 20 # anchors reassessed per idle run

@dataclass(frozen=True)
class SearchConfig:
    top_k_candidates: int
    top_n_results: int
    embedding_dim: int
    matrix_dtype: str = "float32"
    pipeline_width: int = 2

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
    # Maturity thresholds (sessions count per level)
    maturity_apprentice: int = 5
    maturity_practitioner: int = 10
    maturity_expert: int = 30
    maturity_master: int = 100
    # Decay Engine
    exp_decay_days_threshold: int = 90
    exp_decay_rate: float = 0.01  # score_sum reduction per inactive day

@dataclass(frozen=True)
class ModelDefinition:
    path: str
    query_prefix: Optional[str] = None
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
class CalibrationConfig:
    enabled: bool
    max_sessions: int
    source: Optional[str]
    save_history: bool
    min_onboarding_sessions: int = 10
    continuation_threshold: float = 0.82  # updated by CalibrationCollector
    calibration_complete: bool = False

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
class LoggingConfig:
    enabled: bool = True
    mode: str = "safe"      # "safe" | "debug"

@dataclass(frozen=True)
class Config:
    resources: ResourcesConfig
    score: ScoreConfig
    importance: ImportanceConfig
    temporal: TemporalConfig
    dissolver: DissolverConfig
    search: SearchConfig
    observer: ObserverConfig
    tuner: TunerConfig
    urgency: UrgencyConfig
    storage: StorageConfig
    experience: ExperienceConfig
    calibration: CalibrationConfig
    security: SecurityConfig
    cloud_sync: CloudSyncConfig
    feedback: FeedbackConfig
    anchor_decay: AnchorDecayConfig = field(default_factory=AnchorDecayConfig)
    dreamer: DreamerConfig = field(default_factory=DreamerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    manifest: Optional[ModelManifest] = None

    @classmethod
    def _from_dict_filtered(cls, section_class, data):
        """Build dataclass instance from dict, ignoring extra keys."""
        if not data: return section_class()
        # use annotations to identify valid fields
        ann = getattr(section_class, '__annotations__', {})
        return section_class(**{k: v for k, v in data.items() if k in ann})

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
            resources=cls._from_dict_filtered(ResourcesConfig, data.get('resources', {})),
            score=cls._from_dict_filtered(ScoreConfig, data.get('score', {})),
            importance=cls._from_dict_filtered(ImportanceConfig, data.get('importance', {})),
            temporal=cls._from_dict_filtered(TemporalConfig, data.get('temporal', {})),
            dissolver=cls._from_dict_filtered(DissolverConfig, data.get('dissolver', {})),
            search=cls._from_dict_filtered(SearchConfig, data.get('search', {})),
            observer=cls._from_dict_filtered(ObserverConfig, data.get('observer', {})),
            tuner=cls._from_dict_filtered(TunerConfig, data.get('tuner', {})),
            urgency=cls._from_dict_filtered(UrgencyConfig, data.get('urgency', {})),
            storage=cls._from_dict_filtered(StorageConfig, data.get('storage', {})),
            experience=cls._from_dict_filtered(ExperienceConfig, data.get('experience', {})),
            calibration=cls._from_dict_filtered(CalibrationConfig, data.get('calibration', {})),
            security=cls._from_dict_filtered(SecurityConfig, data.get('security', {})),
            cloud_sync=cls._from_dict_filtered(CloudSyncConfig, data.get('cloud_sync', {})),
            feedback=cls._from_dict_filtered(FeedbackConfig, data.get('feedback', {})),
            anchor_decay=cls._from_dict_filtered(AnchorDecayConfig, data.get('anchor_decay')),
            dreamer=cls._from_dict_filtered(DreamerConfig, data.get('dreamer')),
            logging=cls._from_dict_filtered(LoggingConfig, data.get('logging')),
            manifest=ModelManifest.load(Path(path).parent / "models_manifest.json") if (Path(path).parent / "models_manifest.json").exists() else None
        )
