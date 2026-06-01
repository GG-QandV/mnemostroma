# SPDX-License-Identifier: FSL-1.1-MIT
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    session_type_classify_after_n: int = 3
    gliner_mode: str = "open"
    gliner_auto_switch_precision_threshold: float = 0.85
    gliner_auto_switch_after_sessions: int = 10
    # B.3 — embedding-based mention_type classification
    mention_type_enabled: bool = True
    mention_type_threshold: float = 0.7

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
    session_repo: str = "legacy"  # "legacy" | "shadow" | "new"
    backup_interval_hours: int = 3

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
    query_prefix: str | None = None
    tokenizer_path: str | None = None
    dim: int | None = None
    max_length: int | None = None
    pooling: str | None = None

@dataclass(frozen=True)
class ModelManifest:
    active_models: dict[str, ModelDefinition]

    @classmethod
    def load(cls, path: str | Path) -> 'ModelManifest':
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        
        models = {}
        for name, m_data in data['active_models'].items():
            models[name] = ModelDefinition(**m_data)
        return cls(active_models=models)


@dataclass(frozen=True)
class CalibrationConfig:
    enabled: bool
    max_sessions: int
    source: str | None
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
    endpoint: str | None
    layers: list[str]
    interval_sec: int
    encrypted: bool
    device_id: str | None

@dataclass(frozen=True)
class FeedbackConfig:
    weights: dict[str, float]
    ema_alpha: float
    ignore_window_sec: float
    revisit_threshold: int
    # S-1: Auto-recalibration of score weights via Pearson correlation
    recalibration_enabled: bool = True
    recalibration_threshold: float = 0.4   # pearson_r must exceed this to trigger
    recalibrate_every_hours: float = 24.0  # how often ConsolidationWorker calls recalibrator

@dataclass(frozen=True)
class LoggingConfig:
    enabled: bool = True
    mode: str = "safe"      # "safe" | "debug"
    db_path: str = "logs.db"

@dataclass(frozen=True)
class TemporalRetrievalConfig:
    ctx_recent_enabled: bool = True
    time_weighted_search: bool = False
    half_life_days: float = 30.0
    time_weight_exempt_importance: list[str] = field(default_factory=lambda: ["critical", "principle"])

@dataclass(frozen=True)
class AnchorGuardianConfig:
    enabled: bool = True
    threshold: float = 0.72
    cooldown_sec: float = 3600.0
    guardian_types: list[str] = field(default_factory=lambda: ["principle", "constraint", "critical", "decision"])

@dataclass(frozen=True)
class AssociativeSurfacingConfig:
    enabled: bool = True
    anchor_threshold: float = 0.75
    session_threshold: float = 0.78
    max_results: int = 3

@dataclass(frozen=True)
class PrecisionGuardConfig:
    enabled: bool = True
    ram_cap: int = 1000

@dataclass(frozen=True)
class OpenLoopConfig:
    enabled: bool = True
    cooldown_sec: float = 7200.0
    threshold: float = 0.75
    max_results: int = 5

@dataclass(frozen=True)
class UrgencyPulseConfig:
    enabled: bool = True

@dataclass(frozen=True)
class SessionClosureConfig:
    enabled: bool = True
    cooldown_sec: float = 1800.0

@dataclass(frozen=True)
class IntegrationConfig:
    pure_context: bool = False

@dataclass(frozen=True)
class ToolsConfig:
    enabled: bool = True

@dataclass(frozen=True)
class ProxyConfig:
    inject_tools: bool = True

@dataclass(frozen=True)
class PromptConfig:
    tools_instruction: str = ""

@dataclass(frozen=True)
class UiConfig:
    tray_enabled: bool = True
    tray_theme: str = "dark"

@dataclass(frozen=True)
class WatchdogConfig:
    enabled: bool = True
    check_interval_sec: int = 15
    heartbeat_timeout_sec: int = 120
    startup_failsafe_sec: int = 100

@dataclass(frozen=True)
class SseConfig:
    autostart: bool = True
    port: int = 8765
    port_extension: int = 8766
    host: str = "127.0.0.1"


@dataclass(frozen=True)
class HttpConfig:
    autostart: bool = True
    port: int = 8768
    host: str = "127.0.0.1"


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
    temporal_retrieval: TemporalRetrievalConfig = field(default_factory=TemporalRetrievalConfig)
    anchor_guardian: AnchorGuardianConfig = field(default_factory=AnchorGuardianConfig)
    associative_surfacing: AssociativeSurfacingConfig = field(default_factory=AssociativeSurfacingConfig)
    precision_guard: PrecisionGuardConfig = field(default_factory=PrecisionGuardConfig)
    open_loop: OpenLoopConfig = field(default_factory=OpenLoopConfig)
    urgency_pulse: UrgencyPulseConfig = field(default_factory=UrgencyPulseConfig)
    session_closure: SessionClosureConfig = field(default_factory=SessionClosureConfig)
    integration: IntegrationConfig = field(default_factory=IntegrationConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    sse: SseConfig = field(default_factory=SseConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    manifest: ModelManifest | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        import dataclasses
        return dataclasses.asdict(self)

    @classmethod
    def load(cls, path: str | Path) -> 'Config':
        """Load configuration from JSON file.
        
        Args:
            path: Path to config.json file.
            
        Returns:
            Config instance populated with data.
        """
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        
        def filter_keys(cls, data):
            import inspect
            return {
                k: v for k, v in data.items()
                if k in inspect.signature(cls.__init__).parameters
            }

        return cls(
            resources=ResourcesConfig(**filter_keys(ResourcesConfig, data['resources'])),
            score=ScoreConfig(**filter_keys(ScoreConfig, data['score'])),
            importance=ImportanceConfig(**filter_keys(ImportanceConfig, data['importance'])),
            temporal=TemporalConfig(**filter_keys(TemporalConfig, data['temporal'])),
            dissolver=DissolverConfig(**filter_keys(DissolverConfig, data['dissolver'])),
            search=SearchConfig(**filter_keys(SearchConfig, data['search'])),
            observer=ObserverConfig(**filter_keys(ObserverConfig, data['observer'])),
            tuner=TunerConfig(**filter_keys(TunerConfig, data['tuner'])),
            urgency=UrgencyConfig(**filter_keys(UrgencyConfig, data['urgency'])),
            storage=StorageConfig(**filter_keys(StorageConfig, data['storage'])),
            experience=ExperienceConfig(**filter_keys(ExperienceConfig, data['experience'])),
            calibration=CalibrationConfig(**filter_keys(CalibrationConfig, data['calibration'])),
            security=SecurityConfig(**filter_keys(SecurityConfig, data['security'])),
            cloud_sync=CloudSyncConfig(**filter_keys(CloudSyncConfig, data['cloud_sync'])),
            feedback=FeedbackConfig(**filter_keys(FeedbackConfig, data['feedback'])),
            anchor_decay=AnchorDecayConfig(**filter_keys(AnchorDecayConfig, data['anchor_decay'])) if 'anchor_decay' in data else AnchorDecayConfig(),
            dreamer=DreamerConfig(**filter_keys(DreamerConfig, data['dreamer'])) if 'dreamer' in data else DreamerConfig(),
            logging=LoggingConfig(**filter_keys(LoggingConfig, data['logging'])) if 'logging' in data else LoggingConfig(),
            temporal_retrieval=TemporalRetrievalConfig(**filter_keys(TemporalRetrievalConfig, data['temporal_retrieval'])) if 'temporal_retrieval' in data else TemporalRetrievalConfig(),
            anchor_guardian=AnchorGuardianConfig(**filter_keys(AnchorGuardianConfig, data['anchor_guardian'])) if 'anchor_guardian' in data else AnchorGuardianConfig(),
            associative_surfacing=AssociativeSurfacingConfig(**filter_keys(AssociativeSurfacingConfig, data['associative_surfacing'])) if 'associative_surfacing' in data else AssociativeSurfacingConfig(),
            precision_guard=PrecisionGuardConfig(**filter_keys(PrecisionGuardConfig, data['precision_guard'])) if 'precision_guard' in data else PrecisionGuardConfig(),
            open_loop=OpenLoopConfig(**filter_keys(OpenLoopConfig, data['open_loop'])) if 'open_loop' in data else OpenLoopConfig(),
            urgency_pulse=UrgencyPulseConfig(**filter_keys(UrgencyPulseConfig, data['urgency_pulse'])) if 'urgency_pulse' in data else UrgencyPulseConfig(),
            session_closure=SessionClosureConfig(**filter_keys(SessionClosureConfig, data['session_closure'])) if 'session_closure' in data else SessionClosureConfig(),
            integration=IntegrationConfig(**filter_keys(IntegrationConfig, data['integration'])) if 'integration' in data else IntegrationConfig(),
            tools=ToolsConfig(**filter_keys(ToolsConfig, data['tools'])) if 'tools' in data else ToolsConfig(),
            proxy=ProxyConfig(**filter_keys(ProxyConfig, data['proxy'])) if 'proxy' in data else ProxyConfig(),
            prompt=PromptConfig(**filter_keys(PromptConfig, data['prompt'])) if 'prompt' in data else PromptConfig(),
            watchdog=WatchdogConfig(**filter_keys(WatchdogConfig, data['watchdog'])) if 'watchdog' in data else WatchdogConfig(),
            ui=UiConfig(**filter_keys(UiConfig, data['ui'])) if 'ui' in data else UiConfig(),
            sse=SseConfig(**filter_keys(SseConfig, data['sse'])) if 'sse' in data else SseConfig(),
            http=HttpConfig(**filter_keys(HttpConfig, data['http'])) if 'http' in data else HttpConfig(),
            manifest=ModelManifest.load(Path(path).parent / "models_manifest.json") if (Path(path).parent / "models_manifest.json").exists() else None
        )
