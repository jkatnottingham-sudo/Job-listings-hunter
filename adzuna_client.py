import requests
import time
import logging

BASE_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

logger = logging.getLogger(__name__)


def fetch_jobs(config: dict) -> list[dict]:
    """Fetch all jobs from Adzuna matching the configured search terms."""
    adzuna_cfg = config["adzuna"]
    search_cfg = config["search"]
    filters = config["filters"]

    all_jobs = []

    for keyword in search_cfg["keywords"]:
        logger.info(f"Fetching jobs for keyword: '{keyword}'")
        jobs = _fetch_keyword(keyword, adzuna_cfg, search_cfg, filters)
        all_jobs.extend(jobs)
        time.sleep(0.5)  # be polite to the API

    # Deduplicate by job ID within the same fetch run
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        if job["id"] not in seen:
            seen.add(job["id"])
            unique_jobs.append(job)

    logger.info(f"Fetched {len(unique_jobs)} unique jobs across all keywords")
    return unique_jobs


def _fetch_keyword(keyword: str, adzuna_cfg: dict, search_cfg: dict, filters: dict) -> list[dict]:
    jobs = []
    max_pages = adzuna_cfg["max_pages"]
    results_per_page = adzuna_cfg["results_per_page"]

    for page in range(1, max_pages + 1):
        url = BASE_URL.format(country=adzuna_cfg["country"], page=page)
        params = {
            "app_id": adzuna_cfg["app_id"],
            "app_key": adzuna_cfg["app_key"],
            "what": keyword,
            "results_per_page": results_per_page,
            "content-type": "application/json",
        }

        if search_cfg.get("location"):
            params["where"] = search_cfg["location"]

        if filters.get("min_salary"):
            params["salary_min"] = filters["min_salary"]
        if filters.get("max_salary"):
            params["salary_max"] = filters["max_salary"]

        job_type = filters.get("job_type", "")
        if job_type == "full_time":
            params["full_time"] = 1
        elif job_type == "part_time":
            params["part_time"] = 1
        elif job_type == "permanent":
            params["permanent"] = 1
        elif job_type == "contract":
            params["contract"] = 1


        required_keywords = filters.get("required_keywords", [])
        if required_keywords:
            params["what_and"] = " ".join(required_keywords)

        if filters.get("categories"):
            params["category"] = filters["categories"][0]

        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.error(f"API request failed (keyword='{keyword}', page={page}): {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        jobs.extend(_normalise(job) for job in results)

        if len(results) < results_per_page:
            break  # last page

        time.sleep(0.3)

    return jobs


def _normalise(raw: dict) -> dict:
    return {
        "id": raw.get("id", ""),
        "title": raw.get("title", ""),
        "company": raw.get("company", {}).get("display_name", "Unknown"),
        "location": raw.get("location", {}).get("display_name", ""),
        "category": raw.get("category", {}).get("label", ""),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "job_type": raw.get("contract_type", ""),
        "description": raw.get("description", ""),
        "url": raw.get("redirect_url", ""),
        "created": raw.get("created", ""),
    }
