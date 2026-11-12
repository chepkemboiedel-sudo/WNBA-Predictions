"""Upload the explicit app artifacts for the cloud rollout; never publishes a ref."""
import base64
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REPO = "chepkemboiedel-sudo/WNBA-Predictions"
API = f"https://api.github.com/repos/{REPO}"


def main():
    git = shutil.which("git") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe")
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    credential = subprocess.run([git, "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True,
        timeout=20, env=env, check=True)
    values = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
    headers = {"Authorization": "Bearer " + values["password"],
               "Accept": "application/vnd.github+json"}

    def request(method, path, **kwargs):
        response = requests.request(method, API + path, headers=headers, timeout=45, **kwargs)
        if not response.ok:
            raise RuntimeError(f"GitHub {method} {path}: HTTP {response.status_code}")
        return response.json()

    main_sha = request("GET", "/git/ref/heads/main")["object"]["sha"]
    previous_head = request("GET", "/git/ref/heads/deploy-vercel-static-site")["object"]["sha"]
    if previous_head != "427cc1339d93106c1e3f30762910b9d5979297c0":
        raise RuntimeError("Pull request head changed; inspect it before uploading a new tree.")
    base_tree = request("GET", "/git/commits/" + main_sha)["tree"]["sha"]
    paths = ["README.md", "SUMMARY.md", "run_all.py", "requirements.txt", "vercel.json",
             "refresh_schedule.json", ".github/workflows/daily-refresh.yml",
             "scripts/verify_forecast.py", "scripts/wait_for_deployment.py"]
    for pattern in ("src/*.py", "tests/*.py", "tests/*.cjs", "data/*.csv",
                    "data/models.joblib", "data/market_meta.json", "outputs/*.csv",
                    "outputs/forecast.json", "outputs/calibration.png",
                    "outputs/finals_probabilities.png", "outputs/model_vs_market.png",
                    "outputs/shap_*.png", "public/*.html", "public/refresh_meta.json",
                    "site/*.html", "site/refresh_meta.json"):
        paths.extend(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern))
    paths = sorted(set(paths))

    def upload(path):
        data = base64.b64encode((ROOT / path).read_bytes()).decode("ascii")
        blob = request("POST", "/git/blobs", json={"content": data, "encoding": "base64"})
        return {"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]}

    print(f"Preparing {len(paths)} app files from base {main_sha} ...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        elements = list(pool.map(upload, paths))
    tree = request("POST", "/git/trees", json={"base_tree": base_tree, "tree": elements})
    result = {"main_sha": main_sha, "previous_head": previous_head,
              "tree_sha": tree["sha"], "file_count": len(paths)}
    (ROOT / "cloud_tree.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
