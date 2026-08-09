#!/usr/bin/env python3
"""Classify GitHub Actions runner billing failures from Check Run annotations."""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
BILLING_PATTERNS = (
    re.compile(r"recent account payments have failed", re.IGNORECASE),
    re.compile(r"spending limit needs to be increased", re.IGNORECASE),
    re.compile(r"job was not started.+billing", re.IGNORECASE),
    re.compile(r"job was not started.+payment", re.IGNORECASE),
)


def api_get(path: str, token: str) -> object:
    request = Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "d4ctech-actions-ci-fallback",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"GitHub API request failed for {path}: {error}") from error


def is_billing_message(message: str) -> bool:
    normalized = " ".join(message.split())
    return any(pattern.search(normalized) for pattern in BILLING_PATTERNS)


def detect_billing_failure(repository: str, run_id: str, token: str) -> bool:
    jobs_page = 1
    while True:
        jobs_payload = api_get(
            f"/repos/{repository}/actions/runs/{run_id}/jobs"
            f"?filter=latest&per_page=100&page={jobs_page}",
            token,
        )
        if not isinstance(jobs_payload, dict) or not isinstance(
            jobs_payload.get("jobs"), list
        ):
            raise RuntimeError("GitHub jobs response did not contain a jobs list")
        jobs = jobs_payload["jobs"]
        for job in jobs:
            if not isinstance(job, dict) or not isinstance(job.get("id"), int):
                continue
            annotations_page = 1
            while True:
                annotations = api_get(
                    f"/repos/{repository}/check-runs/{job['id']}/annotations"
                    f"?per_page=100&page={annotations_page}",
                    token,
                )
                if not isinstance(annotations, list):
                    raise RuntimeError("GitHub annotations response was not a list")
                for annotation in annotations:
                    if not isinstance(annotation, dict):
                        continue
                    text = " ".join(
                        str(annotation.get(field) or "")
                        for field in ("title", "message", "raw_details")
                    )
                    if is_billing_message(text):
                        return True
                if len(annotations) < 100:
                    break
                annotations_page += 1
        if len(jobs) < 100:
            return False
        jobs_page += 1


def main() -> int:
    token = os.environ.get("D4CTECH_GITHUB_TOKEN", "")
    repository = os.environ.get("D4CTECH_REPOSITORY", "")
    run_id = os.environ.get("D4CTECH_RUN_ID", "")
    if not token or not repository or not run_id:
        print("required classifier environment is missing", file=sys.stderr)
        return 2

    billing_failure = detect_billing_failure(repository, run_id, token)
    value = "true" if billing_failure else "false"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"billing_failure={value}\n")
    print(f"GitHub-hosted runner billing failure: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
