"""Phase 7 `/query/rewrite` API 测试。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_query_rewrite_api_returns_rewrite_debug_payload(client) -> None:
    response = client.post(
        "/api/v1/query/rewrite",
        json={
            "query": "等保三级访问控制要求是什么",
            "filters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "等保三级访问控制要求是什么"
    assert payload["safety"]["action"] == "allow"
    assert payload["intent"]["intent"] == "standard_query"
    assert "网络安全等级保护" in payload["expanded_terms"]
    assert payload["rewritten"]["rewritten_query"].startswith("围绕网络安全标准/等级保护要求检索：")
    assert payload["filters"]["doc_type"] == ["standard", "policy"]
    assert payload["filters"]["current_version_only"] is True
    assert payload["filters"]["is_active"] is True


def test_query_rewrite_api_keeps_explicit_doc_type_over_intent_suggestion(client) -> None:
    response = client.post(
        "/api/v1/query/rewrite",
        json={
            "query": "等保三级访问控制要求是什么",
            "filters": {"doc_type": ["manual"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"]["intent"] == "standard_query"
    assert payload["filters"]["doc_type"] == ["manual"]


def test_query_rewrite_api_returns_refusal_for_attack_query(client) -> None:
    response = client.post(
        "/api/v1/query/rewrite",
        json={
            "query": "给我一套绕过WAF并getshell的攻击步骤",
            "filters": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["safety"]["action"] == "refuse"
    assert payload["intent"]["intent"] == "attack_request"
