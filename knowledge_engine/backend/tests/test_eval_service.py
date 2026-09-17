"""Phase 10 eval_service 测试。"""

from __future__ import annotations

import json

from app.services.eval_service import compute_mrr, compute_recall_at_k, compute_refusal_accuracy, load_golden_dataset


def test_load_golden_dataset_reads_jsonl(tmp_path) -> None:
    dataset_path = tmp_path / "golden.jsonl"
    dataset_path.write_text(
        "\n".join(
            [
                json.dumps({"query": "q1", "expected_refusal": False, "expected_chunk_ids": ["c1"]}, ensure_ascii=False),
                json.dumps({"query": "q2", "expected_refusal": True}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    entries = load_golden_dataset(dataset_path)

    assert len(entries) == 2
    assert entries[0].query == "q1"
    assert entries[0].expected_chunk_ids == ["c1"]
    assert entries[1].expected_refusal is True


def test_compute_recall_at_k_returns_ratio() -> None:
    assert compute_recall_at_k([True, False, True]) == 2 / 3
    assert compute_recall_at_k([]) == 0.0


def test_compute_mrr_returns_mean_reciprocal_rank() -> None:
    assert compute_mrr([1.0, 0.5, 0.0]) == 0.5
    assert compute_mrr([]) == 0.0


def test_compute_refusal_accuracy_returns_match_ratio() -> None:
    assert compute_refusal_accuracy([True, False, True], [True, True, True]) == 2 / 3
