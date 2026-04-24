import logging

logger = logging.getLogger(__name__)


def apply_filters(jobs: list[dict], filters: dict) -> list[dict]:
    """Return only jobs that pass all configured filters."""
    passed = []
    for job in jobs:
        reason = _reject_reason(job, filters)
        if reason:
            logger.debug(f"Rejected '{job['title']}' at {job['company']}: {reason}")
        else:
            passed.append(job)

    logger.info(f"Filter result: {len(passed)}/{len(jobs)} jobs passed")
    return passed


def _reject_reason(job: dict, filters: dict) -> str | None:
    text = f"{job['title']} {job['description']}".lower()
    title = job["title"].lower()

    # Exclude keywords — checked against title + description
    for kw in filters.get("exclude_keywords", []):
        if kw.lower() in text:
            return f"exclude keyword '{kw}'"

    # Required keywords — ALL must appear in title or description
    for kw in filters.get("required_keywords", []):
        if kw.lower() not in text:
            return f"missing required keyword '{kw}'"

    # Salary filters
    min_sal = filters.get("min_salary", 0)
    if min_sal:
        job_max = job.get("salary_max") or job.get("salary_min")
        if job_max and job_max < min_sal:
            return f"salary {job_max} below minimum {min_sal}"

    max_sal = filters.get("max_salary", 0)
    if max_sal:
        job_min = job.get("salary_min") or job.get("salary_max")
        if job_min and job_min > max_sal:
            return f"salary {job_min} above maximum {max_sal}"

    # Category filter
    categories = filters.get("categories", [])
    if categories and job.get("category"):
        if not any(c.lower() in job["category"].lower() for c in categories):
            return f"category '{job['category']}' not in allowed list"

    return None
