"""Stage explicit feature files in GitHub's object store; does not publish refs."""
import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/chepkemboiedel-sudo/WNBA-Predictions"
BASE = "767434e4cdf61727748c6d2f331b0ed681297dd9"


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
    if current != BASE and "--sync" not in sys.argv:
        raise RuntimeError("Main changed; inspect the new head before continuing.")
    paths = ["README.md",".github/workflows/daily-refresh.yml","src/backtest_ui.py",
             "src/app_features.py","src/build_site.py","src/availability_ui.py",
             "scripts/verify_forecast.py","tests/test_backtest_browser.cjs","tests/test_backtest_ui.py"]
    for folder in ("public","site"):
        for pattern in ("index.html","teams/*/index.html","backtest/*"):
            paths.extend(path.relative_to(ROOT).as_posix() for path in (ROOT/folder).glob(pattern))

    if "--sync" in sys.argv:
        # Pull only this feature's generated artifacts; source edits stay local.
        artifacts = [p for p in paths if p.startswith(("data/","outputs/","public/","site/")) or p == "SUMMARY.md"]
        tree = request("GET","/git/trees/"+current+"?recursive=1")
        blobs = {row["path"]:row["sha"] for row in tree["tree"] if row["type"] == "blob"}
        def download(path):
            blob = request("GET","/git/blobs/"+blobs[path])
            content = base64.b64decode(blob["content"])
            target = ROOT/path
            target.write_bytes(content)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(download,artifacts))
        print(json.dumps({"synced_artifacts":len(artifacts),"head":current}),flush=True)
        return

    def upload(path):
        content = base64.b64encode((ROOT/path).read_bytes()).decode("ascii")
        blob = request("POST","/git/blobs",json={"encoding":"base64","content":content})
        return {"path":path,"mode":"100644","type":"blob","sha":blob["sha"]}

    print(f"Preparing {len(paths)} feature files ...",flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(upload,paths))
    tree = request("POST","/git/trees",json={"base_tree":request("GET","/git/commits/"+BASE)["tree"]["sha"],"tree":entries})
    result = {"base_sha":BASE,"tree_sha":tree["sha"],"file_count":len(paths)}
    (ROOT/"backtest_ui_tree.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result),flush=True)


if __name__ == "__main__":
    main()
