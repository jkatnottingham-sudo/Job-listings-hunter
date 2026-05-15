"""Tests for LLM ranking prompt construction (must-have / profile wiring)."""

from ai_ranker import _build_ranking_user_prompt


def _sample_payload():
    return [
        {
            "id": "1",
            "title": "Cloud Architect",
            "company": "Acme",
            "location": "Remote",
            "category": "IT",
            "salary_min": None,
            "salary_max": None,
            "created": "2026-01-01",
            "description": "We use AWS daily.",
        }
    ]


def test_prompt_includes_hard_gate_when_must_have_non_empty():
    prompt = _build_ranking_user_prompt(
        job_payload=_sample_payload(),
        llm_cfg={"must_have_keywords": ["AWS", "Terraform"]},
        top_k=10,
    )
    assert "HARD GATE" in prompt
    assert "Must-have keywords: ['AWS', 'Terraform']" in prompt or "AWS" in prompt


def test_prompt_omits_hard_gate_when_must_have_empty():
    prompt = _build_ranking_user_prompt(
        job_payload=_sample_payload(),
        llm_cfg={"must_have_keywords": []},
        top_k=10,
    )
    assert "HARD GATE" not in prompt


def test_prompt_omits_hard_gate_when_must_have_missing():
    prompt = _build_ranking_user_prompt(
        job_payload=_sample_payload(),
        llm_cfg={},
        top_k=5,
    )
    assert "HARD GATE" not in prompt


def test_prompt_lists_target_roles_and_avoid():
    prompt = _build_ranking_user_prompt(
        job_payload=_sample_payload(),
        llm_cfg={
            "target_roles": ["Solutions Architect"],
            "avoid_keywords": ["clearance"],
        },
        top_k=3,
    )
    assert "Solutions Architect" in prompt
    assert "clearance" in prompt
    assert "Select up to 3 jobs." in prompt
