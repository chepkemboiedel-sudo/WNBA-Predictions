"""Publish coverage and register independent championship forecasts."""
import json
from datetime import datetime, timedelta, timezone
from app_data import atomic_json


def update(root, games, results, forecast, snapshot):
    now=datetime.now(timezone.utc).isoformat()
    path=root/"data/backtests/title_predictions.json"
    ledger=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version":1,"predictions":[]}
    season=forecast["season"]
    existing={r["season"] for r in ledger["predictions"]}
    # One first pre-playoff observation per season. Current Finals estimates
    # cannot be re-labelled as an untouched season championship prediction.
    tips=[datetime.fromisoformat(e["date"].replace("Z","+00:00")) for e in snapshot.get("next_games",{}).values() if e.get("is_playoff")]
    playoffs_soon=bool(tips) and min(tips)>datetime.now(timezone.utc)+timedelta(minutes=5)
    if season not in existing and forecast["completed_playoff_games"]==0 and playoffs_soon:
        ledger["predictions"].append({"season":season,"locked_at":now,"data_through":forecast["data_through"],
            "status":"pending","model":forecast["probability_model"],
            "player_model_version":snapshot.get("model",{}).get("version"),
            "probabilities":{r.team:float(r.p_champion) for r in results.itertuples()},
            "score_only":{r.team:float(r.p_champion_baseline) for r in results.itertuples()},
            "injury_adjusted":{r.team:float(r.p_champion_availability) for r in results.itertuples()}})
    for row in ledger["predictions"]:
        if row["status"]!="pending" or row["season"]!=season:continue
        for key,score in forecast["observed_series"].items():
            # A seven-game Finals is the only series in the verified format
            # that can reach four wins; provisional future formats not scored.
            if forecast["season_context"]["format_provisional"]:continue
            if max(score["hw"],score["lw"])<4:continue
            winner=key.split('|')[0 if score["hw"]>=4 else 1]
            row.update(status="settled",winner=winner,settled_at=now,
                brier=sum((p-int(t==winner))**2 for t,p in row["probabilities"].items())+int(winner not in row["probabilities"]))
            row["paired_brier"]={name:sum((p-int(t==winner))**2 for t,p in row.get(name,{}).items())+int(winner not in row.get(name,{})) for name in ("score_only","injury_adjusted")}
    atomic_json(path,ledger)
    box=snapshot.get("boxscore_coverage",{})
    manifest=root/"data/backtests/injury_report_manifest.json"
    reports=json.loads(manifest.read_text(encoding="utf-8")).get("reports",[]) if manifest.exists() else []
    value={"version":1,"updated_at":now,"season":forecast["season_context"],"promotion":forecast["promotion"],
           "coverage":{"boxscores":box,"archived_reports_verified":sum(r.get("status")==200 for r in reports),
                       "archived_reports_requested":len(reports),"archived_report_failures":[{"url":r["url"],"status":r["status"]} for r in reports if r.get("status")!=200],
                       "note":"Unknown reports are never counted as healthy. Missing public reports cannot be reconstructed reliably."},
           "championship_evaluation":{"registered_seasons":len(ledger["predictions"]),"completed_seasons":sum(r["status"]=="settled" for r in ledger["predictions"]),
                 "note":"One first pre-playoff forecast per season. Daily Finals snapshots are correlated and are not independent validation. No proven championship improvement is claimed.","predictions":ledger["predictions"]}}
    for folder in ("public","site"):atomic_json(root/folder/"operations.json",value)
    return value

