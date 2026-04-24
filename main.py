"""
Job Listings Hunter — main entry point.
Run directly or via Windows Task Scheduler.
"""

import logging
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from adzuna_client import fetch_jobs
from ai_ranker import shortlist_jobs_with_ai
from filters import apply_filters
from notifier import send_report

LOG_FILE = Path(__file__).parent / "hunter.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run():
    logger.info("=== Job Hunt starting ===")
    config = load_config()
    roles = _get_active_roles(config)
    if not roles:
        logger.warning("No active roles configured; nothing to process")
        send_report([], config)
        logger.info("=== Job Hunt done — 0 job(s) reported ===")
        return

    merged_jobs: dict[str, dict] = {}
    for role in roles:
        role_name = role.get("name", "Unnamed role")
        logger.info("=== Processing role: %s ===", role_name)
        role_cfg = _build_role_config(config, role)

        # 1. Fetch from Adzuna
        raw_jobs = fetch_jobs(role_cfg)

        # 2. Apply custom filters
        filtered_jobs = apply_filters(raw_jobs, role_cfg["filters"])

        # Optional AI stage:
        # - "replace": AI shortlists from all fetched jobs
        # - "augment": AI reranks jobs that already passed normal filters
        ai_cfg = role_cfg.get("ai", {})
        ai_mode = ai_cfg.get("mode", "replace")
        if ai_cfg.get("enabled", False):
            ai_input = raw_jobs if ai_mode == "replace" else filtered_jobs
            filtered_jobs = shortlist_jobs_with_ai(ai_input, role_cfg)
            logger.info("Post-AI result (%s): %s jobs", role_name, len(filtered_jobs))

        for job in filtered_jobs:
            _merge_job_for_role(merged_jobs, job, role_name)

    final_jobs = list(merged_jobs.values())
    final_jobs.sort(key=lambda j: j.get("created") or "", reverse=True)

    # 3. Send report (stateless mode: no seen-jobs persistence)
    send_report(final_jobs, config)

    logger.info("=== Job Hunt done — %s job(s) reported ===", len(final_jobs))


def _get_active_roles(config: dict) -> list[dict]:
    role_entries = config.get("roles", [])
    if isinstance(role_entries, list) and role_entries:
        active = [r for r in role_entries if isinstance(r, dict) and r.get("enabled", True)]
        return sorted(active, key=lambda r: r.get("priority", 999))

    # Backward-compatible single role from legacy config.
    return [
        {
            "name": "Default",
            "enabled": True,
            "priority": 1,
            "search": deepcopy(config.get("search", {})),
            "filters": deepcopy(config.get("filters", {})),
            "ai": {
                "target_roles": config.get("ai", {}).get("target_roles", []),
                "must_have_keywords": config.get("ai", {}).get("must_have_keywords", []),
                "nice_to_have_keywords": config.get("ai", {}).get("nice_to_have_keywords", []),
                "avoid_keywords": config.get("ai", {}).get("avoid_keywords", []),
            },
        }
    ]


def _build_role_config(config: dict, role: dict) -> dict:
    role_config = deepcopy(config)
    defaults = config.get("defaults", {})

    role_config["search"] = _merge_dicts(defaults.get("search", {}), role.get("search", {}))
    role_config["filters"] = _merge_dicts(defaults.get("filters", {}), role.get("filters", {}))

    ai_base = _merge_dicts(defaults.get("ai", {}), config.get("ai", {}))
    role_ai = _merge_dicts(ai_base, role.get("ai", {}))
    limits = role.get("limits", {})
    if "max_jobs_to_evaluate" in limits:
        role_ai["max_jobs_to_evaluate"] = limits["max_jobs_to_evaluate"]
    if "top_k" in limits:
        role_ai["top_k"] = limits["top_k"]

    role_config["ai"] = role_ai
    return role_config


def _merge_job_for_role(merged_jobs: dict[str, dict], job: dict, role_name: str) -> None:
    job_id = job.get("id")
    if not job_id:
        return

    if job_id not in merged_jobs:
        item = dict(job)
        item["matched_roles"] = [role_name]
        item["matched_role_count"] = 1
        merged_jobs[job_id] = item
        return

    existing = merged_jobs[job_id]
    matched_roles = existing.setdefault("matched_roles", [])
    if role_name not in matched_roles:
        matched_roles.append(role_name)
    existing["matched_role_count"] = len(matched_roles)

    existing_score = existing.get("ai_score")
    new_score = job.get("ai_score")
    if new_score is not None and (existing_score is None or new_score > existing_score):
        existing["ai_score"] = new_score
        if "ai_reason" in job:
            existing["ai_reason"] = job["ai_reason"]


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(override, dict):
        return merged

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        logger.info("Storage is disabled in stateless mode; --reset is a no-op")
    else:
        run()
