"""Independently count PDF status cells and validate parsed team/matchup pairs."""
import csv
import json
import re
from collections import Counter
from pathlib import Path

import pdfplumber

ROOT=Path(__file__).resolve().parents[1]
ALIASES={"GS":"GSV","NY":"NYL","LV":"LVA","WSH":"WAS","LA":"LAS","PHO":"PHX","POR":"PDX"}


def main():
    names={}
    with (ROOT/"data/all_games.csv").open(newline="",encoding="utf-8") as stream:
        for game in csv.DictReader(stream):
            for side in ("home","away"):
                names[re.sub(r"\s+","",game[side+"_team"])]=ALIASES.get(game[side+"_abbr"],game[side+"_abbr"])
    manifest=json.loads((ROOT/"data/backtests/injury_report_manifest.json").read_text())
    audits=[]
    for report in manifest["reports"]:
        if report["status"]!=200:
            continue
        raw=ROOT/"tmp/pdfs/historical_injuries"/report["url"].rsplit("/",1)[-1]
        status_cells=Counter()
        with pdfplumber.open(raw) as pdf:
            for page in pdf.pages:
                for word in page.extract_words():
                    if 80<word["top"]<530 and 584<word["x0"]<665 and word["text"] in {"Out","Suspended","Doubtful","Questionable","Probable","Available"}:
                        status_cells[word["text"]]+=1
        parsed=Counter(player["status"] for player in report["players"])
        if status_cells!=parsed:
            raise AssertionError((raw.name,"PDF status count differs",dict(status_cells),dict(parsed)))
        for record in report["teams"]+report["players"]:
            if names[re.sub(r"\s+","",record["team"])] not in record["matchup"].split("@"):
                raise AssertionError((raw.name,"Team does not belong to its matchup",record))
        audits.append({"url":report["url"],"statuses":dict(parsed),"passed":True})
    out=ROOT/"outputs/availability_backtest/report_audit.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"reports_checked":len(audits),"all_passed":True,"checks":["independent PDF status-cell counts","team belongs to reported matchup"],"reports":audits},indent=2),encoding="utf-8")
    print(f"Audited {len(audits)} PDFs: status counts and team/matchup assignments passed.")


if __name__=="__main__":
    main()
