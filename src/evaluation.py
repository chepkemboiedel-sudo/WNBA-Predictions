"""Daily append-only historical evaluation and an independent pregame trial."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import backtest_availability as B
import collect_historical_injuries as reports
import availability as A
import simulate as S
from app_data import atomic_json

ET=ZoneInfo("America/New_York")


def stamp(now):
    return now.isoformat().replace("+00:00","Z")


def settle(ledger,games,now):
    """Set outcomes once; never alter a recorded pregame probability."""
    result=copy.deepcopy(ledger)
    completed={str(r.game_id):r for r in games.itertuples()}
    for row in result["predictions"]:
        if row.get("status")!="pending" or row["game_id"] not in completed:
            continue
        tip=A.utc(row["tip"])
        if not A.utc(row["locked_at"])<tip or now<tip:
            continue
        game=completed[row["game_id"]]
        if (game.home_team,game.away_team)!=(row["home"],row["away"]):
            row["notice"]="Completed matchup differs from the recorded schedule; not scored."
            continue
        row.update(status="settled",home_win=int(game.home_win),settled_at=stamp(now),is_playoff=bool(game.is_playoff),local_date=tip.astimezone(ET).date().isoformat())
    return result


def capture(ledger,games,snapshot,model,now,model_hash,clock=None):
    """Freeze the first paired forecast in the 24 hours before scheduled tip."""
    result=copy.deepcopy(ledger)
    fetched=A.utc(snapshot.get("fetched_at"))
    if not snapshot.get("apply_adjustments") or not fetched or not timedelta(0)<=now-fetched<=timedelta(hours=2):
        result["capture_note"]="No fresh, verified player snapshot for a prospective prediction."
        return result
    recorded={r["game_id"] for r in result["predictions"]}
    completed=set(games.game_id.astype(str))
    schedule=snapshot.get("next_games",{})
    for home,event in sorted(schedule.items()):
        if not event.get("home"):
            continue
        gid=str(event["event_id"])
        away=event["opponent"]
        opposite=schedule.get(away,{})
        tip=A.utc(event["date"])
        if gid in recorded or gid in completed or not tip or not timedelta(0)<tip-now<=timedelta(hours=24):
            continue
        if str(opposite.get("event_id"))!=gid or opposite.get("opponent")!=home or opposite.get("home") is not False:
            continue
        # This project models 2026. Do not silently score a new season with it.
        if tip.year!=2026 or games.date.max().date()>now.date():
            continue
        feats=S.current_team_features(games,[home,away])
        baseline=S.build_prob_matrix(model,feats,[home,away])
        optional=S.build_prob_matrix(model,feats,[home,away],snapshot)
        baseline_p=float(baseline[(home,away,True)])
        adjusted_p=float(optional.get((home,away,True,"next"),optional[(home,away,True)]))
        locked=clock() if clock else now
        if tip-locked<timedelta(minutes=5):
            continue
        evidence={"fetched_at":snapshot["fetched_at"],"source_timestamp":snapshot.get("source_timestamp"),"model":snapshot.get("model"),
                  "teams":{t:snapshot.get("teams",{}).get(t,{}) for t in (home,away)},"scheduled_game":event}
        row={"game_id":gid,"tip":event["date"],"locked_at":stamp(locked),"status":"pending","home":home,"away":away,
             "is_playoff":bool(event.get("is_playoff")),"local_date":tip.astimezone(ET).date().isoformat(),
             "p_baseline":baseline_p,"p_adjusted":adjusted_p,"model_version":"score-logistic-v1+"+A.MODEL_VERSION,
             "model_sha256":model_hash,"data_through":str(games.date.max().date()),"snapshot":evidence}
        result["predictions"].append(row)
        recorded.add(gid)
    result["capture_note"]="First paired predictions are frozen 5 minutes to 24 hours before tip; late games are never backfilled as prospective."
    return result


def trial_frame(ledger):
    rows=[r for r in ledger["predictions"] if r["status"]=="settled"]
    return pd.DataFrame(rows,columns=["game_id","local_date","home","away","home_win","p_baseline","p_adjusted","locked_at","tip","settled_at","is_playoff"])


def checkpoint(progress,summary,frame,trials,now):
    signature=hashlib.sha256(json.dumps({"historical":frame[["game_id","home_win","p_baseline","p_adjusted"]].to_dict("records"),
                                       "prospective":trials[["game_id","home_win","p_baseline","p_adjusted"]].to_dict("records")},sort_keys=True).encode()).hexdigest()
    result=copy.deepcopy(progress)
    if not result["checkpoints"] or result["checkpoints"][-1]["signature"]!=signature:
        groups={key:{"n":group["n"],**({"accuracy_delta":group["metrics"]["accuracy"]["delta"],"log_loss_delta":group["metrics"]["log_loss"]["delta"],"brier_delta":group["metrics"]["brier"]["delta"]} if group["n"] else {})} for key,group in summary["groups"].items()}
        result["checkpoints"].append({"at":stamp(now),"signature":signature,"groups":groups})
    return result


def publish_files(changes):
    """Rollback a failed promotion so the published evaluation remains coherent."""
    old={path:path.read_bytes() if path.exists() else None for path in changes}
    try:
        for path,content in changes.items():
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_name(path.name+".tmp")
            temporary.write_bytes(content)
            os.replace(temporary,path)
    except Exception:
        for path,content in old.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise


def update(*,fetch_reports=True,now=None):
    realtime=now is None
    now=now or datetime.now(timezone.utc)
    output=ROOT/"outputs/availability_backtest"
    data=ROOT/"data/backtests"
    status_path=output/"auto_status.json"
    previous_status=json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    try:
        data.mkdir(parents=True,exist_ok=True)
        for name,source in (("initial_results.json","results.json"),("initial_predictions.csv","predictions.csv")):
            target=data/name
            if not target.exists():
                target.write_bytes((output/source).read_bytes())
        initial=pd.read_csv(data/"initial_predictions.csv",dtype={"game_id":str},float_precision="round_trip")
        ledger_path=data/"prospective_predictions.json"
        ledger=json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {"version":1,"started_at":stamp(now),"predictions":[]}
        progress_path=output/"progress.json"
        progress=json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else {"version":1,"started_at":ledger["started_at"],"checkpoints":[]}
        if fetch_reports:
            reports.refresh_manifest(now=now)
        games=pd.read_csv(ROOT/"data/all_games.csv",dtype={"game_id":str},parse_dates=["date"])
        ledger=settle(ledger,games,now)
        snapshot=A.load_snapshot(now=now)
        bundle=ROOT/"data/models.joblib"
        ledger=capture(ledger,games,snapshot,joblib.load(bundle)["logistic"],now,hashlib.sha256(bundle.read_bytes()).hexdigest(),clock=(lambda:datetime.now(timezone.utc)) if realtime else None)
        # Persist the prediction journal before any lengthy retrospective fitting.
        # A later evaluation failure must not turn a pregame capture into hindsight.
        atomic_json(ledger_path,ledger)
        trials=trial_frame(ledger)
        temporary_root=ROOT/"tmp"
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="evaluation-",dir=temporary_root) as directory:
            stage=Path(directory)
            for name in ("results.json","predictions.csv","REPORT.md","comparison.png"):
                shutil.copyfile(output/name,stage/name)
            old_count=len(pd.read_csv(output/"predictions.csv"))
            summary,frame=B.run(append_only=True,destination=stage)
            new_rows=frame[~frame.game_id.isin(set(initial.game_id))]
            summary["groups"]["initial_study"]=B.score(initial[initial.report_covered])
            summary["groups"]["newly_evaluated"]=B.score(new_rows[new_rows.report_covered])
            summary["groups"]["prospective"]=B.score(trials)
            progress=checkpoint(progress,summary,frame,trials,now)
            pending=sum(r["status"]=="pending" for r in ledger["predictions"])
            status={"status":"ok","started_at":ledger["started_at"],"last_checked_at":stamp(now),"last_success_at":stamp(now),
                    "last_changed_at":progress["checkpoints"][-1]["at"],"new_games_this_run":len(frame)-old_count,
                    "historical_new_games":len(new_rows),"prospective_scored":len(trials),"prospective_pending":pending,
                    "capture_note":ledger.get("capture_note"),"schedule_label":"Daily at 7:00 a.m. Pacific",
                    "message":"Automatic evaluation checked successfully. Existing predictions are retained; new completed games are added once."}
            atomic_json(stage/"results.json",summary)
            atomic_json(stage/"progress.json",progress)
            atomic_json(stage/"auto_status.json",status)
            trials.to_csv(stage/"prospective.csv",index=False)
            # Keep the original methodology and append live monitoring provenance.
            methodology=(stage/"REPORT.md").read_text(encoding="utf-8").split("\n## Automatic monitoring")[0]
            methodology+=f"\n## Automatic monitoring\n\nChecked {stamp(now)}. Historical predictions are append-only. The initial study is frozen separately; {len(new_rows)} later completed games have been evaluated. New archived-report rows are retrospective walk-forward evaluations, not prospective forecasts.\n\nThe separate prospective trial freezes the first paired production game prediction within 24 hours before scheduled tip, using a player snapshot fetched within two hours. Captured probabilities, model hash, and relevant roster/injury evidence are stored before outcomes. Missing pregame captures are never backfilled. There are {len(trials)} scored and {pending} pending predictions. Daily 7 a.m. Pacific sampling may miss early games or last-minute injury updates. This trial uses fixed regular-season form, while the historical test uses pregame running form. Their results must not be pooled as one experiment.\n\nCheckpoints are added only when scored evidence changes. Repeated daily checks do not count as new games or independent significance tests. The initial one-point trend is a starting checkpoint, not a historical performance curve. Score-only remains default; no statistical threshold automatically promotes injuries.\n"
            (stage/"REPORT.md").write_text(methodology,encoding="utf-8")
            changes={output/p.name:p.read_bytes() for p in stage.iterdir() if p.is_file()}
            changes[ledger_path]=(json.dumps(ledger,indent=2,ensure_ascii=False)+"\n").encode("utf-8")
            publish_files(changes)
        print(f"  Evaluation: {len(frame)} historical games, {len(trials)} prospective scored, {pending} pending",flush=True)
        return status
    except Exception as error:
        status={**previous_status,"status":"failed","last_checked_at":stamp(now),"message":"Evaluation update failed; showing the last successful comparison.","error_type":type(error).__name__}
        atomic_json(status_path,status)
        print(f"  Evaluation update failed ({type(error).__name__}: {error}); retained prior results",flush=True)
        return status


if __name__=="__main__":
    update(fetch_reports="--offline" not in sys.argv)
