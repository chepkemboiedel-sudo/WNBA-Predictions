"""Fixed, disjoint prospective checks. Historical results cannot promote a model."""
import hashlib
import json
import math
from datetime import datetime, timezone

import numpy as np

VERSION = "prospective-gate-v1"
BLOCK = 100


def evaluate(ledger, model_version, season):
    rows = []
    seen = set()
    for r in sorted(ledger.get("predictions", []), key=lambda r: r["locked_at"]):
        tip = datetime.fromisoformat(r["tip"].replace("Z", "+00:00"))
        locked = datetime.fromisoformat(r["locked_at"].replace("Z", "+00:00"))
        fetched = datetime.fromisoformat(r.get("snapshot",{}).get("fetched_at","1900-01-01T00:00:00+00:00").replace("Z","+00:00"))
        if (r.get("status") not in ("pending","settled") or r.get("model_version") != model_version or
                tip.year != season or not 300 <= (tip-locked).total_seconds() <= 86400 or
                not 0 <= (locked-fetched).total_seconds() <= 7200 or
                r["game_id"] in seen or not r.get("model_sha256") or not r.get("snapshot")):
            continue
        if not all(0 < r[k] < 1 for k in ("p_baseline", "p_adjusted")) or (r["status"]=="settled" and r.get("home_win") not in (0, 1)):
            continue
        seen.add(r["game_id"])
        rows.append(r)
    result = {"policy": VERSION, "model_version": model_version, "season": season,
              "eligible_games": sum(r["status"]=="settled" for r in rows), "registered_games":len(rows), "block_size": BLOCK, "promoted": False, "checks": [],
              "reason": "Waiting for 100 independently recorded, completed games of the current model version."}
    for index in range(len(rows)//BLOCK):
        block = rows[index*BLOCK:(index+1)*BLOCK]
        # Reserve slots before outcomes. Late results cannot reshuffle blocks
        # or cause the same evidence to receive multiple significance tests.
        if any(r["status"]!="settled" for r in block):
            continue
        days = np.array([r["local_date"] for r in block])
        unique = sorted(set(days))
        y = np.array([r["home_win"] for r in block])
        b, a = (np.array([r[k] for r in block]) for k in ("p_baseline", "p_adjusted"))
        changed = int((abs(a-b)>1e-10).sum())
        bc, ac = (b>=.5)==y, (a>=.5)==y
        corrected, harmed = int((ac & ~bc).sum()), int((bc & ~ac).sum())
        discordant = corrected+harmed
        p = min(1., 2*sum(math.comb(discordant,k) for k in range(min(corrected,harmed)+1))/2**discordant) if discordant else 1.
        delta = np.column_stack([ac.astype(float)-bc,
             -(y*np.log(a)+(1-y)*np.log1p(-a))+(y*np.log(b)+(1-y)*np.log1p(-b)),
             (a-y)**2-(b-y)**2])
        # Across fixed looks, sum 0.05/(k*(k+1)) = 0.05. Split each look
        # across the three metrics and McNemar; no daily significance peeking.
        look = index+1
        alpha = .05/(look*(look+1)*4)
        rng = np.random.default_rng(4901+index)
        sums = np.array([delta[days==d].sum(axis=0) for d in unique])
        counts = np.array([(days==d).sum() for d in unique])
        boot = []
        for _ in range(20000):
            sample = rng.integers(0,len(unique),len(unique))
            boot.append(sums[sample].sum(axis=0)/counts[sample].sum())
        ci = np.quantile(boot,[alpha/2,1-alpha/2],axis=0)
        span = (datetime.fromisoformat(unique[-1])-datetime.fromisoformat(unique[0])).days+1
        passed = (len(unique)>=30 and span>=30 and changed>=30 and delta[:,0].mean()>=.01
                  and ci[0,0]>0 and ci[1,1]<0 and ci[1,2]<0 and p<=alpha)
        evidence = {"look":look,"games":BLOCK,"distinct_days":len(unique),"span_days":span,"changed_games":changed,
                    "alpha_per_test":alpha,"accuracy_gain":float(delta[:,0].mean()),"log_loss_change":float(delta[:,1].mean()),
                    "brier_change":float(delta[:,2].mean()),"intervals":ci.T.tolist(),"mcnemar_p":p,"passed":bool(passed),
                    "game_ids":[r["game_id"] for r in block]}
        result["checks"].append(evidence)
        if passed:
            result.update(promoted=True,reason="A fixed prospective block passed the prespecified improvement checks.",
                          evidence_id=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()[:20])
            break
    if result["checks"] and not result["promoted"]:
        result["reason"]="No completed prospective block passed every improvement check; score-only stays default."
    return result


def current(root, snapshot, season):
    path = root/"data/backtests/prospective_predictions.json"
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    from availability import MODEL_VERSION
    decision = evaluate(ledger,"score-logistic-v1+"+MODEL_VERSION,season)
    decision["checked_at"] = datetime.now(timezone.utc).isoformat()
    decision["usable"] = bool(decision["promoted"] and snapshot.get("apply_adjustments") and snapshot.get("season")==season)
    return decision

