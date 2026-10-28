"""Import corroborated source archives without changing any backtest outputs.

Run after probe_missing_coverage.py, with pdfplumber available. Source archives
are validated completely before replacement files are written.
"""
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import recovered_data
import collect_historical_injuries as C

PROTECTED=("data/backtests/initial_results.json","data/backtests/initial_predictions.csv",
           "outputs/availability_backtest/results.json","outputs/availability_backtest/predictions.csv",
           "outputs/availability_backtest/comparison.png")

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    os.replace(temp,path)

def main():
    if (ROOT/"data/recovery/audit.json").exists():
        print("Recovery audit already exists; preserving its original receipt and backtest hashes.")
        return
    protected={name:digest(ROOT/name) for name in PROTECTED}
    probe=ROOT/"tmp/recovery"
    evidence_by_name={r["name"]:r for r in read(probe/"probes.json")["results"]}
    with (ROOT/"data/all_games.csv").open(encoding="utf-8",newline="") as f:
        game=next(r for r in csv.DictReader(f) if r["game_id"]=="401856947")
    game.update(season=int(game["season"]),is_playoff=game["is_playoff"].lower()=="true",
                home_score=int(game["home_score"]),away_score=int(game["away_score"]))
    game=SimpleNamespace(**game)
    with (ROOT/"data/player_game_stats.csv").open(encoding="utf-8",newline="") as f:
        names={r["player_id"]:r["player"] for r in csv.DictReader(f)}
    source=read(probe/"espn_core.json");status=read(probe/"espn_status.json")
    competition=source["competitions"][0]
    if source["id"]!="401856947" or len(competition["competitors"])!=2:raise ValueError("Unexpected ESPN event")
    teams={}
    for t in competition["competitors"]:
        side=t["homeAway"];tid=t["id"]
        roster=read(probe/f"espn_roster_{tid}.json")
        players=[]
        for p in roster["entries"]:
            if p["period"]!=0:raise ValueError("Not a whole-game roster")
            aid=str(p["playerId"])
            if aid not in names:raise ValueError("Missing previously identified ESPN athlete")
            stats={}
            if not p["didNotPlay"]:
                raw=read(probe/f"stats-{tid}-{aid}.json")
                if raw["$ref"]!=p["statistics"]["$ref"] or f"/athletes/{aid}" not in raw["athlete"]["$ref"]:
                    raise ValueError("Athlete statistics identity mismatch")
                values={r["name"]:r["value"] for group in raw["splits"]["categories"] for r in group["stats"]}
                stats={k:values[k] for k in ("minutes","points","rebounds","assists")}
            players.append({"id":aid,"name":names[aid],"game_surname":p["displayName"],
                "didNotPlay":p["didNotPlay"],"statistics":stats})
        teams[side]={"id":tid,"team":getattr(game,side+"_team"),"players":players}
    official=read(probe/"wnba_props.json")["game"]
    official={k:official[k] for k in ("gameId","gameStatus","gameTimeUTC","period","homeTeam","awayTeam")}
    evidence={"version":1,"recovered_at":datetime.now(timezone.utc).isoformat(),
              "espn":{"id":source["id"],"date":source["date"],"completed":status["type"]["completed"],"teams":teams},
              "wnba":official,"sources":[r for r in evidence_by_name.values() if r.get("status")==200 and r["name"] in
                  {"espn_core.json","espn_status.json","espn_roster_19.json","espn_roster_8.json","wnba_box.html"} or r.get("name","").startswith("stats-")],
              "method":"Exact existing ESPN athlete IDs; unique full-name or event-surname match to WNBA rows; identical points/rebounds/assists, rounded ESPN minutes corroborate exact WNBA clocks; complete team totals."}
    rows,identities=recovered_data.validate_boxscore(evidence,game)
    evidence["identities"]=identities
    manifest=read(ROOT/"data/backtests/injury_report_manifest.json")
    before=sum(r["status"]==200 for r in manifest["reports"])
    recovered=[]
    pending=[]
    for old in manifest["reports"]:
        name=Path(old["url"]).name
        p=probe/name
        if old["status"]==200 or not p.exists():continue
        provenance=evidence_by_name.get(name,{})
        if provenance.get("status")!=200 or not p.read_bytes().startswith(b"%PDF"):continue
        result={"url":old["url"],"status":200,"sha256":digest(p),**C.parse_report(p)}
        expected=datetime.strptime(name,"Injury-Report_%Y-%m-%d_%I_%M%p.pdf").replace(tzinfo=C.ET)
        if datetime.fromisoformat(result["published_at"])!=expected:raise ValueError("Recovered report publication time mismatch")
        result["recovered_at"]=evidence["recovered_at"]
        pending.append((old,result,p))
        recovered.append({"url":old["url"],"sha256":result["sha256"],"published_at":result["published_at"],
                          "wnba_player_rows":len(result["players"]),"excluded_nba_placeholder_rows":len(result["excluded_non_wnba_placeholders"])})
    # Validation above is complete before any production input cache changes.
    write(ROOT/"data/recovery/boxscore_401856947.json",evidence)
    for old,result,p in pending:
        old.clear();old.update(result)
        destination=ROOT/"data/recovery/sources"/p.name
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,destination)
        write(ROOT/"data/backtests/injury_reports"/(p.stem+".json"),result)
    write(ROOT/"data/backtests/injury_report_manifest.json",manifest)
    after=sum(r["status"]==200 for r in manifest["reports"])
    audit={"version":1,"recovered_at":evidence["recovered_at"],"boxscore":{"game_id":"401856947","official_game_id":official["gameId"],
              "player_rows":len(rows),"home":game.home_team,"away":game.away_team,"score":[game.home_score,game.away_score],
              "validation":"Both providers agree on player statistics. Individual WNBA minute clocks sum to 200 minutes per team within six seconds of rounding; original clocks are retained.",
              "team_player_minutes":{team:round(sum(r["minutes"] for r in rows if r["team"]==team),6) for team in (game.home_team,game.away_team)},
              "source_url":"https://www.wnba.com/game/min-vs-chi-1022600058/box-score"},
           "injury_reports":{"before":before,"after":after,"requested":len(manifest["reports"]),"recovered":recovered,
               "still_unavailable":[r for r in manifest["reports"] if r["status"]!=200]},
           "recovery_attempts":list(evidence_by_name.values()),"protected_backtest_sha256":protected,
           "backtest_note":"Recovered inputs improve current archive coverage. Original study predictions, numerical results, and frozen initial-study files were not recalculated."}
    if any(digest(ROOT/name)!=sha for name,sha in protected.items()):raise RuntimeError("A protected backtest artifact changed")
    write(ROOT/"data/recovery/audit.json",audit)
    print(json.dumps({"boxscore_player_rows":len(rows),"reports_before":before,"reports_after":after,"recovered_reports":len(recovered),"backtest_unchanged":True}),flush=True)

if __name__=="__main__":main()

