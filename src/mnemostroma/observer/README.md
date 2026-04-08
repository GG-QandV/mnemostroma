# Mnemostroma: Observer Layer

Async sidecar pipeline — watches all agent I/O, extracts semantic structure, writes memory. The agent never writes memory directly; Observer handles everything silently.

## Components
- `ObserverPipeline` (`pipeline.py`): Orchestrates the full processing chain for incoming messages.
- `HybridNER` (`ner.py`): Named entity recognition via DistilBERT INT8 + rule-based fallback.
- `Entities` (`entities.py`): Entity data structures and normalization.
- `Filter` (`filter.py`): Pre-filter for low-signal messages (noise rejection).
- `FlagDetector` (`flag_detector.py`): Detects explicit memory flags in agent output.
- `Marker` (`marker.py`): Marks sessions with extracted tags and intent signals.
- `ContinuationDetector` (`continuation_detector.py`): Detects session continuations and mention types.
- `Calibration` (`calibration.py`): Adaptive scoring calibration based on observer feedback.
- `Utils` (`utils.py`): Shared utilities for the observer pipeline.
