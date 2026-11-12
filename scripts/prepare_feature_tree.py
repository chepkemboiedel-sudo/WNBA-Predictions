"""Stage explicit feature files in GitHub's object store; does not publish refs."""
import base64
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/chepkemboiedel-sudo/WNBA-Predictions"
BASE = "2bf483ab16713ec873d7f45c5db17b4d207e51fe"


def main():
    git = str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe")
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    credential = subprocess.run([git,"credential","fill"],input="protocol=https\nhost=github.com\n\n",
                                text=True,capture_output=True,check=True,timeout=20,env=env)
    secret = dict(line.split("=",1) for line in credential.stdout.splitlines() if "=" in line)["password"]
    headers = {"Authorization":"Bearer " + secret,"Accept":"application/vnd.github+json"}

    def request(method, endpoint, **kwargs):
        response = requests.request(method,API+endpoint,headers=headers,timeout=45,**kwargs)
        if not response.ok:
            raise RuntimeError(f"GitHub {method} {endpoint}: HTTP {response.status_code}")
        return response.json()

    current = request("GET","/git/ref/heads/main")["object"]["sha"]
    if current != BASE:
        raise RuntimeError("Main changed; inspect the new head before continuing.")
    paths = ["README.md","run_all.py","vercel.json",".github/workflows/daily-refresh.yml",
             "src/app_data.py","src/app_features.py","src/build_site.py",
             "scripts/verify_forecast.py","scripts/record_refresh_failure.py",
             "tests/test_app_features.py","tests/test_refresh_polling.cjs","tests/test_health_state.cjs",
             "data/forecast_history.json"]
    for folder in ("public","site"):
        for pattern in ("index.html","refresh_meta.json","refresh_health.json","teams/*/index.html"):
            paths.extend(path.relative_to(ROOT).as_posix() for path in (ROOT/folder).glob(pattern))

    def upload(path):
        content = base64.b64encode((ROOT/path).read_bytes()).decode("ascii")
        blob = request("POST","/git/blobs",json={"encoding":"base64","content":content})
        return {"path":path,"mode":"100644","type":"blob","sha":blob["sha"]}

    print(f"Preparing {len(paths)} feature files ...",flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(upload,paths))
    tree = request("POST","/git/trees",json={"base_tree":request("GET","/git/commits/"+BASE)["tree"]["sha"],"tree":entries})
    result = {"base_sha":BASE,"tree_sha":tree["sha"],"file_count":len(paths)}
    (ROOT/"feature_tree.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result),flush=True)


if __name__ == "__main__":
    main()
