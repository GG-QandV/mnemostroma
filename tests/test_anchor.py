# SPDX-License-Identifier: FSL-1.1-MIT
import time
import pytest
from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.subconscious.anchor_index import AnchorIndex


class TestAnchor:
    def test_create_anchor(self):
        a = Anchor(
            anchor_id="s001",
            session_id="s001",
            brief="Выбрали PostgreSQL для проекта",
            anchor_type="decision",
            key_facts=[
                {"type": "решение", "value": "PostgreSQL", "score": 0.95, "priority": 1}
            ],
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        assert a.anchor_type == "decision"
        assert a.decay_level == 0
        assert a.access_count == 0

    def test_touch_increments_access(self):
        a = Anchor(
            anchor_id="s001", session_id="s001", brief="test",
            anchor_type="observation", created_at=1000, updated_at=1000,
        )
        a.touch()
        assert a.access_count == 1
        assert a.last_accessed_at > 1000

    def test_to_dict_from_dict_roundtrip(self):
        a = Anchor(
            anchor_id="s001", session_id="s001", brief="test brief",
            anchor_type="decision",
            key_facts=[{"type": "tech", "value": "Python", "score": 0.9, "priority": 3}],
            created_at=1000, updated_at=1000,
        )
        d = a.to_dict()
        a2 = Anchor.from_dict(d)
        assert a2.anchor_id == a.anchor_id
        assert a2.key_facts == a.key_facts
        assert a2.flags == a.flags


class TestAnchorIndex:
    def test_put_and_get(self):
        idx = AnchorIndex(max_capacity=10)
        a = Anchor(
            anchor_id="s001", session_id="s001", brief="test",
            anchor_type="decision", created_at=1000, updated_at=1000,
        )
        evicted = idx.put(a)
        assert evicted is None
        assert idx.get("s001") is a
        assert len(idx) == 1

    def test_eviction_at_capacity(self):
        idx = AnchorIndex(max_capacity=3)
        for i in range(3):
            a = Anchor(
                anchor_id=f"s{i:03d}", session_id=f"s{i:03d}", brief=f"test {i}",
                anchor_type="observation",
                created_at=1000 + i, updated_at=1000 + i,
                last_accessed_at=1000 + i,
            )
            idx.put(a)
        
        # 4th anchor should evict oldest (s000)
        a4 = Anchor(
            anchor_id="s003", session_id="s003", brief="test 3",
            anchor_type="observation",
            created_at=2000, updated_at=2000, last_accessed_at=2000,
        )
        evicted = idx.put(a4)
        assert evicted is not None
        assert evicted.anchor_id == "s000"
        assert len(idx) == 3
        assert "s000" not in idx

    def test_query_by_type(self):
        idx = AnchorIndex()
        idx.put(Anchor(
            anchor_id="s001", session_id="s001", brief="chose DB",
            anchor_type="decision", created_at=1000, updated_at=1000,
        ))
        idx.put(Anchor(
            anchor_id="s002", session_id="s002", brief="daily standup",
            anchor_type="observation", created_at=1001, updated_at=1001,
        ))
        
        decisions = idx.query_by_type("decision")
        assert len(decisions) == 1
        assert decisions[0].anchor_id == "s001"

    def test_resurface_updates_access(self):
        idx = AnchorIndex()
        a = Anchor(
            anchor_id="s001", session_id="s001", brief="test",
            anchor_type="event", created_at=1000, updated_at=1000,
        )
        idx.put(a)
        
        result = idx.resurface("s001")
        assert result.access_count == 1
        assert result.last_accessed_at > 1000

    def test_build_key_facts_priority_order(self):
        entities = [
            {"type": "технология", "value": "Python", "score": 0.9},
            {"type": "решение", "value": "использовать FastAPI", "score": 0.85},
            {"type": "дата", "value": "2025-01-15", "score": 0.95},
            {"type": "человек", "value": "Коваленко", "score": 0.8},
        ]
        facts = AnchorIndex.build_key_facts(entities, max_facts=3)
        # решение (priority 1) first, then человек (2), then технология (3)
        assert facts[0]["type"] == "решение"
        assert facts[1]["type"] == "человек"
        assert len(facts) == 3

    def test_infer_anchor_type(self):
        assert AnchorIndex.infer_anchor_type(
            "normal", [{"type": "решение"}]
        ) == "decision"
        assert AnchorIndex.infer_anchor_type(
            "normal", [{"type": "запрет"}]
        ) == "constraint"
        assert AnchorIndex.infer_anchor_type(
            "critical", [{"type": "технология"}]
        ) == "milestone"
        assert AnchorIndex.infer_anchor_type(
            "normal", [{"type": "дата"}]
        ) == "event"
        assert AnchorIndex.infer_anchor_type(
            "normal", [{"type": "технология"}]
        ) == "observation"
