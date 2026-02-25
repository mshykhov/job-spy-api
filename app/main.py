import logging
import os
import tomllib
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from jobspy import scrape_jobs
from pydantic import BaseModel

from app.enrich import EnrichRequest as EnrichReq
from app.enrich import enrich_jobs


def _read_version() -> str:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if pyproject.exists():
        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    return "0.0.0"


app = FastAPI(title="job-spy-api", version=_read_version())
logger = logging.getLogger(__name__)

DEFAULT_PROXIES = os.getenv("DEFAULT_PROXIES", "")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/jobs")
def search_jobs(
    site: str = Query(..., description="Comma-separated: linkedin,indeed,google,glassdoor,zip_recruiter,bayt,bdjobs"),
    search_term: str | None = Query(None),
    google_search_term: str | None = Query(None, description="Search term for Google Jobs only"),
    location: str | None = Query(None),
    distance: int | None = Query(None, ge=1, description="In miles, default 50"),
    job_type: str | None = Query(None, description="fulltime, parttime, internship, contract"),
    proxies: str | None = Query(None, description="Comma-separated: user:pass@host:port"),
    is_remote: bool = Query(False),
    results_wanted: int = Query(15, ge=1, le=200),
    easy_apply: bool | None = Query(None, description="Filter for jobs hosted on the job board site"),
    description_format: str = Query("markdown", description="markdown or html"),
    offset: int | None = Query(None, ge=0, description="Start search from offset (e.g. 25)"),
    hours_old: int | None = Query(None, ge=1, description="Filter by hours since posted"),
    verbose: int = Query(2, ge=0, le=2, description="0=errors, 1=warnings, 2=all"),
    linkedin_fetch_description: bool = Query(False, description="Fetch full description for LinkedIn (O(n) extra requests)"),
    linkedin_company_ids: str | None = Query(None, description="Comma-separated LinkedIn company IDs"),
    country_indeed: str = Query("usa", description="Country for Indeed & Glassdoor"),
    enforce_annual_salary: bool = Query(False, description="Convert wages to annual salary"),
    ca_cert: str | None = Query(None, description="Path to CA certificate for proxies"),
):
    proxy_list = _parse_proxies(proxies)
    company_ids = _parse_company_ids(linkedin_company_ids)

    kwargs = {
        "site_name": site.split(","),
        "search_term": search_term,
        "google_search_term": google_search_term,
        "location": location,
        "distance": distance,
        "job_type": job_type,
        "proxies": proxy_list,
        "is_remote": is_remote,
        "results_wanted": results_wanted,
        "description_format": description_format,
        "hours_old": hours_old,
        "verbose": verbose,
        "linkedin_fetch_description": linkedin_fetch_description,
        "country_indeed": country_indeed,
        "enforce_annual_salary": enforce_annual_salary,
    }

    if easy_apply is not None:
        kwargs["easy_apply"] = easy_apply
    if offset is not None:
        kwargs["offset"] = offset
    if company_ids is not None:
        kwargs["linkedin_company_ids"] = company_ids
    if ca_cert is not None:
        kwargs["ca_cert"] = ca_cert

    try:
        jobs = scrape_jobs(**kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Scraping failed")
        raise HTTPException(status_code=500, detail=str(e))

    jobs = jobs.where(jobs.notna(), None)
    return jobs.to_dict(orient="records")


class EnrichJobItem(BaseModel):
    url: str
    job_id: str = ""


class EnrichProxyItem(BaseModel):
    url: str
    fingerprint: dict[str, str] = {}


class EnrichRequestBody(BaseModel):
    jobs: list[EnrichJobItem]
    proxies: list[EnrichProxyItem]
    delay_min: int = 7
    delay_max: int = 15


@app.post("/jobs/enrich")
async def enrich(body: EnrichRequestBody):
    request = EnrichReq(
        jobs=[j.model_dump() for j in body.jobs],
        proxies=[p.model_dump() for p in body.proxies],
        delay_min=body.delay_min,
        delay_max=body.delay_max,
    )
    return await enrich_jobs(request)


def _parse_proxies(proxies: str | None) -> list[str] | None:
    raw = proxies or DEFAULT_PROXIES
    if not raw:
        return None
    return [p.removeprefix("http://").removeprefix("https://") for p in raw.split(",")]


def _parse_company_ids(ids: str | None) -> list[int] | None:
    if not ids:
        return None
    return [int(x.strip()) for x in ids.split(",") if x.strip().isdigit()]
