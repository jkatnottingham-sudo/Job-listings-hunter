"""Tests for primary hard filters (keyword matching semantics)."""

from filters import apply_filters, job_matches_all_keywords


def test_job_matches_all_keywords_case_insensitive():
    job = {"title": "AWS Engineer", "description": "We need terraform skills."}
    assert job_matches_all_keywords(job, ["aws", "Terraform"])


def test_job_matches_all_keywords_fails_if_one_missing():
    job = {"title": "Java Engineer", "description": "No cloud here."}
    assert not job_matches_all_keywords(job, ["AWS", "Java"])


def test_job_matches_all_keywords_empty_list_always_true():
    job = {"title": "X", "description": "Y"}
    assert job_matches_all_keywords(job, [])
    assert job_matches_all_keywords(job, ["", "  "])


def test_apply_filters_required_keywords_all_must_match():
    jobs = [
        {"title": "A", "description": "has python and aws", "company": "c1"},
        {"title": "B", "description": "python only", "company": "c2"},
    ]
    out = apply_filters(jobs, {"required_keywords": ["python", "aws"]})
    assert len(out) == 1
    assert out[0]["title"] == "A"


def test_apply_filters_exclude_keywords():
    jobs = [
        {"title": "Good", "description": "fine", "company": "c"},
        {"title": "Bad", "description": "this mentions Director level", "company": "c"},
    ]
    out = apply_filters(jobs, {"exclude_keywords": ["director"]})
    assert len(out) == 1
    assert out[0]["title"] == "Good"
