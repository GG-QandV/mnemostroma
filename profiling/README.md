# profiling/

Internal parameter measurement scripts — for validating system characteristics
under controlled conditions (latency, RAM, retrieval quality, throughput).

Not competitive benchmarks. These scripts measure *this system against its own
design targets*, not against other tools.

Planned:
- `retrieval_latency.py` — MatrixSearch ANN latency under various index sizes
- `ram_usage.py` — RSS measurement across bootstrap, idle, and peak load
- `pipeline_throughput.py` — Observer pipeline throughput (texts/sec)
- `embedding_quality.py` — Cosine similarity distribution sanity checks
