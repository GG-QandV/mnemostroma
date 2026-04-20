import sqlite3
import json
import os
from datetime import datetime

LOGS_DB = "/home/gg/.mnemostroma/logs.db"
MAIN_DB = "/home/gg/.mnemostroma/mnemostroma.db"

def query_logs(sql):
    with sqlite3.connect(LOGS_DB) as conn:
        return conn.execute(sql).fetchall()

def query_main(sql):
    with sqlite3.connect(MAIN_DB) as conn:
        return conn.execute(sql).fetchall()

report = []
report.append("# Mnemostroma Extended Log Analytics v2")
report.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# S1
total_rows = query_logs("SELECT COUNT(*) FROM onnx_logs")[0][0]
report.append(f"**Rows analyzed:** {total_rows}")

# S2
dist = query_logs("SELECT component, event, COUNT(*) as cnt, ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM onnx_logs), 2) FROM onnx_logs GROUP BY 1, 2 ORDER BY cnt DESC")
report.append("\n## SECTION 2 — EVENT VOLUME DISTRIBUTION")
report.append("| Component | Event | Count | % |")
report.append("|-----------|-------|-------|---|")
for row in dist:
    report.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]}% |")

# S3
health = query_logs("SELECT json_extract(data, '$.ram_mb'), json_extract(data, '$.issues'), datetime(ts/1000, 'unixepoch') FROM onnx_logs WHERE component = 'conductor.health' AND event='check' ORDER BY ts DESC LIMIT 1")
report.append("\n## SECTION 3 — INFRASTRUCTURE")
if health:
    report.append(f"- **Latest Health:** {health[0][0]} MB RAM, Issues: {health[0][1]} at {health[0][2]}")
else:
    report.append("- **Latest Health:** DATA_UNAVAILABLE")

# S4
report.append("\n## SECTION 4 — OBSERVER PIPELINE")
pipe = query_logs("SELECT AVG(latency_ms), MAX(latency_ms), COUNT(*) FROM onnx_logs WHERE (component = 'observer.pipe' OR component='pipeline') AND event = 'pipeline_total'")
if pipe[0][2] > 0:
    report.append(f"- **Pipeline Latency:** Avg {pipe[0][0]:.2f}ms, Max {pipe[0][1]:.2f}ms ({pipe[0][2]} events)")
else:
    report.append("- **Pipeline Latency:** DATA_UNAVAILABLE")

score = query_logs("SELECT COUNT(*), SUM(CASE WHEN CAST(json_extract(data,'$.score') AS FLOAT) < 0.25 THEN 1 ELSE 0 END), SUM(CASE WHEN CAST(json_extract(data,'$.score') AS FLOAT) > 0.95 THEN 1 ELSE 0 END) FROM onnx_logs WHERE component = 'observer.score' AND event = 'calculate'")
score_count = score[0][0] if score else 0
report.append(f"- **Score Anomalies:** Low (<0.25): {score[0][1] or 0}, High (>0.95): {score[0][2] or 0} (Total: {score_count})")

# S5
report.append("\n## SECTION 5 — MEMORY MANAGEMENT")
evict = query_logs("SELECT json_extract(data,'$.reason'), SUM(CAST(json_extract(data,'$.evicted_count') AS INT)), COUNT(*) FROM onnx_logs WHERE component = 'dissolver.evict' AND event = 'evict' GROUP BY 1")
if not evict:
    report.append("- No eviction events recorded.")
for row in evict:
    report.append(f"- **Eviction ({row[0]}):** {row[1]} total sessions evicted in {row[2]} cycles")

# S8
report.append("\n## SECTION 8 — DATABASE STATS")
sessions = query_main("SELECT COUNT(*) FROM sessions")[0][0]
anchors = query_main("SELECT COUNT(*) FROM anchors")[0][0]
report.append(f"- **Total Sessions:** {sessions}")
report.append(f"- **Total Anchors:** {anchors}")

# S9
report.append("\n## SECTION 9 — GAP AUDIT")
events_to_check = [
    ("conductor.bootstrap", "start"), ("conductor.health", "check"), ("conductor", "shutdown"),
    ("observer.pipe", "pipeline_total"), ("observer.score", "calculate"),
    ("dissolver.evict", "evict"), ("feedback.recalibration", "pearson"), ("tools.inject", "call")
]
report.append("| Component | Event | Status |")
report.append("|-----------|-------|--------|")
for comp, ev in events_to_check:
    cnt = query_logs(f"SELECT COUNT(*) FROM onnx_logs WHERE component = '{comp}' AND event = '{ev}'")[0][0]
    status = f"PRESENT ({cnt} rows)" if cnt > 0 else "ABSENT"
    report.append(f"| {comp} | {ev} | {status} |")

# S10
report.append("\n## SECTION 10 — ANOMALIES")
warns = query_logs("SELECT component, event, level, COUNT(*) FROM onnx_logs WHERE level IN ('ERROR', 'WARNING', 'WARN') GROUP BY 1, 2, 3")
if warns:
    for w in warns: report.append(f"- {w[0]}.{w[1]} ({w[2]}): {w[3]}")
else:
    report.append("- No errors or warnings found in recent logs.")

with open("/home/gg/projects/Project_mnemostroma/analytics/reports/session_analysis_v2.md", "w") as f:
    f.write("\n".join(report))

print("Report v2.2 generated.")
