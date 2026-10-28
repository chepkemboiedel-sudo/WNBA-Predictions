"""Validate an archived box score corroborated by ESPN Core and WNBA.com."""
import json
import math
import re
import unicodedata
from pathlib import Path

def key(name):
    return re.sub(r"[^a-z0-9]","",unicodedata.normalize("NFKD",name).encode("ascii","ignore").decode().lower())

def minutes(value):
    if not value:return 0.
    m,s=value.split(":")
    if not 0<=int(s)<60:raise ValueError("Invalid minute clock")
    return int(m)+int(s)/60

def validate_boxscore(evidence,game):
    core,official=evidence["espn"],evidence["wnba"]
    if str(core["id"])!=str(game.game_id) or not core["completed"] or official["gameStatus"]!=3:
        raise ValueError("Recovered event identity or final status mismatch")
    if int(game.season)!=int(core["date"][:4]) or core["date"][:10]!=str(game.date)[:10] or core["date"].replace(":00Z","Z")!=official["gameTimeUTC"].replace(":00Z","Z"):
        raise ValueError("Recovered event season/date/tip mismatch")
    rows=[];identities=[];all_ids=set()
    for side,other in (("home","homeTeam"),("away","awayTeam")):
        team=getattr(game,side+"_team");score=int(getattr(game,side+"_score"))
        source=core["teams"][side];w=official[other]
        if source["team"]!=team or w["teamCity"]+" "+w["teamName"]!=team or int(w["score"])!=score:
            raise ValueError("Recovered team or score mismatch")
        used=set();side_rows=[]
        for p in source["players"]:
            aid=str(p["id"])
            if aid in all_ids:raise ValueError("Duplicate recovered athlete")
            all_ids.add(aid)
            aliases={key(p["name"]),key(p["name"].split()[0]+" "+p["game_surname"])}
            matches=[x for x in w["players"] if key(x["firstName"]+" "+x["familyName"]) in aliases]
            if len(matches)!=1:raise ValueError("Ambiguous recovered player identity")
            wp=matches[0]
            if wp["personId"] in used:raise ValueError("Official athlete matched twice")
            used.add(wp["personId"])
            ws=wp["statistics"];mp=minutes(ws["minutes"])
            if p["didNotPlay"]!=(mp==0):raise ValueError("Source participation disagreement")
            if p["didNotPlay"]:
                if any(ws[k] for k in ("points","reboundsTotal","assists")):raise ValueError("DNP has nonzero statistics")
            else:
                stats=p["statistics"]
                if abs(float(stats["minutes"])-mp)>.51:raise ValueError("Source minute totals disagree")
                if any(float(stats[a])!=float(ws[b]) for a,b in (("points","points"),("rebounds","reboundsTotal"),("assists","assists"))):
                    raise ValueError("Source player statistics disagree")
            side_rows.append({"game_id":str(game.game_id),"season":int(game.season),"date":str(game.date)[:10],
                "started_at":core["date"],"is_playoff":bool(game.is_playoff),"team":team,"player_id":aid,"player":p["name"],
                "minutes":mp,"points":float(ws["points"]),"rebounds":float(ws["reboundsTotal"]),"assists":float(ws["assists"])})
            identities.append({"espn_id":aid,"espn_name":p["name"],"event_surname":p["game_surname"],"wnba_id":wp["personId"],"wnba_name":wp["firstName"]+" "+wp["familyName"]})
        if used!={p["personId"] for p in w["players"]}:raise ValueError("Incomplete official roster match")
        expected_minutes=5*(40+5*max(0,int(official["period"])-4))
        if sum(r["minutes"]>0 for r in side_rows)<5 or abs(sum(r["minutes"] for r in side_rows)-expected_minutes)>.1:
            raise ValueError("Incomplete regulation/overtime player minutes")
        if sum(r["points"] for r in side_rows)!=score:raise ValueError("Player points do not sum to the final score")
        for stat,official_stat in (("rebounds","reboundsTotal"),("assists","assists")):
            if sum(r[stat] for r in side_rows)!=float(w["statistics"][official_stat]):raise ValueError("Player totals do not match official team totals")
        if any(not all(math.isfinite(float(r[k])) and float(r[k])>=0 for k in ("minutes","points","rebounds","assists")) for r in side_rows):
            raise ValueError("Invalid recovered player statistic")
        rows.extend(side_rows)
    return rows,identities

def load_verified_boxscore(root,game):
    path=Path(root)/"data/recovery"/f"boxscore_{game.game_id}.json"
    if not path.exists():raise FileNotFoundError("No validated archived fallback for this game")
    return validate_boxscore(json.loads(path.read_text(encoding="utf-8")),game)[0]

