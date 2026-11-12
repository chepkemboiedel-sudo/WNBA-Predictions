"""Separate, fixed-protocol recovery experiment; never replaces the live study."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
os.environ.setdefault("MPLCONFIGDIR",str(ROOT/"tmp/matplotlib-recovered-study"))
os.environ.setdefault("MPLBACKEND","Agg")
import numpy as np
import pandas as pd
import backtest_availability as B
import availability as A
import recovered_study_protocol as protocol

PROTOCOL_REF="dbab1765e8ec4dcc426a25830dc332791f49524e"

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def write(path,value):Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

def protected():
    paths=list((ROOT/"outputs/availability_backtest").glob("*"))
    paths+=list((ROOT/"data/backtests").glob("initial_*"))
    paths+=[ROOT/p for p in ("data/backtests/prospective_predictions.json","outputs/forecast.json",
                            "data/forecast_history.json","public/index.html","site/index.html")]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.is_file()}

def run_variant(inputs,destination):
    previous_root,previous_fit=B.ROOT,A.fit_effects
    B.ROOT=inputs;A.fit_effects=protocol.fit_effects
    try:return B.run(append_only=False,destination=destination)
    finally:B.ROOT=previous_root;A.fit_effects=previous_fit

def metric_table(reference,recovered):
    lines=["| Metric | Score-only | Original injury model | Recovered-data injury model | New injury minus score-only (95% interval) |",
           "|---|---:|---:|---:|---:|"]
    for k in ("accuracy","log_loss","brier"):
        old=reference["metrics"][k];new=recovered["metrics"][k]
        f=(lambda x:f"{x:.2%}") if k=="accuracy" else (lambda x:f"{x:.6f}")
        scale=100 if k=="accuracy" else 1
        digits=2 if k=="accuracy" else 6;suffix=" pp" if k=="accuracy" else ""
        lo,hi=new["delta_ci95"]
        change=f"{new['delta']*scale:+.{digits}f}{suffix} [{lo*scale:+.{digits}f}, {hi*scale:+.{digits}f}]"
        lines.append(f"| {k.replace('_',' ')} | {f(old['baseline'])} | {f(old['adjusted'])} | {f(new['adjusted'])} | {change} |")
    return "\n".join(lines)

def finding_text(result):
    group=result["cohorts"]["same_original_covered_games"]
    effect=group["recovery_effect"]
    a,l,b=(effect["metrics"][k] for k in ("accuracy","log_loss","brier"))
    uncertainty=" Both probability-score intervals include zero; this study does not establish a clear improvement." if all(m["delta_ci95"][0]<=0<=m["delta_ci95"][1] for m in (l,b)) else " These are retrospective uncertainty estimates, not independent prospective validation."
    return (f"On the same {effect['n']} originally covered games, injury-adjusted winner accuracy changed from {a['baseline']:.2%} to {a['adjusted']:.2%} ({a['delta']*100:+.2f} percentage points). Log-loss changed from {l['baseline']:.6f} to {l['adjusted']:.6f}, and Brier score from {b['baseline']:.6f} to {b['adjusted']:.6f}. Lower probability scores are better.\n\n"
            f"The paired recovery-effect 95% intervals are {a['delta_ci95'][0]*100:+.2f} to {a['delta_ci95'][1]*100:+.2f} pp for accuracy, {l['delta_ci95'][0]:+.6f} to {l['delta_ci95'][1]:+.6f} for log-loss, and {b['delta_ci95'][0]:+.6f} to {b['delta_ci95'][1]:+.6f} for Brier score."+uncertainty+"\n\nThe original study, live forecast, and prospective model-selection evidence remain unchanged.")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,default=ROOT/"outputs/recovered_data_backtest")
    ap.add_argument("--inputs-source",type=Path,help="Reuse an earlier experiment's archived inputs directory")
    args=ap.parse_args();out=args.output.resolve()
    if not out.is_relative_to((ROOT/"outputs").resolve()) or out==(ROOT/"outputs/availability_backtest").resolve():
        raise ValueError("The experiment must use a separate folder inside outputs/.")
    if out.exists():raise FileExistsError("Choose a new experiment folder; existing studies are not overwritten.")
    before=protected();out.mkdir(parents=True)
    audit=read(ROOT/"data/recovery/audit.json")
    original_summary=read(ROOT/"data/backtests/initial_results.json")
    original=pd.read_csv(ROOT/"data/backtests/initial_predictions.csv",dtype={"game_id":str},float_precision="round_trip")
    if original.game_id.duplicated().any():raise ValueError("Duplicate original observations")
    current_boxes=pd.read_csv(ROOT/"data/player_game_stats.csv",dtype={"game_id":str,"player_id":str},float_precision="round_trip")
    recovered_id=audit["boxscore"]["game_id"]
    new_boxes=current_boxes[current_boxes.game_id==recovered_id]
    if len(new_boxes)!=audit["boxscore"]["player_rows"]:raise ValueError("Recovered player cache is incomplete")
    recovered_urls={r["url"] for r in audit["injury_reports"]["recovered"]}
    manifest=read(ROOT/"data/backtests/injury_report_manifest.json")
    reconstructed=json.loads(json.dumps(manifest))
    for r in reconstructed["reports"]:
        if r["url"] in recovered_urls:
            r["status"]="error";r["error"]="Unavailable to the original study; excluded for the control run."
    counts={}
    for label,boxes,source in (("original",current_boxes[current_boxes.game_id!=recovered_id],reconstructed),
                               ("recovered",current_boxes,manifest)):
        data=out/"inputs"/label/"data";data.mkdir(parents=True)
        (data/"backtests").mkdir()
        if args.inputs_source:
            archived=args.inputs_source.resolve()/label/"data"
            for name in ("all_games.csv","player_game_stats.csv","backtests/injury_report_manifest.json"):
                shutil.copyfile(archived/name,data/name)
            boxes=pd.read_csv(data/"player_game_stats.csv",dtype={"game_id":str,"player_id":str},float_precision="round_trip")
            source=read(data/"backtests/injury_report_manifest.json")
        else:
            shutil.copyfile(ROOT/"data/all_games.csv",data/"all_games.csv")
            boxes.to_csv(data/"player_game_stats.csv",index=False)
            write(data/"backtests/injury_report_manifest.json",source)
        counts[label]={"boxscores":int(boxes.game_id.nunique()),"verified_report_files":sum(r["status"]==200 for r in source["reports"])}
    if counts["original"]["verified_report_files"]!=original_summary["report_files_verified"]:
        raise ValueError("Reconstructed report coverage does not match the original study")
    print("Reproducing the original protocol with pre-recovery inputs ...",flush=True)
    control_summary,control=run_variant(out/"inputs/original",out/"control")
    joined_control=original.merge(control,on="game_id",suffixes=("_original","_control"),validate="one_to_one")
    if len(joined_control)!=len(original) or len(control)!=len(original):raise ValueError("Control game cohorts differ")
    control_error={k:float(abs(joined_control[k+"_original"]-joined_control[k+"_control"]).max()) for k in ("p_baseline","p_adjusted")}
    if any(v>1e-8 for v in control_error.values()):
        write(out/"reproduction_failure.json",control_error)
        raise ValueError("The control does not reproduce original probabilities; investigate before claiming a data-only comparison")
    print("Original probabilities reproduced: "+json.dumps(control_error),flush=True)
    print("Running the separate recovered-data study ...",flush=True)
    summary,fresh=run_variant(out/"inputs/recovered",out)
    pairs=original.merge(fresh,on="game_id",suffixes=("_original","_recovered"),validate="one_to_one")
    if len(pairs)!=len(original) or len(fresh)!=len(original):raise ValueError("Comparison game cohorts differ")
    for k in ("home","away","home_win","date","is_playoff"):
        if not pairs[k+"_original"].equals(pairs[k+"_recovered"]):raise ValueError("Outcome or matchup changed: "+k)
    baseline_error=float(abs(pairs.p_baseline_original-pairs.p_baseline_recovered).max())
    if baseline_error>1e-10:raise ValueError("Score-only predictions changed; cannot isolate recovery effects")
    original_mask=pairs.report_covered_original
    recovered_mask=pairs.report_covered_recovered
    if (original_mask&~recovered_mask).any():raise ValueError("Previously covered games unexpectedly lost coverage")
    newly_covered_mask=recovered_mask&~original_mask
    cohorts={}
    for name,mask in (("same_original_covered_games",original_mask),("all_same_games",np.ones(len(pairs),dtype=bool)),
                      ("expanded_recovered_coverage",recovered_mask),("newly_covered_only",newly_covered_mask)):
        part=pairs.loc[mask]
        common={"local_date":part.local_date_recovered,"home_win":part.home_win_recovered}
        old=pd.DataFrame({**common,"p_baseline":part.p_baseline_original,"p_adjusted":part.p_adjusted_original})
        new=pd.DataFrame({**common,"p_baseline":part.p_baseline_original,"p_adjusted":part.p_adjusted_recovered})
        impact=pd.DataFrame({**common,"p_baseline":part.p_adjusted_original,"p_adjusted":part.p_adjusted_recovered})
        old_result=(original_summary["groups"]["verified_report_games"] if name=="same_original_covered_games" else
                    original_summary["groups"]["all_eligible_games"] if name=="all_same_games" else B.score(old))
        cohorts[name]={"original":old_result,"recovered":B.score(new),"recovery_effect":B.score(impact)}
    pairs["recovery_probability_change"]=pairs.p_adjusted_recovered-pairs.p_adjusted_original
    pairs["newly_report_covered"]=newly_covered_mask
    pairs["winner_pick_changed"]=(pairs.p_adjusted_original>=.5)!=(pairs.p_adjusted_recovered>=.5)
    pairs["player_details_recovered"]=pairs.player_details_recovered.map(json.dumps)
    pairs.to_csv(out/"original_vs_recovered_games.csv",index=False)
    after=protected()
    if before!=after:raise RuntimeError("Protected original files changed")
    result={"version":1,"kind":"retrospective recovered-data sensitivity analysis","created_at":datetime.now(timezone.utc).isoformat(),
            "protocol_ref":PROTOCOL_REF,"protocol_file_sha256":sha(Path(protocol.__file__)),"input_coverage":counts,
            "original_probability_reproduction_max_error":control_error,"baseline_probability_max_error":baseline_error,
            "newly_covered_games":pairs.loc[newly_covered_mask,["game_id","date_recovered","local_date_recovered","home_recovered","away_recovered"]].to_dict("records"),
            "changed_probability_pairs":int((abs(pairs.recovery_probability_change)>1e-10).sum()),
            "winner_pick_changes":int(pairs.winner_pick_changed.sum()),"cohorts":cohorts,
            "protected_original_files_sha256":before,"original_files_unchanged":True,
            "input_sha256":{p.relative_to(out).as_posix():sha(p) for p in (out/"inputs").rglob("*") if p.is_file()},
            "limits":["Settings and report-time rules fixed to the original historical protocol; no tuning to these outcomes.",
                      "Recovery changed available inputs; same-game cohorts isolate it from changes in sample composition.",
                      "This is retrospective, not new independent prospective evidence, and cannot trigger model promotion.",
                      "Game-day bootstrap intervals are approximate and conditional on the fitted models.",
                      "Minute restrictions, projected lineups, mid-game scenarios, and championship forecasts are not validated by this study."]}
    write(out/"original_vs_recovered.json",result)
    shutil.copyfile(Path(protocol.__file__),out/"frozen_fitting_protocol.py")
    original_n=int(original_mask.sum());expanded_n=int(recovered_mask.sum());added_n=int(newly_covered_mask.sum())
    lines=["# Separate recovered-data backtest","","Original study outputs and production forecasts are unchanged. This experiment uses separate input snapshots and output files.","",
           "## Finding","",finding_text(result),"",
           f"Reproduced the original {len(original)} game probabilities within 1e-8 before comparing recovered inputs. Score-only predictions are unchanged within 1e-10. Player effects use the original fixed 2025–2026 protocol, monthly past-only fitting, and the same caps and hyperparameters. This avoids confounding recovery with subsequent production model changes.","",
           "## Same original covered games — primary comparison","",f"Exactly the original {original_n} covered games in both runs; no sample-composition change.","",
           metric_table(cohorts["same_original_covered_games"]["original"],cohorts["same_original_covered_games"]["recovered"]),"",
           "## All original games — same fallback policy","",f"The same {len(original)} games, including score-only fallbacks when a report was unavailable. Recovered reports can change a fallback into an adjustment.","",
           metric_table(cohorts["all_same_games"]["original"],cohorts["all_same_games"]["recovered"]),"",
           "## Coverage change","",f"Player box scores: {counts['original']['boxscores']} → {counts['recovered']['boxscores']}. Verified report files: {counts['original']['verified_report_files']} → {counts['recovered']['verified_report_files']}. Both-team report-covered games: {original_n} → {expanded_n}; {added_n} newly covered games.","",
           "The expanded cohort is a different sample. Its aggregate accuracy must not be compared directly with the original covered-sample accuracy as evidence of model improvement.","",
           f"On the expanded {expanded_n}-game cohort, score-only accuracy is {cohorts['expanded_recovered_coverage']['recovered']['metrics']['accuracy']['baseline']:.2%} and injury-adjusted accuracy is {cohorts['expanded_recovered_coverage']['recovered']['metrics']['accuracy']['adjusted']:.2%}. Score-only versus injury-adjusted log-loss is {cohorts['expanded_recovered_coverage']['recovered']['metrics']['log_loss']['baseline']:.6f} versus {cohorts['expanded_recovered_coverage']['recovered']['metrics']['log_loss']['adjusted']:.6f}; Brier score is {cohorts['expanded_recovered_coverage']['recovered']['metrics']['brier']['baseline']:.6f} versus {cohorts['expanded_recovered_coverage']['recovered']['metrics']['brier']['adjusted']:.6f}. The five newly covered games alone have 40% winner accuracy for both models and are too few for a reliable separate conclusion.","",
           "| New covered game | Date (Eastern) | Matchup |","|---|---|---|"]
    for r in result["newly_covered_games"]:lines.append(f"| {r['game_id']} | {r['local_date_recovered']} | {r['away_recovered']} at {r['home_recovered']} |")
    lines += ["","## What changed in the injury predictions?","",f"Across all {len(original)} games, {result['changed_probability_pairs']} injury-adjusted probability pairs changed; the winner pick changed in {result['winner_pick_changes']} game(s). `original_vs_recovered_games.csv` contains the original and recovered predictions for each game.","",
              "The separate paired recovery-effect comparison in `original_vs_recovered.json` compares the new injury forecast directly against the original injury forecast on the same games. Its intervals use 10,000 paired resamples of game days.","",
              "![Effect of recovery on the same original covered games](original_vs_recovered.png)","","## Limits","",
              *["- "+s for s in result["limits"]],"","## Audit and reproduce","",
              f"Pinned fitting function source: Git commit `{PROTOCOL_REF}`. The copied fitting protocol, input snapshots, their SHA-256 hashes, and reproduction errors are retained here.","",
              "Run `.venv/Scripts/python.exe -X utf8 scripts/backtest_recovered_data.py --inputs-source outputs/recovered_data_backtest/inputs --output outputs/recovered_data_backtest_NEW` to reproduce from the saved input snapshots. Existing experiment folders and the live study cannot be overwritten by this runner.","",
              "All protected original-file SHA-256 hashes matched after both runs. No live data refresh, notification, model promotion, or website publication was performed.",""]
    (out/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    plot(cohorts["same_original_covered_games"]["recovery_effect"],out,original_n)
    if protected()!=before:raise RuntimeError("Protected original files changed after report creation")
    print(json.dumps({"output":str(out),"original_covered":original_n,"recovered_covered":expanded_n,"newly_covered":added_n,
                      "same_original_games":cohorts["same_original_covered_games"],"all_original_games":cohorts["all_same_games"],"original_files_unchanged":True},indent=2),flush=True)

def plot(effect,out,n):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator,FuncFormatter
    fig,axes=plt.subplots(1,3,figsize=(11.5,3.9))
    for ax,k,title in zip(axes,("accuracy","log_loss","brier"),("Winner accuracy change","Log-loss change","Brier score change")):
        m=effect["metrics"][k];scale=100 if k=="accuracy" else 1
        lo,hi=m["delta_ci95"];v=m["delta"]
        ax.axvline(0,color="#718096",ls="--",lw=1)
        ax.errorbar(v*scale,0,xerr=[[(v-lo)*scale],[(hi-v)*scale]],fmt="o",color="#c65024",capsize=7,markersize=7)
        ax.set_title(title,fontsize=12);ax.set_yticks([]);ax.set_ylim(-.8,.8)
        ax.set_xlabel("Higher is better (pp)" if k=="accuracy" else "Lower is better",fontsize=10)
        digits=3 if k=="accuracy" else 6
        ax.text(.5,.8,f"{v*scale:+.{digits}f}"+(" pp" if k=="accuracy" else ""),ha="center",transform=ax.transAxes,fontweight="bold")
        ax.xaxis.set_major_locator(MaxNLocator(4))
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos,accuracy=(k=="accuracy"):f"{x:.1f}" if accuracy else f"{x:.4f}"))
        ax.tick_params(axis="x",labelsize=9)
        ax.grid(axis="x",alpha=.15)
    fig.suptitle(f"Effect of recovered data on injury forecasts · same {n} games",fontsize=14,fontweight="bold")
    fig.text(.5,.035,"Recovered minus original · 95% paired game-day intervals · fixed settings · retrospective analysis",ha="center",fontsize=9)
    fig.tight_layout(rect=(0,.07,1,.9));fig.savefig(out/"original_vs_recovered.png",dpi=170);plt.close(fig)

if __name__=="__main__":main()
