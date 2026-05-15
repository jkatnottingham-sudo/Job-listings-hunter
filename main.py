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

        raw_jobs = fetch_jobs(role_cfg)

        filtered_jobs = apply_filters(raw_jobs, role_cfg["primary"]["filters"])

        llm_cfg = role_cfg.get("llm", {})
        ai_mode = llm_cfg.get("mode", "replace")
        if llm_cfg.get("enabled", False):
            ai_input = raw_jobs if ai_mode == "replace" else filtered_jobs
            filtered_jobs = shortlist_jobs_with_ai(ai_input, role_cfg)
            logger.info("Post-LLM result (%s): %s jobs", role_name, len(filtered_jobs))

        for job in filtered_jobs:
            _merge_job_for_role(merged_jobs, job, role_name)

    final_jobs = list(merged_jobs.values())
    final_jobs.sort(key=lambda j: j.get("created") or "", reverse=True)

    send_report(final_jobs, config)

    logger.info("=== Job Hunt done — %s job(s) reported ===", len(final_jobs))


def _get_active_roles(config: dict) -> list[dict]:
    role_entries = config.get("roles", [])
    if isinstance(role_entries, list) and role_entries:
        active = [r for r in role_entries if isinstance(r, dict) and r.get("enabled", True)]
        return sorted(active, key=lambda r: r.get("priority", 999))

    return [
        {
            "name": "Default",
            "enabled": True,
            "priority": 1,
        }
    ]


def _ensure_primary_shape(p: dict | None) -> dict:
    if not isinstance(p, dict):
        return {"source": "adzuna", "search": {}, "filters": {}}
    out = deepcopy(p)
    return {
        "source": out.get("source", "adzuna"),
        "search": deepcopy(out.get("search", {})),
        "filters": deepcopy(out.get("filters", {})),
    }


def _defaults_primary_block(defaults: dict) -> dict:
    if isinstance(defaults.get("primary"), dict):
        return _ensure_primary_shape(defaults["primary"])
    return _ensure_primary_shape(
        {
            "source": "adzuna",
            "search": deepcopy(defaults.get("search", {})),
            "filters": deepcopy(defaults.get("filters", {})),
        }
    )


def _config_has_roles(config: dict) -> bool:
    r = config.get("roles")
    return isinstance(r, list) and len(r) > 0


def _global_primary(config: dict) -> dict:
    """Baseline primary config. With roles, search/filters come from each role only (+ defaults)."""
    d = _defaults_primary_block(config.get("defaults", {}))
    if not _config_has_roles(config):
        d = _merge_dicts(
            d,
            _ensure_primary_shape(
                {
                    "source": "adzuna",
                    "search": config.get("search", {}),
                    "filters": config.get("filters", {}),
                }
            ),
        )
        d = _merge_dicts(d, _ensure_primary_shape(config.get("primary", {})))
        return d

    root_primary = config.get("primary", {})
    if isinstance(root_primary, dict):
        meta_only = {k: v for k, v in root_primary.items() if k not in ("search", "filters")}
        d = _merge_dicts(d, _ensure_primary_shape(meta_only))
    return d


def _role_primary(role: dict, global_primary: dict) -> dict:
    merged = _merge_dicts(global_primary, _ensure_primary_shape(role.get("primary", {})))
    if isinstance(role.get("primary"), dict):
        return merged
    legacy: dict = {}
    if "search" in role:
        legacy["search"] = role["search"]
    if "filters" in role:
        legacy["filters"] = role["filters"]
    if legacy:
        merged = _merge_dicts(merged, _ensure_primary_shape({"source": "adzuna", **legacy}))
    return merged


def _defaults_llm_block(defaults: dict) -> dict:
    if isinstance(defaults.get("llm"), dict):
        return deepcopy(defaults["llm"])
    return deepcopy(defaults.get("ai", {}))


def _global_llm(config: dict) -> dict:
    d = _defaults_llm_block(config.get("defaults", {}))
    d = _merge_dicts(d, deepcopy(config.get("llm", {})))
    d = _merge_dicts(d, deepcopy(config.get("ai", {})))
    return d


def _role_llm(role: dict, global_llm: dict) -> dict:
    d = _merge_dicts(global_llm, deepcopy(role.get("llm", {})))
    d = _merge_dicts(d, deepcopy(role.get("ai", {})))
    limits = role.get("limits", {})
    for key in ("max_jobs_to_evaluate", "top_k"):
        if key in limits:
            d[key] = limits[key]
    return d


def _build_role_config(config: dict, role: dict) -> dict:
    role_config = deepcopy(config)
    gp = _global_primary(config)
    gl = _global_llm(config)
    role_config["primary"] = _role_primary(role, gp)
    role_config["llm"] = _role_llm(role, gl)
    role_config["search"] = role_config["primary"]["search"]
    role_config["filters"] = role_config["primary"]["filters"]
    role_config["ai"] = role_config["llm"]
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


def _dedupe_strings_preserve_order(items: list) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        low = item.lower()
        if low not in seen:
            seen.add(low)
            out.append(item)
    return out


def _merge_search_dicts(base_s: dict, override_s: dict) -> dict:
    out = deepcopy(base_s)
    for k, v in override_s.items():
        if k == "keywords":
            continue
        out[k] = deepcopy(v)
    a = base_s.get("keywords") if isinstance(base_s.get("keywords"), list) else []
    b = override_s.get("keywords") if isinstance(override_s.get("keywords"), list) else []
    if a or b or "keywords" in override_s or "keywords" in base_s:
        out["keywords"] = _dedupe_strings_preserve_order(list(a) + list(b))
    return out


def _merge_job_filter_dicts(base_f: dict, override_f: dict) -> dict:
    """Merge job filter dicts; union exclude_keywords and required_keywords lists."""
    out = deepcopy(base_f)
    for k, v in override_f.items():
        if k in ("exclude_keywords", "required_keywords"):
            continue
        out[k] = deepcopy(v)
    for list_key in ("exclude_keywords", "required_keywords"):
        a = base_f.get(list_key, [])
        b = override_f.get(list_key, [])
        if not isinstance(a, list):
            a = []
        if not isinstance(b, list):
            b = []
        if list_key in override_f or list_key in base_f:
            seen: set[str] = set()
            ordered: list[str] = []
            for item in a + b:
                if not isinstance(item, str):
                    continue
                low = item.lower()
                if low not in seen:
                    seen.add(low)
                    ordered.append(item)
            out[list_key] = ordered
    return out


def _merge_dicts(base: dict, override: dict) -> dict:
    merged = deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(override, dict):
        return merged

    for key, value in override.items():
        if key == "search" and isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_search_dicts(merged[key], value)
        elif key == "filters" and isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_job_filter_dicts(merged[key], value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        logger.info("Storage is disabled in stateless mode; --reset is a no-op")
    else:
        run()
