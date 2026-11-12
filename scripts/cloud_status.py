"""Inspect this repository's cloud rollout without displaying credentials."""
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

git = str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe")
env = os.environ.copy()
env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
result = subprocess.run([git, "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                        text=True, capture_output=True, check=True, timeout=20, env=env)
credentials = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
session = requests.Session()
session.headers.update({"Authorization": "Bearer " + credentials["password"],
                        "Accept": "application/vnd.github+json"})
base = "https://api.github.com/repos/chepkemboiedel-sudo/WNBA-Predictions"

if "--cancel-duplicate" in sys.argv:
    response = session.post(base + "/actions/runs/40568900041/cancel", timeout=30)
    print("Cancel duplicate HTTP", response.status_code)
    response.raise_for_status()

response = session.get(base + "/actions/workflows/daily-refresh.yml", timeout=30)
if response.ok:
    workflow = response.json()
    print(json.dumps({k: workflow[k] for k in ("id", "name", "path", "state", "html_url")}))

if "--dispatch" in sys.argv:
    response = session.post(base + "/actions/workflows/daily-refresh.yml/dispatches",
                            json={"ref": "main"}, timeout=30)
    print("Dispatch HTTP", response.status_code)
    response.raise_for_status()

response = session.get(base + "/actions/runs?per_page=5", timeout=30)
response.raise_for_status()
for run in response.json().get("workflow_runs", []):
    print(json.dumps({k: run[k] for k in ("id", "name", "head_sha", "event", "status", "conclusion", "html_url")}))
response = session.get(base + "/deployments?per_page=4", timeout=30)
response.raise_for_status()
for deployment in response.json():
    response = session.get(deployment["statuses_url"], timeout=30)
    response.raise_for_status()
    statuses = response.json()
    status = statuses[0] if statuses else {}
    print(json.dumps({"deployment_id": deployment["id"], "sha": deployment["sha"],
                      "environment": deployment["environment"],
                      **{k: status.get(k) for k in ("state", "description", "environment_url")}}))
