# job-hunter-scraper

Lightweight FastAPI wrapper around [python-jobspy](https://github.com/speedyapply/JobSpy) for scraping job vacancies from multiple platforms.

Part of the [Job Hunter](https://github.com/mshykhov/job-hunter) project.

## Supported Platforms

LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter, Bayt, Naukri, BDJobs

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

## API

### `GET /jobs`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `site` | string | **required** | Comma-separated: `linkedin,indeed,google` |
| `search_term` | string | — | Search query |
| `location` | string | — | Location filter |
| `results_wanted` | int | 15 | Results per site (max 200) |
| `hours_old` | int | — | Filter by age in hours |
| `is_remote` | bool | false | Remote jobs only |
| `distance` | int | — | Radius in miles |
| `job_type` | string | — | `fulltime`, `parttime`, `contract`, `internship` |
| `country_indeed` | string | usa | Country for Indeed/Glassdoor |
| `linkedin_fetch_description` | bool | false | Fetch full LinkedIn descriptions (slower) |
| `description_format` | string | markdown | `markdown`, `html`, `plain` |
| `proxies` | string | — | Comma-separated: `user:pass@host:port` |

### `GET /health`

Returns `{"status": "ok"}`.

## Docker

```bash
docker build -t job-hunter-scraper .
docker run -p 8000:8000 -e DEFAULT_PROXIES=user:pass@host:port job-hunter-scraper
```

## Release

Push a semver tag to trigger Docker image build and push to GHCR:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Image: `ghcr.io/mshykhov/job-hunter-scraper:latest`
