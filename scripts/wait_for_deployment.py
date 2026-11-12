"""Verify the existing Vercel integration deployed the refreshed Git commit."""
import os
import time

import requests


def main():
    repository = os.environ["GH_REPOSITORY"]
    commit = os.environ["DEPLOY_COMMIT"]
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                            "Accept": "application/vnd.github+json"})
    url = f"https://api.github.com/repos/{repository}/commits/{commit}/status"
    for _ in range(40):
        response = session.get(url, timeout=30)
        response.raise_for_status()
        statuses = [s for s in response.json()["statuses"]
                    if s["context"].lower().startswith("vercel")]
        failed = [s for s in statuses if s["state"] in ("failure", "error")]
        if failed:
            raise RuntimeError("Vercel deployment failed: " + "; ".join(
                f"{s['context']}: {s.get('target_url', '')}" for s in failed))
        if statuses and all(s["state"] == "success" for s in statuses):
            print("Vercel published refreshed commit " + commit)
            return
        time.sleep(15)
    raise TimeoutError("No successful Vercel deployment appeared within ten minutes.")


if __name__ == "__main__":
    main()
