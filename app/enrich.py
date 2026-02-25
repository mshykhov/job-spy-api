import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

logger = logging.getLogger(__name__)

LINKEDIN_JOB_URL = "https://www.linkedin.com/jobs/view/{job_id}"
REQUEST_TIMEOUT = 30


@dataclass
class ProxyConfig:
    url: str
    fingerprint: dict[str, str] = field(default_factory=dict)

    @property
    def proxy_url(self) -> str:
        raw = self.url.removeprefix("http://").removeprefix("https://")
        return f"http://{raw}"


@dataclass
class EnrichRequest:
    jobs: list[dict]
    proxies: list[dict]
    delay_min: int = 7
    delay_max: int = 15


@dataclass
class EnrichResult:
    job_id: str
    url: str
    status: str
    data: dict | None = None
    error: str | None = None


@dataclass
class EnrichStats:
    total: int = 0
    success: int = 0
    no_data: int = 0
    not_found: int = 0
    timeout: int = 0
    error: int = 0
    skipped: int = 0
    proxies_alive: int = 0
    proxies_dead: int = 0
    duration_seconds: float = 0


async def enrich_jobs(request: EnrichRequest) -> dict:
    start_time = time.monotonic()

    proxies = [ProxyConfig(url=p["url"], fingerprint=p.get("fingerprint", {})) for p in request.proxies]
    if not proxies:
        return _empty_response(request.jobs, "No proxies provided")

    queue: asyncio.Queue[dict] = asyncio.Queue()
    for job in request.jobs:
        await queue.put(job)

    results: list[EnrichResult] = []
    results_lock = asyncio.Lock()
    alive_count = asyncio.Semaphore(len(proxies))
    dead_proxies: set[int] = set()

    async def worker(proxy_idx: int, proxy: ProxyConfig):
        async with httpx.AsyncClient(
            proxy=proxy.proxy_url,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
        ) as client:
            while True:
                try:
                    job = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                job_id = job.get("job_id", "")
                url = job.get("url", LINKEDIN_JOB_URL.format(job_id=job_id))

                try:
                    result = await _fetch_job_detail(client, url, job_id, proxy.fingerprint)
                    async with results_lock:
                        results.append(result)

                    if result.status == "success":
                        delay = random.uniform(request.delay_min, request.delay_max)
                        await asyncio.sleep(delay)
                    else:
                        await asyncio.sleep(2)

                except _ProxyDeadError as e:
                    logger.warning("Proxy %d dead: %s. Re-queuing job %s", proxy_idx, e, job_id)
                    await queue.put(job)
                    dead_proxies.add(proxy_idx)
                    alive_count.acquire()
                    return

                except Exception as e:
                    logger.error("Unexpected error for job %s on proxy %d: %s", job_id, proxy_idx, e)
                    async with results_lock:
                        results.append(EnrichResult(job_id=job_id, url=url, status="error", error=str(e)))

    tasks = [asyncio.create_task(worker(i, p)) for i, p in enumerate(proxies)]
    await asyncio.gather(*tasks)

    skipped_jobs = []
    while not queue.empty():
        job = queue.get_nowait()
        skipped_jobs.append(
            EnrichResult(
                job_id=job.get("job_id", ""),
                url=job.get("url", ""),
                status="skipped",
                error="All proxies exhausted",
            )
        )
    results.extend(skipped_jobs)

    stats = _compute_stats(results, len(proxies), dead_proxies, time.monotonic() - start_time)

    return {
        "results": [_result_to_dict(r) for r in results],
        "stats": stats.__dict__,
    }


class _ProxyDeadError(Exception):
    pass


async def _fetch_job_detail(
    client: httpx.AsyncClient,
    url: str,
    job_id: str,
    fingerprint: dict[str, str],
) -> EnrichResult:
    headers = _build_headers(fingerprint)

    try:
        response = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        return EnrichResult(job_id=job_id, url=url, status="timeout", error="Request timed out")
    except httpx.ProxyError as e:
        raise _ProxyDeadError(f"Proxy error: {e}")
    except httpx.ConnectError as e:
        raise _ProxyDeadError(f"Connection error: {e}")

    if response.status_code == 429:
        raise _ProxyDeadError("429 Too Many Requests")

    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get("location", "")
        if "signup" in location or "login" in location or "authwall" in location:
            raise _ProxyDeadError(f"Auth wall redirect: {location}")

    if response.status_code == 404:
        return EnrichResult(job_id=job_id, url=url, status="not_found", error="Job not found")

    if response.status_code >= 400:
        return EnrichResult(job_id=job_id, url=url, status="error", error=f"HTTP {response.status_code}")

    data = _parse_job_page(response.text)
    if not data:
        return EnrichResult(job_id=job_id, url=url, status="no_data", error="Could not parse job page")

    return EnrichResult(job_id=job_id, url=url, status="success", data=data)


def _parse_job_page(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    desc_el = soup.find("div", class_="show-more-less-html__markup")
    if not desc_el:
        return None

    description_html = str(desc_el)
    description = md(description_html).strip()

    criteria = {}
    criteria_items = soup.find_all("li", class_="description__job-criteria-item")
    for item in criteria_items:
        header = item.find("h3")
        value = item.find("span", class_="description__job-criteria-text")
        if header and value:
            key = header.get_text(strip=True).lower().replace(" ", "_")
            criteria[key] = value.get_text(strip=True)

    salary = None
    salary_el = soup.find("div", class_="salary")
    if salary_el:
        salary = salary_el.get_text(strip=True)

    applicants = None
    applicants_el = soup.find("figcaption", class_="num-applicants__caption")
    if applicants_el:
        applicants = applicants_el.get_text(strip=True)

    apply_url = None
    apply_el = soup.find("code", id="applyUrl")
    if apply_el:
        match = re.search(r'(?<=\?url=)[^"]+', apply_el.get_text())
        if match:
            apply_url = match.group(0)

    return {
        "description": description,
        "description_html": description_html,
        "seniority": criteria.get("seniority_level"),
        "employment_type": criteria.get("employment_type"),
        "job_function": criteria.get("job_function"),
        "industries": criteria.get("industries"),
        "applicants": applicants,
        "salary": salary,
        "apply_url": apply_url,
    }


def _build_headers(fingerprint: dict[str, str]) -> dict[str, str]:
    base = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if fingerprint:
        base.update(fingerprint)
    else:
        base["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        base["Accept-Language"] = "en-US,en;q=0.9"
    return base


def _compute_stats(
    results: list[EnrichResult],
    total_proxies: int,
    dead_proxies: set[int],
    duration: float,
) -> EnrichStats:
    stats = EnrichStats(
        total=len(results),
        duration_seconds=round(duration, 1),
        proxies_alive=total_proxies - len(dead_proxies),
        proxies_dead=len(dead_proxies),
    )
    for r in results:
        match r.status:
            case "success":
                stats.success += 1
            case "no_data":
                stats.no_data += 1
            case "not_found":
                stats.not_found += 1
            case "timeout":
                stats.timeout += 1
            case "error":
                stats.error += 1
            case "skipped":
                stats.skipped += 1
    return stats


def _result_to_dict(r: EnrichResult) -> dict:
    d = {"job_id": r.job_id, "url": r.url, "status": r.status}
    if r.data:
        d["data"] = r.data
    if r.error:
        d["error"] = r.error
    return d


def _empty_response(jobs: list[dict], error: str) -> dict:
    results = [
        _result_to_dict(EnrichResult(job_id=j.get("job_id", ""), url=j.get("url", ""), status="skipped", error=error))
        for j in jobs
    ]
    return {
        "results": results,
        "stats": EnrichStats(total=len(jobs), skipped=len(jobs)).__dict__,
    }
