"""Cache fixed-time official pregame reports for a reproducible injury backtest.

Run with the bundled PDF Python runtime. No current roster or injury feed is used.
"""
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
BASE = "https://ak-static.cms.nba.com/referee/wnba_injury/"
PARSER_VERSION = 3
COMPATIBLE_PARSER_VERSIONS = (2, 3)
NBA_PLACEHOLDER_TEAMS = {"MemphisGrizzlies", "OklahomaCityThunder", "AtlantaHawks", "UtahJazz"}
ABBREVIATIONS={"GS":"GSV","NY":"NYL","LV":"LVA","WSH":"WAS","LA":"LAS","PHO":"PHX","POR":"PDX"}


def wnba_sections(teams, records, known):
    """Keep identifiable WNBA rows; discard only explicit NBA placeholders."""
    normalize=lambda text:re.sub(r"\s+","",text)
    excluded=[t for t in teams if normalize(t["team"]) not in known]
    if any(normalize(t["team"]) not in NBA_PLACEHOLDER_TEAMS or t["submitted"] for t in excluded):
        raise ValueError("Report contains an unrecognized/non-WNBA team")
    if any(normalize(r["team"]) not in known for r in records):
        raise ValueError("Non-WNBA player rows cannot be accepted as placeholders")
    accepted=[t for t in teams if normalize(t["team"]) in known]
    if not accepted:
        raise ValueError("Report has no identifiable WNBA section")
    codes=set(known.values())
    for row in accepted:
        matchup=row["matchup"].split("@")
        if len(matchup)!=2 or not set(matchup).issubset(codes) or known[normalize(row["team"])] not in matchup:
            raise ValueError("WNBA team and matchup disagree")
    return accepted,records,excluded


def parse_report(path):
    import pdfplumber
    records, teams = [], {}
    status_counts=Counter()
    game_date = matchup = team = None
    with pdfplumber.open(path) as pdf:
        header = pdf.pages[0].extract_text()
        stamp = re.search(r"Injury\s*Report:\s*(\d{2}/\d{2}/\d{2})\s*(\d{2}:\d{2})\s*(AM|PM)", header)
        if not stamp:
            raise ValueError("Missing dated report header")
        published = datetime.strptime(" ".join(stamp.groups()), "%m/%d/%y %I:%M %p").replace(tzinfo=ET)
        columns = None
        for page in pdf.pages:
            words = page.extract_words()
            headers = {w["text"].replace(" ", ""): w for w in words if 95 < w["top"] < 130}
            if "GameDate" in headers:
                columns = [headers[name]["x0"] - 1 for name in ("GameDate", "GameTime", "Matchup", "Team", "PlayerName", "CurrentStatus", "Reason")]
            if columns is None:
                raise ValueError("Missing column header")
            for word in words:
                if (125 if "GameDate" in headers else 80)<word["top"]<page.height-65 and columns[5]<=word["x0"]<columns[6] and word["text"] in {"Out","Doubtful","Questionable","Probable","Available","Suspended"}:
                    status_counts[word["text"]]+=1
            lines = {}
            for word in words:
                if not (125 if "GameDate" in headers else 80) < word["top"] < page.height-65:
                    continue
                y = round(word["top"] / 3) * 3
                cells = lines.setdefault(y, [[] for _ in range(7)])
                col = max((i for i, x in enumerate(columns) if word["x0"] >= x), default=0)
                cells[col].append(word["text"])
            for _, cells in sorted(lines.items()):
                cells = [" ".join(cell).strip() for cell in cells]
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", cells[0]):
                    game_date = datetime.strptime(cells[0], "%m/%d/%Y").date().isoformat()
                if "@" in cells[2]:
                    matchup = cells[2].replace(" ", "")
                if cells[3]:
                    team = cells[3]
                if not (game_date and matchup and team):
                    continue
                key = "|".join((game_date, matchup, team))
                if cells[3]:
                    teams.setdefault(key, {"date":game_date,"matchup":matchup,"team":team,"submitted":False})
                reason = cells[6].replace(" ", "").upper()
                if "NOTYETSUBMITTED" in reason:
                    teams[key]["submitted"] = False
                elif cells[4] and cells[5] in {"Out","Doubtful","Questionable","Probable","Available","Suspended"}:
                    teams[key]["submitted"] = True
                    records.append({"date":game_date,"matchup":matchup,"team":team,"player":cells[4],"status":cells[5]})
                elif reason in {"NONE","NOINJURIES","NOREPORTABLEINJURIES"}:
                    teams[key]["submitted"] = True
    if status_counts!=Counter(record["status"] for record in records):
        raise ValueError("Parsed player rows do not match the PDF status cells")
    with (ROOT/"data/all_games.csv").open(encoding="utf-8",newline="") as stream:
        known = {re.sub(r"\s+","",row[side+"_team"]):ABBREVIATIONS.get(row[side+"_abbr"],row[side+"_abbr"])
                 for row in csv.DictReader(stream) for side in ("home","away")}
    accepted,records,excluded=wnba_sections(list(teams.values()),records,known)
    return {"parser_version":PARSER_VERSION,"published_at":published.isoformat(),"teams":accepted,"players":records,
            "excluded_non_wnba_placeholders":excluded}


def collect(day_hour):
    day, hour = day_hour
    suffix = "09_00AM" if hour == 9 else "03_00PM"
    filename = f"Injury-Report_{day}_{suffix}.pdf"
    raw = ROOT/"tmp/pdfs/historical_injuries"/filename
    target = ROOT/"data/backtests/injury_reports"/(filename.removesuffix(".pdf")+".json")
    url = BASE+filename
    if target.exists():
        cached = json.loads(target.read_text(encoding="utf-8"))
        expected=datetime.fromisoformat(day).replace(hour=hour,tzinfo=ET)
        if cached.get("parser_version") in COMPATIBLE_PARSER_VERSIONS and cached.get("url")==url and cached.get("status")==200 and datetime.fromisoformat(cached["published_at"])==expected:
            return cached
    try:
        if not raw.exists():
            try:
                with urlopen(Request(url,headers={"User-Agent":"WNBA forecast research"}),timeout=35) as response:
                    content=response.read()
            except HTTPError as error:
                if error.code in (403,404):
                    return {"url":url,"status":error.code}
                raise
            if not content.startswith(b"%PDF"):
                raise ValueError("Response is not a PDF")
            raw.write_bytes(content)
        result = {"url":url,"status":200,"sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),**parse_report(raw)}
        expected = datetime.fromisoformat(day).replace(hour=hour,tzinfo=ET)
        if datetime.fromisoformat(result["published_at"]) != expected:
            raise ValueError("PDF header differs from requested report time")
        target.write_text(json.dumps(result,indent=2),encoding="utf-8")
        return result
    except Exception as error:
        return {"url":url,"status":"error","error":str(error)}


def refresh_manifest(limit=None, now=None):
    now=now or datetime.now(timezone.utc)
    manifest_path=ROOT/"data/backtests/injury_report_manifest.json"
    previous=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"reports":[]}
    cached={r["url"]:r for r in previous["reports"]}
    slots = set()
    with (ROOT/"data/player_game_stats.csv").open(encoding="utf-8",newline="") as stream:
        for row in csv.DictReader(stream):
            if int(row["season"]) < 2026:
                continue
            tip = datetime.fromisoformat(row["started_at"].replace("Z","+00:00")).astimezone(ET)
            hour = 9 if tip.hour < 16 else 15
            if tip.hour >= hour+1:
                slots.add((tip.date().isoformat(),hour))
    slots = sorted(slots)
    if limit:
        slots=slots[:limit]
    for folder in ("tmp/pdfs/historical_injuries","data/backtests/injury_reports"):
        (ROOT/folder).mkdir(parents=True,exist_ok=True)
    results=[]
    def incremental(slot):
        day,hour=slot
        suffix="09_00AM" if hour==9 else "03_00PM"
        url=BASE+f"Injury-Report_{day}_{suffix}.pdf"
        old=cached.get(url)
        if old and old.get("status")==200 and old.get("parser_version") in COMPATIBLE_PARSER_VERSIONS:
            return old
        recovered=ROOT/"data/backtests/injury_reports"/(url.rsplit("/",1)[-1].replace(".pdf",".json"))
        if recovered.exists():
            candidate=collect(slot)
            if candidate.get("status")==200:
                return {**candidate,"attempted_at":now.isoformat()}
        attempted=datetime.fromisoformat(old["attempted_at"]) if old and old.get("attempted_at") else None
        # Retry recent failures daily and older unavailable reports weekly.
        old_report=(now.date()-datetime.fromisoformat(day).date()).days>7
        if old and attempted and now-attempted<timedelta(days=7 if old_report else 1):
            return old
        return {**collect(slot),"attempted_at":now.isoformat()}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i,result in enumerate(pool.map(incremental,slots),1):
            results.append(result)
            if i%20==0 or i==len(slots):
                print(f"Reports checked {i}/{len(slots)}; parsed {sum(r['status']==200 for r in results)}",flush=True)
    merged={**cached,**{r["url"]:r for r in results}}
    manifest={"policy":"09:00 ET for tips before 16:00 ET; 15:00 ET for later tips; at least one hour before tip. No outcome-dependent report selection.","reports":sorted(merged.values(),key=lambda r:r["url"])}
    temporary=manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    temporary.replace(manifest_path)
    print(json.dumps({"requested":len(slots),"parsed":sum(r["status"]==200 for r in results),"failures":[r for r in results if r["status"]!=200][:3]}),flush=True)
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--limit",type=int)
    refresh_manifest(parser.parse_args().limit)


if __name__=="__main__":
    main()

