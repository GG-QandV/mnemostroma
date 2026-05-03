# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma Log Analyzer — mnemostroma logs command.

Reads logs.db, finds anomalies, outputs calibration recommendations.
"""

import argparse
import json
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────

@dataclass
class AnalysisReport:
    """Full analysis report with findings and recommendations."""
    period_days: int = 7
    total_logs: int = 0
    total_sessions: int = 0

    # Observer
    filter_stats: dict = field(default_factory=dict)
    ner_stats: dict = field(default_factory=dict)
    embed_stats: dict = field(default_factory=dict)
    score_stats: dict = field(default_factory=dict)

    # Tuner
    conflicts_detected: int = 0
    drifts_detected: int = 0

    # Dissolver
    evictions: int = 0
    eviction_reasons: dict = field(default_factory=dict)

    # Performance
    latency_anomalies: list = field(default_factory=list)

    # Health
    ram_peak_mb: float = 0.0
    health_issues: list = field(default_factory=list)

    # Feedback
    feedback_stats: dict = field(default_factory=dict)

    # Recommendations
    recommendations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Database access
# ─────────────────────────────────────────────────────────────

def connect_db(db_path: str) -> sqlite3.Connection:
    """Connect to logs.db."""
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"logs.db not found: {path}")
    return sqlite3.connect(str(path))


def fetch_logs(db: sqlite3.Connection, days: int, component: str = None) -> list[dict]:
    """Fetch log entries for the given period."""
    cutoff = int((time.time() - days * 86400) * 1000)
    query = "SELECT ts, component, event, data, latency_ms, session_id, level FROM onnx_logs WHERE ts > ?"
    params = [cutoff]

    if component:
        query += " AND component = ?"
        params.append(component)

    query += " ORDER BY ts"
    rows = db.execute(query, params).fetchall()

    return [
        {
            "ts": r[0],
            "component": r[1],
            "event": r[2],
            "data": json.loads(r[3]),
            "latency_ms": r[4],
            "session_id": r[5],
            "level": r[6],
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────
# Analysis functions
# ─────────────────────────────────────────────────────────────

def analyze_filter(logs: list[dict], report: AnalysisReport):
    """Analyze Observer filter decisions."""
    filter_logs = [l for l in logs if l["component"] == "observer.filter"]
    if not filter_logs:
        return

    importance_counts = Counter(l["data"].get("importance") for l in filter_logs)
    ner_requested = sum(1 for l in filter_logs if l["data"].get("needs_ner"))

    report.filter_stats = {
        "total": len(filter_logs),
        "importance_distribution": dict(importance_counts),
        "ner_call_rate_actual": round(ner_requested / len(filter_logs), 3) if filter_logs else 0,
        "background_percent": round(importance_counts.get("background", 0) / len(filter_logs) * 100, 1),
    }

    # Warning: if >80% background — filter is too aggressive
    bg_pct = report.filter_stats["background_percent"]
    if bg_pct > 80:
        report.warnings.append(
            f"Filter marks {bg_pct}% as background — possibly too aggressive. "
            f"Consider adding more importance_signals or ↓ observer_ner_call_rate_target."
        )

    # Warning: if <30% background — filter is too permissive
    if bg_pct < 30:
        report.warnings.append(
            f"Filter marks only {bg_pct}% as background — possibly too permissive. "
            f"RAM may fill with low-value sessions."
        )

    # Recommendation: NER call rate
    actual_rate = report.filter_stats["ner_call_rate_actual"]
    if actual_rate > 0.60:
        report.recommendations.append(
            f"NER call rate is {actual_rate:.0%} — high. "
            f"Filter may not be confident enough. Add more deterministic signals."
        )


def analyze_ner(logs: list[dict], report: AnalysisReport):
    """Analyze GLiNER NER extraction quality."""
    ner_logs = [l for l in logs if l["component"] == "observer.ner"]
    if not ner_logs:
        return

    entity_counts = [l["data"].get("entities_count", len(l["data"].get("entities", []))) for l in ner_logs]
    latencies = [l["latency_ms"] for l in ner_logs if l["latency_ms"]]
    low_score_entities = []

    for l in ner_logs:
        for e in l["data"].get("entities", []):
            if e.get("score", 1.0) < 0.70:
                low_score_entities.append(e)

    report.ner_stats = {
        "total_calls": len(ner_logs),
        "avg_entities_per_call": round(sum(entity_counts) / len(entity_counts), 2) if entity_counts else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "low_score_entities_count": len(low_score_entities),
    }

    # Warning: GLiNER too slow
    avg_lat = report.ner_stats["avg_latency_ms"]
    if avg_lat > 15:
        report.warnings.append(
            f"GLiNER avg latency {avg_lat}ms > 15ms threshold. "
            f"Consider gliner_mode='small' or check CPU load."
        )

    # Recommendation: too many low-score entities
    if low_score_entities and len(low_score_entities) / max(len(ner_logs), 1) > 0.3:
        report.recommendations.append(
            f"{len(low_score_entities)} entities with score < 0.70. "
            f"Consider ↑ ner_score_threshold to reduce noise."
        )


def analyze_scores(logs: list[dict], report: AnalysisReport):
    """Analyze Score distribution and balance."""
    score_logs = [l for l in logs if l["component"] == "observer.score"]
    if not score_logs:
        return

    scores = [l["data"].get("score", 0) for l in score_logs]
    r_values = [l["data"].get("R", 0) for l in score_logs]
    t_values = [l["data"].get("T", 0) for l in score_logs]
    i_values = [l["data"].get("I", 0) for l in score_logs]

    report.score_stats = {
        "total": len(score_logs),
        "avg_score": round(sum(scores) / len(scores), 3),
        "min_score": round(min(scores), 3),
        "max_score": round(max(scores), 3),
        "avg_R": round(sum(r_values) / len(r_values), 3),
        "avg_T": round(sum(t_values) / len(t_values), 3),
        "avg_I": round(sum(i_values) / len(i_values), 3),
    }

    # Warning: all scores too similar (no differentiation)
    score_range = report.score_stats["max_score"] - report.score_stats["min_score"]
    if score_range < 0.15 and len(scores) > 20:
        report.warnings.append(
            f"Score range is only {score_range:.3f} — poor differentiation. "
            f"All sessions look equally important. Adjust α/β/γ weights."
        )

    # Warning: temporal dominates
    avg_t = report.score_stats["avg_T"]
    avg_r = report.score_stats["avg_R"]
    if avg_t > avg_r * 1.5:
        report.recommendations.append(
            f"Temporal component (avg T={avg_t:.3f}) dominates over relevance (avg R={avg_r:.3f}). "
            f"Recent sessions always win. Consider ↓ score_weight_temporal or ↓ temporal_decay_lambda."
        )


def analyze_latencies(logs: list[dict], report: AnalysisReport):
    """Find latency anomalies across all components."""
    thresholds = {
        "observer.filter": 1.0,
        "observer.ner": 20.0,
        "observer.embed": 25.0,
        "observer.score": 1.0,
        "matrix.search": 10.0,
        "reranker.rerank": 15.0,
        "tools.semantic": 40.0,
        "tools.inject": 30.0,
        "storage.flush": 20.0,
    }

    for log in logs:
        component = log["component"]
        latency = log.get("latency_ms", 0)
        threshold = thresholds.get(component)

        if threshold and latency > threshold * 2:  # >2x expected = anomaly
            report.latency_anomalies.append({
                "component": component,
                "latency_ms": latency,
                "threshold_ms": threshold,
                "ts": log["ts"],
                "session_id": log.get("session_id"),
            })

    if len(report.latency_anomalies) > 10:
        report.warnings.append(
            f"{len(report.latency_anomalies)} latency anomalies detected. "
            f"Check CPU load or model optimization."
        )


def analyze_conflicts(logs: list[dict], report: AnalysisReport):
    """Analyze conflict detection."""
    conflict_logs = [l for l in logs if l["component"] == "tuner.conflict"]
    report.conflicts_detected = sum(
        1 for l in conflict_logs if l["data"].get("conflict_detected")
    )

    if report.conflicts_detected > 10:
        report.warnings.append(
            f"{report.conflicts_detected} conflicts detected. "
            f"Many contradictory decisions. Check conflict_signal_threshold."
        )


def analyze_evictions(logs: list[dict], report: AnalysisReport):
    """Analyze Dissolver eviction patterns."""
    evict_logs = [l for l in logs if l["component"] == "dissolver.evict"]
    report.evictions = len(evict_logs)

    reasons = Counter(l["data"].get("reason") for l in evict_logs)
    report.eviction_reasons = dict(reasons)

    if reasons.get("ram_hard_limit", 0) > 0:
        report.errors.append(
            f"RAM hard limit evictions: {reasons['ram_hard_limit']} times! "
            f"System under memory pressure. ↑ ram_hard_limit_mb or ↓ session_window_size."
        )


def analyze_feedback(logs: list[dict], report: AnalysisReport):
    """Analyze implicit feedback signals."""
    fb_logs = [l for l in logs if l["component"] == "feedback.implicit"]
    signal_counts = Counter(l["data"].get("type") for l in fb_logs)

    report.feedback_stats = {
        "total": len(fb_logs),
        "signals": dict(signal_counts),
    }

    use_count = signal_counts.get("USE", 0) + signal_counts.get("DEEP_USE", 0)
    ignore_count = signal_counts.get("IGNORE", 0)
    total = use_count + ignore_count

    if total > 20:
        use_rate = use_count / total
        if use_rate < 0.3:
            report.recommendations.append(
                f"Memory USE rate is {use_rate:.0%} — agent ignores 70%+ of retrieved memory. "
                f"Retrieval quality may be low. Check Score weights and embedding quality."
            )


def analyze_health(logs: list[dict], report: AnalysisReport):
    """Analyze health checks."""
    health_logs = [l for l in logs if l["component"] == "conductor.health"]

    ram_values = [l["data"].get("ram_mb", 0) for l in health_logs]
    if ram_values:
        report.ram_peak_mb = max(ram_values)

    for l in health_logs:
        issues = l["data"].get("issues", [])
        if issues:
            report.health_issues.extend(issues)

    if report.ram_peak_mb > 500:
        report.warnings.append(
            f"RAM peak: {report.ram_peak_mb}MB — approaching 600MB budget. "
            f"Monitor session_window_size."
        )


# ─────────────────────────────────────────────────────────────
# Report formatting
# ─────────────────────────────────────────────────────────────

def format_report(report: AnalysisReport) -> str:
    """Format report as human-readable text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  MNEMOSTROMA LOG ANALYSIS REPORT")
    lines.append(f"  Period: last {report.period_days} days")
    lines.append(f"  Total log entries: {report.total_logs}")
    lines.append("=" * 60)

    # Observer Filter
    if report.filter_stats.get('total'):
        lines.append("\n── OBSERVER FILTER ──")
        fs = report.filter_stats
        lines.append(f"  Total decisions: {fs['total']}")
        lines.append(f"  Distribution: {fs['importance_distribution']}")
        lines.append(f"  Background: {fs['background_percent']}%")
        lines.append(f"  NER call rate (actual): {fs['ner_call_rate_actual']:.1%}")

    # NER
    if report.ner_stats:
        lines.append("\n── OBSERVER NER ──")
        ns = report.ner_stats
        lines.append(f"  Total calls: {ns['total_calls']}")
        lines.append(f"  Avg entities/call: {ns['avg_entities_per_call']}")
        lines.append(f"  Avg latency: {ns['avg_latency_ms']}ms")
        lines.append(f"  Low-score entities: {ns['low_score_entities_count']}")

    # Score
    if report.score_stats:
        lines.append("\n── SCORE DISTRIBUTION ──")
        ss = report.score_stats
        lines.append(f"  Avg Score: {ss['avg_score']} (range: {ss['min_score']}–{ss['max_score']})")
        lines.append(f"  Avg components: R={ss['avg_R']}, T={ss['avg_T']}, I={ss['avg_I']}")

    # Conflicts & Evictions
    lines.append(f"\n── TUNER & DISSOLVER ──")
    lines.append(f"  Conflicts detected: {report.conflicts_detected}")
    lines.append(f"  Evictions: {report.evictions} ({report.eviction_reasons})")
    lines.append(f"  RAM peak: {report.ram_peak_mb}MB")

    # Feedback
    if report.feedback_stats.get("total", 0) > 0:
        lines.append(f"\n── FEEDBACK ──")
        lines.append(f"  Total signals: {report.feedback_stats['total']}")
        lines.append(f"  Breakdown: {report.feedback_stats['signals']}")

    # Latency anomalies
    if report.latency_anomalies:
        lines.append(f"\n── LATENCY ANOMALIES ({len(report.latency_anomalies)}) ──")
        for a in report.latency_anomalies[:5]:
            lines.append(f"  {a['component']}: {a['latency_ms']}ms (expected <{a['threshold_ms']}ms)")
        if len(report.latency_anomalies) > 5:
            lines.append(f"  ... and {len(report.latency_anomalies) - 5} more")

    # Errors
    if report.errors:
        lines.append(f"\n🔴 ERRORS ({len(report.errors)})")
        for e in report.errors:
            lines.append(f"  !! {e}")

    # Warnings
    if report.warnings:
        lines.append(f"\n🟡 WARNINGS ({len(report.warnings)})")
        for w in report.warnings:
            lines.append(f"  ⚠ {w}")

    # Recommendations
    if report.recommendations:
        lines.append(f"\n🟢 RECOMMENDATIONS ({len(report.recommendations)})")
        for r in report.recommendations:
            lines.append(f"  → {r}")

    if not report.errors and not report.warnings and not report.recommendations:
        lines.append(f"\n✅ No issues found. System operating normally.")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def analyze_experience(logs: list[dict], report: AnalysisReport):
    """Analyze Experience Layer intuition signal activity."""
    exp_logs = [l for l in logs if l["component"] == "experience.signal"]
    if not exp_logs:
        return

    by_type = Counter(l["data"].get("type") for l in exp_logs)
    by_tag  = defaultdict(list)
    for l in exp_logs:
        by_tag[l["data"].get("tag", "?")].append(l["data"].get("avg_score", 0))

    top_tags = sorted(by_tag.items(), key=lambda x: -len(x[1]))[:5]

    report.filter_stats["experience"] = {
        "total_signals": len(exp_logs),
        "by_type": dict(by_type),
        "top_tags": [
            {"tag": t, "fires": len(scores), "avg_score": round(sum(scores)/len(scores), 3)}
            for t, scores in top_tags
        ],
    }

    tension_count = by_type.get("TENSION", 0)
    if tension_count >= 3:
        report.warnings.append(
            f"Experience Layer: {tension_count} TENSION signals — "
            f"conflicting decisions accumulating. Review related sessions."
        )

    avoid_count = by_type.get("AVOID_THIS", 0)
    if avoid_count >= 5:
        report.recommendations.append(
            f"Experience Layer: {avoid_count} AVOID_THIS signals — "
            f"recurring negative patterns. Check tags with low avg_score."
        )


def analyze_calibration(logs: list[dict], report: AnalysisReport):
    """Analyze calibration threshold updates."""
    cal_logs = [l for l in logs if l["component"] == "calibration.update"]
    if not cal_logs:
        return

    last = cal_logs[0]["data"]
    old_t = last.get("threshold_old")
    new_t = last.get("threshold_new")
    samples = last.get("samples", 0)

    report.filter_stats["calibration"] = {
        "updates": len(cal_logs),
        "last_threshold_old": old_t,
        "last_threshold_new": new_t,
        "last_samples": samples,
    }

    if old_t and new_t:
        delta = abs(new_t - old_t)
        if delta > 0.1:
            report.recommendations.append(
                f"Calibration shifted threshold by {delta:.3f} "
                f"({old_t} → {new_t}). "
                f"Large jump — consider monitoring continuation accuracy."
            )


def _format_experience_section(report: AnalysisReport) -> list[str]:
    """Format Experience + Calibration sections for text report."""
    lines = []
    exp = report.filter_stats.get("experience")
    cal = report.filter_stats.get("calibration")

    if exp:
        lines.append("\n── EXPERIENCE LAYER ──")
        lines.append(f"  Intuition signals: {exp['total_signals']}  {exp['by_type']}")
        for t in exp["top_tags"]:
            lines.append(f"    {t['tag']}: {t['fires']} fires  avg_score={t['avg_score']}")

    if cal:
        lines.append("\n── CALIBRATION ──")
        lines.append(f"  Updates: {cal['updates']}")
        if cal["last_threshold_old"] is not None:
            lines.append(
                f"  Last: {cal['last_threshold_old']} → {cal['last_threshold_new']} "
                f"({cal['last_samples']} samples)"
            )
    return lines


# Patch format_report to include new sections
_orig_format_report = format_report

def format_report(report: AnalysisReport) -> str:
    base = _orig_format_report(report)
    extra = _format_experience_section(report)
    if extra:
        # Insert before the ERRORS/WARNINGS/RECOMMENDATIONS block
        insert_marker = "\n🔴 ERRORS"
        alt_marker = "\n🟡 WARNINGS"
        marker = insert_marker if insert_marker in base else alt_marker
        if marker in base:
            idx = base.index(marker)
            return base[:idx] + "\n".join(extra) + "\n" + base[idx:]
        return base + "\n".join(extra)
    return base


def _build_report(db_path: str, days: int) -> tuple[AnalysisReport, sqlite3.Connection]:
    db = connect_db(db_path)
    logs = fetch_logs(db, days)
    report = AnalysisReport(period_days=days, total_logs=len(logs))
    report.total_sessions = len(set(l["session_id"] for l in logs if l["session_id"]))
    analyze_filter(logs, report)
    analyze_ner(logs, report)
    analyze_scores(logs, report)
    analyze_latencies(logs, report)
    analyze_conflicts(logs, report)
    analyze_evictions(logs, report)
    analyze_feedback(logs, report)
    analyze_health(logs, report)
    analyze_experience(logs, report)
    analyze_calibration(logs, report)
    return report, db


def run_logs(db_path: str = "logs.db", days: int = 7, as_json: bool = False) -> None:
    """Entry point for `mnemostroma logs` CLI command."""
    try:
        report, db = _build_report(db_path, days)
        db.close()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        print("Start the daemon first: mnemostroma run")
        return

    if as_json:
        from dataclasses import asdict
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        print(format_report(report))


def main():
    parser = argparse.ArgumentParser(description="Mnemostroma Log Analyzer")
    parser.add_argument("--db",   default="logs.db", help="Path to logs.db")
    parser.add_argument("--days", type=int, default=7, help="Analysis period in days")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    run_logs(args.db, args.days, args.json)


if __name__ == "__main__":
    main()
