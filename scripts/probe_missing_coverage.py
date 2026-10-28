"""Read-only source recovery probes; production caches are never changed here."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from urllib.request import Request,urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"tmp/recovery"

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((ROOT/"data/backtests/injury_report_manifest.json").read_text(encoding="utf-8"))
    targets=[(Path(r["url"]).name,r["url"]) for r in manifest["reports"] if r["status"]!=200]
    targets += [
        ("espn_summary.json","https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary?event=401856947"),
        ("espn_core.json","https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/events/401856947?lang=en&region=us"),
        ("espn_cdn.json","https://cdn.espn.com/core/wnba/boxscore?xhr=1&gameId=401856947"),
        ("wnba_box.json","https://cdn.wnba.com/static/json/liveData/boxscore/boxscore_1022600058.json"),
        ("nba_box.json","https://cdn.nba.com/static/json/liveData/boxscore/boxscore_1022600058.json"),
        ("wnba_box.html","https://www.wnba.com/game/min-vs-chi-1022600058/box-score"),
        ("wnba_injury.html","https://www.wnba.com/wnba-injury-report"),
        ("espn_roster_19.json","https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/events/401856947/competitions/401856947/competitors/19/roster?lang=en&region=us"),
        ("espn_roster_8.json","https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/events/401856947/competitions/401856947/competitors/8/roster?lang=en&region=us"),
        ("espn_status.json","https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/events/401856947/competitions/401856947/status?lang=en&region=us"),
    ]
    for day in ("2026-07-28","2026-08-23"):
        filename=f"Injury-Report_{day}_03_00PM.pdf"
        targets.extend([
            ("uncached-"+filename,"https://ak-static.cms.nba.com/referee/wnba_injury/"+filename+"?recovery=1"),
            ("alternate-cdn-"+filename,"https://cdn.nba.com/referee/wnba_injury/"+filename),
            ("earlier-"+filename,"https://ak-static.cms.nba.com/referee/wnba_injury/"+filename.replace("03_00PM","02_45PM")),
            ("archive-"+day+".json","https://web.archive.org/cdx/search/cdx?url=ak-static.cms.nba.com/referee/wnba_injury/"+filename+"&output=json&filter=statuscode:200&collapse=digest"),
        ])
    for tid in ("19","8"):
        roster=OUT/f"espn_roster_{tid}.json"
        if roster.exists():
            for p in json.loads(roster.read_text(encoding="utf-8"))["entries"]:
                if p.get("statistics") and p.get("period")==0:
                    targets.append((f"stats-{tid}-{p['playerId']}.json",p["statistics"]["$ref"].replace("http://","https://")))
    def probe(item):
        name,url=item
        try:
            with urlopen(Request(url,headers={"User-Agent":"Mozilla/5.0"}),timeout=30) as response:
                content=response.read()
                row={"name":name,"url":url,"status":response.status,"bytes":len(content),"type":response.headers.get("content-type"),"sha256":hashlib.sha256(content).hexdigest()}
            if row["status"]==200:
                (OUT/name).write_bytes(content)
                if content.startswith(b"%PDF"):
                    import pdfplumber
                    with pdfplumber.open(OUT/name) as pdf:
                        row["header"]=pdf.pages[0].extract_text().splitlines()[0]
                elif "json" in (row["type"] or ""):
                    value=json.loads(content);row["keys"]=list(value)[:12] if isinstance(value,dict) else "array"
            return row
        except HTTPError as error:return {"name":name,"url":url,"status":error.code}
        except Exception as error:return {"name":name,"url":url,"error":str(error)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(probe,targets))
    result={"checked_at":datetime.now(timezone.utc).isoformat(),"results":rows}
    (OUT/"probes.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    for row in rows:print(json.dumps(row),flush=True)

if __name__=="__main__":main()

