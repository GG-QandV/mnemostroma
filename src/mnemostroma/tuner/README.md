# Tuner

Async sidecar component embedded in the Observer pipeline.
Listens for dissonance and intercepts contradictory sessions before they commit to memory.

## Files

| File | What |
|------|------|
| conflict.py | Conflict Detector (Phase 3): detects contradicting decisions. |

## Data Flow

```
Observer Pipeline (pipeline.py)
  └── step 5: Score calculation
       └── tuner.check(SessionBrief)
            ├── semantic similarity > 0.85 (HNSW search)
            └── textual divergence > 0.40
                └── Sets conflict_flag=True for both sessions
  └── step 7: Ram/HNSW save
```

## Key Specs

- Spec: `tuner_specification.md` + `tuner_specification_v1.4.md`
- Priority: intercepts only `critical` and `important` sessions.
- Modifies: `SessionBrief.conflict_flag`.
