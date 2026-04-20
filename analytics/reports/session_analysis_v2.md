# Mnemostroma Extended Log Analytics v2
**Date:** 2026-04-20 08:42:54
**Rows analyzed:** 228

## SECTION 2 — EVENT VOLUME DISTRIBUTION
| Component | Event | Count | % |
|-----------|-------|-------|---|
| conductor.bootstrap | start | 79 | 34.65% |
| conductor.health | check | 79 | 34.65% |
| dissolver.evict | evict | 70 | 30.7% |

## SECTION 3 — INFRASTRUCTURE
- **Latest Health:** 471.3 MB RAM, Issues: [] at 2026-04-20 06:30:41

## SECTION 4 — OBSERVER PIPELINE
- **Pipeline Latency:** DATA_UNAVAILABLE
- **Score Anomalies:** Low (<0.25): 0, High (>0.95): 0 (Total: 0)

## SECTION 5 — MEMORY MANAGEMENT
- **Eviction (ram_soft_limit):** 297 total sessions evicted in 70 cycles

## SECTION 8 — DATABASE STATS
- **Total Sessions:** 317
- **Total Anchors:** 311

## SECTION 9 — GAP AUDIT
| Component | Event | Status |
|-----------|-------|--------|
| conductor.bootstrap | start | PRESENT (79 rows) |
| conductor.health | check | PRESENT (79 rows) |
| conductor | shutdown | ABSENT |
| observer.pipe | pipeline_total | ABSENT |
| observer.score | calculate | ABSENT |
| dissolver.evict | evict | PRESENT (70 rows) |
| feedback.recalibration | pearson | ABSENT |
| tools.inject | call | ABSENT |

## SECTION 10 — ANOMALIES
- dissolver.evict.evict (WARNING): 3