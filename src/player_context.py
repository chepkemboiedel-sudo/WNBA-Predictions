"""Explicit minute caps and clearly labelled recent-usage lineup estimates."""
import re
from datetime import timedelta


def minute_limit(report, now, next_game, typical_minutes, last_played=None):
    from availability import utc
    published = utc((report or {}).get("date"))
    tip = utc((next_game or {}).get("date"))
    played = utc(last_played)
    if not published or not tip or not timedelta(0)<=now-published<=timedelta(hours=72) or not timedelta(0)<tip-now<=timedelta(hours=72):
        return None
    if played and played>published or not typical_minutes or typical_minutes<=0:
        return None
    text = " ".join(str((report or {}).get(k, "")) for k in ("shortComment","longComment"))
    if re.search(r"\b(no|without|not|lifted|removed|could|might|may)\b.{0,40}(limit|restrict|cap)",text,re.I):
        return None
    if re.search(r"\b(limit|restriction|cap)\b.{0,30}\b(lifted|removed|ended)\b",text,re.I):
        return None
    matches = re.findall(r"\b(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?[- ]minute\s+(?:limit|restriction|cap)\b",text,re.I)
    if len(matches)!=1:
        return None
    cap = int(matches[0][1] or matches[0][0])
    if not 1<=cap<min(40,typical_minutes):
        return None
    return {"minutes":cap,"fraction_missing":round(1-cap/typical_minutes,4),"text":text,
            "published_at":(report or {}).get("date"),"event_id":next_game.get("event_id")}


def projected_rotation(boxes, team, season):
    if boxes.empty:
        return {"kind":"unavailable","players":[],"note":"No recent player box scores; starting lineup unconfirmed."}
    rows = boxes[(boxes.team==team)&(boxes.season==season)]
    dates = rows[["game_id","date"]].drop_duplicates().sort_values("date").tail(3)
    rows = rows[rows.game_id.isin(dates.game_id)]
    if rows.empty:
        return {"kind":"unavailable","players":[],"note":"No recent player box scores; starting lineup unconfirmed."}
    used = rows.groupby(["player_id","player"]).minutes.sum().div(len(dates)).sort_values(ascending=False).head(5)
    return {"kind":"projected_usage","games":len(dates),
            "players":[{"id":str(aid),"name":name,"recent_minutes":round(float(value),1)} for (aid,name),value in used.items()],
            "note":"Five highest recent-minute players across the last three covered games. Usage estimate; starting lineup unconfirmed."}

