import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)


def shortlist_jobs_with_ai(jobs: list[dict], config: dict) -> list[dict]:
    """
    Use an LLM to score and shortlist jobs.

    Returns the original job dicts enriched with optional:
      - ai_score
      - ai_reason
    """
    ai_cfg = config.get("ai", {})
    if not ai_cfg.get("enabled", False):
        return jobs
    if not jobs:
        return []

    api_key_env = ai_cfg.get("api_key_env", "GROQ_API_KEY")
    api_key = _resolve_api_key(ai_cfg, api_key_env)
    if not api_key:
        logger.warning("AI ranking enabled but %s is not set; skipping AI step", api_key_env)
        return jobs

    max_jobs = int(ai_cfg.get("max_jobs_to_evaluate", 120))
    top_k = int(ai_cfg.get("top_k", 30))
    desc_chars = int(ai_cfg.get("max_description_chars", 400))
    endpoint = ai_cfg.get("endpoint", "https://api.groq.com/openai/v1/chat/completions")
    model = ai_cfg.get("model", "llama-3.3-70b-versatile")
    timeout_s = int(ai_cfg.get("timeout_seconds", 45))

    # Prioritize most recent items before sending to model.
    candidates = sorted(jobs, key=lambda j: j.get("created") or "", reverse=True)[:max_jobs]
    logger.info("AI ranking %s candidate jobs (from %s fetched)", len(candidates), len(jobs))

    shortlist = None
    working_candidates = candidates
    working_desc_chars = desc_chars
    for _ in range(5):
        shortlist, payload_too_large = _call_model(
            candidates=working_candidates,
            top_k=min(top_k, len(working_candidates)),
            desc_chars=working_desc_chars,
            ai_cfg=ai_cfg,
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            timeout_s=timeout_s,
        )
        if shortlist is not None:
            candidates = working_candidates
            break
        if not payload_too_large:
            break

        # Back off aggressively on 413 to stay below model limits.
        next_count = max(20, int(len(working_candidates) * 0.65))
        next_desc_chars = max(120, int(working_desc_chars * 0.7))
        if next_count == len(working_candidates) and next_desc_chars == working_desc_chars:
            break
        logger.warning(
            "AI payload too large; retrying with %s jobs and %s description chars",
            next_count,
            next_desc_chars,
        )
        working_candidates = working_candidates[:next_count]
        working_desc_chars = next_desc_chars

    if shortlist is None:
        logger.warning("AI ranking failed; falling back to non-AI results")
        return jobs

    jobs_by_id = {j["id"]: j for j in jobs}
    selected = []
    for row in shortlist.get("selected", []):
        job_id = row.get("id")
        if not job_id or job_id not in jobs_by_id:
            continue
        job = dict(jobs_by_id[job_id])
        if "score" in row:
            job["ai_score"] = row["score"]
        if "reason" in row:
            job["ai_reason"] = row["reason"]
        selected.append(job)

    logger.info("AI shortlist: %s selected out of %s candidates", len(selected), len(candidates))
    return selected


def _call_model(
    *,
    candidates: list[dict],
    top_k: int,
    desc_chars: int,
    ai_cfg: dict,
    endpoint: str,
    model: str,
    api_key: str,
    timeout_s: int,
) -> tuple[dict[str, Any] | None, bool]:
    job_payload = []
    for j in candidates:
        job_payload.append(
            {
                "id": j.get("id"),
                "title": j.get("title"),
                "company": j.get("company"),
                "location": j.get("location"),
                "category": j.get("category"),
                "salary_min": j.get("salary_min"),
                "salary_max": j.get("salary_max"),
                "created": j.get("created"),
                "description": (j.get("description") or "")[:desc_chars],
            }
        )

    target_roles = ai_cfg.get("target_roles", [])
    must_have = ai_cfg.get("must_have_keywords", [])
    nice_to_have = ai_cfg.get("nice_to_have_keywords", [])
    avoid = ai_cfg.get("avoid_keywords", [])

    system_prompt = (
        "You are a hiring-market analyst. Rank job listings for relevance and quality. "
        "Return strict JSON only with no markdown."
    )
    user_prompt = (
        "Rank jobs and return the best matches.\n"
        f"Target roles: {target_roles}\n"
        f"Must-have keywords: {must_have}\n"
        f"Nice-to-have keywords: {nice_to_have}\n"
        f"Avoid keywords: {avoid}\n"
        f"Select up to {top_k} jobs.\n"
        "Output JSON schema:\n"
        "{\n"
        '  "selected": [\n'
        '    {"id": "job-id", "score": 0-100, "reason": "short reason"}\n'
        "  ]\n"
        "}\n"
        "Rules:\n"
        "- Only use ids from the input list\n"
        "- Prefer role match, recency, salary signal, and clarity of responsibilities\n"
        "- Penalize seniority mismatch and obvious security-clearance dependency\n"
        "- Sort selected by score descending\n\n"
        f"Jobs:\n{json.dumps(job_payload, ensure_ascii=True)}"
    )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    if ai_cfg.get("use_json_mode", True):
        body["response_format"] = {"type": "json_object"}

    try:
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        payload = resp.json()
        content = payload["choices"][0]["message"]["content"]
        return _parse_json(content), False
    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 401:
            logger.error(
                "AI request unauthorized (401). Verify your Groq API key in ai.api_key "
                "or the %s environment variable.",
                ai_cfg.get("api_key_env", "OPENAI_API_KEY"),
            )
            return None, False
        if status_code == 413:
            return None, True
        else:
            logger.error("AI request/parse failed: %s", e)
            return None, False
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        logger.error("AI request/parse failed: %s", e)
        return None, False


def _resolve_api_key(ai_cfg: dict, api_key_env: str) -> str:
    # Allow either direct config key or environment variable.
    raw_key = ai_cfg.get("api_key") or os.getenv(api_key_env, "")
    if not isinstance(raw_key, str):
        return ""

    cleaned = raw_key.strip().strip('"').strip("'")
    return cleaned


def _parse_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json", "", 1).strip()
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Model output is not a JSON object")
    if "selected" not in data or not isinstance(data["selected"], list):
        raise ValueError("Model output missing 'selected' array")
    return data
