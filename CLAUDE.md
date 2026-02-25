# job-hunter-scraper

**TL;DR:** FastAPI wrapper around python-jobspy for [Job Hunter](https://github.com/mshykhov/job-hunter). Scrapes job vacancies from LinkedIn, Indeed, Google Jobs, and other platforms.

> **Stack**: Python 3.12, FastAPI, python-jobspy, Docker

---

## Portfolio Project

**Public repository.** Everything must be clean and professional.

### Standards
- **English only** — README, commits, CLAUDE.md, code, comments
- **Meaningful commits** — conventional commits
- **No junk** — no test/temporary code in master
- **No AI mentions** in commits

---

## Architecture

```
FastAPI (app/main.py)
  └── python-jobspy (scrape_jobs)
        ├── LinkedIn scraper
        ├── Indeed scraper
        ├── Google Jobs scraper
        └── ... other platforms
```

Single endpoint: `GET /jobs` — accepts search params, returns JSON array of job postings.

### Integration with Job Hunter

```
n8n → GET /proxies (Kotlin API) → proxy URL
n8n → GET /jobs?site=linkedin&proxies=... (this service) → job list
n8n → POST /jobs/ingest (Kotlin API) → persist
```

---

## Structure

```
job-hunter-scraper/
├── app/
│   ├── __init__.py
│   └── main.py              # FastAPI application
├── .github/workflows/
│   └── release.yml           # Build & push Docker image on tag
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## Key Details

- **Proxies**: Passed via `proxies` query param or `DEFAULT_PROXIES` env var. Strips `http://` prefix automatically (JobSpy expects `user:pass@host:port` format)
- **NaN handling**: pandas NaN values converted to None for valid JSON
- **Error handling**: ValueError → 400, other exceptions → 500 with logging
- **LinkedIn**: Requires proxies. Rate-limited. Max ~1000 results per query. `linkedin_fetch_description=true` for full descriptions (O(n) extra requests)
- **Release**: Push `v*` tag → GitHub Actions builds Docker image → pushes to `ghcr.io/mshykhov/job-hunter-scraper`
