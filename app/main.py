import logging
import os

from fastapi import FastAPI, HTTPException, Query
from jobspy import scrape_jobs

app = FastAPI(title="Job Hunter Scraper", version="0.1.0")
logger = logging.getLogger(__name__)

DEFAULT_PROXIES = os.getenv("DEFAULT_PROXIES", "")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/jobs")
def search_jobs(
    site: str = Query(..., description="Comma-separated: linkedin,indeed,google"),
    search_term: str | None = Query(None),
    location: str | None = Query(None),
    results_wanted: int = Query(15, ge=1, le=200),
    hours_old: int | None = Query(None, ge=1),
    is_remote: bool = Query(False),
    distance: int | None = Query(None, ge=1),
    job_type: str | None = Query(None),
    country_indeed: str = Query("usa"),
    linkedin_fetch_description: bool = Query(False),
    description_format: str = Query("markdown"),
    proxies: str | None = Query(None, description="Comma-separated: user:pass@host:port"),
):
    proxy_list = _parse_proxies(proxies)

    try:
        jobs = scrape_jobs(
            site_name=site.split(","),
            search_term=search_term,
            location=location,
            results_wanted=results_wanted,
            hours_old=hours_old,
            is_remote=is_remote,
            distance=distance,
            job_type=job_type,
            country_indeed=country_indeed,
            linkedin_fetch_description=linkedin_fetch_description,
            description_format=description_format,
            proxies=proxy_list,
            verbose=2,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Scraping failed")
        raise HTTPException(status_code=500, detail=str(e))

    jobs = jobs.where(jobs.notna(), None)
    return jobs.to_dict(orient="records")


def _parse_proxies(proxies: str | None) -> list[str] | None:
    raw = proxies or DEFAULT_PROXIES
    if not raw:
        return None
    return [p.removeprefix("http://").removeprefix("https://") for p in raw.split(",")]
