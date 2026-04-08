# Mnemostroma: Tuner Layer

Async sidecar embedded in the Observer pipeline. Detects dissonance and intercepts contradictory sessions before they commit to memory.

## Components

| File | What |
|------|------|
| `conflict.py` | Conflict Detector: detects contradicting decisions via semantic similarity + textual divergence. |
| `drift.py` | Drift Detector: tracks gradual concept drift across sessions over time. |

## Data Flow

```
Observer Pipeline (pipeline.py)
  └── step 5: Score calculation
       └── tuner.check(SessionBrief)
            ├── semantic similarity > 0.85 (MatrixSearch ANN)
            └── textual divergence > 0.40
                └── Sets conflict_flag=True for both sessions
  └── step 7: RAM / MatrixSearch save
```

## Key Specs
- Intercepts only `critical` and `important` sessions.
- Modifies: `SessionBrief.conflict_flag`.
