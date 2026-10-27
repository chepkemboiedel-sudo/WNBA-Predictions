"""Roster, source coverage, and experimental availability comparisons."""
from html import escape

from availability import team_shift
from app_data import slug


CSS = """
.availability-notice{border-left:4px solid var(--west);padding:15px 18px;background:var(--card);border-radius:8px;margin:18px 0;color:var(--ink)}
.availability-tag{font-size:.72rem;font-weight:800;border-radius:99px;padding:4px 9px;background:var(--line);white-space:nowrap}
.availability-out{color:var(--neg);background:color-mix(in srgb,var(--neg) 10%,var(--card))}
.health-partial,.health-stale,.health-unavailable{color:#946200;background:color-mix(in srgb,#d39416 12%,var(--card))}
.roster-table{min-width:750px}.roster-table td:first-child,.roster-table th:first-child{text-align:left}.roster-table .report-note{max-width:330px;font-size:.8rem;color:var(--muted);white-space:normal;margin-top:5px}
.roster-source{display:flex;flex-wrap:wrap;gap:10px 24px;color:var(--muted);font-size:.85rem;margin:18px 0}
"""


def roster_section(team_name, availability):
    team = availability.get("teams",{}).get(team_name,{})
    players = team.get("players",[])
    rows = []
    for player in sorted(players,key=lambda p:(p["status"]!="Out",p["name"])):
        out = player["status"].lower() in ("out","suspended")
        minutes = f"{player['minutes']:.1f}" if player.get("minutes") is not None else "—"
        points = f"{player['points']:.1f}" if player.get("points") is not None else "—"
        applied = availability.get("apply_adjustments") and player.get("extra_absence_points",0)>0
        impact = f"Optional: −{player['extra_absence_points']:.2f} pts" if applied else "No optional penalty"
        scope = {"long_term":"Long-term report","next_game":"Next game only","none":"Not assumed absent"}[player.get("scope","none")]
        reason = player.get("reason","") if player["status"]!="No report" else ""
        rows.append(f'''<tr><td><a class="team-link" href="{escape(player['source_url'])}">{escape(player['name'])} ↗</a><div class="report-note">{escape(player['position'])} · #{escape(player.get('jersey',''))}</div></td>
          <td><span class="availability-tag {'availability-out' if out else ''}">{escape(player['status'])}</span><div class="report-note">{escape(player['detail'])}</div></td>
          <td>{escape((player.get('report_date') or 'Not listed')[:10])}</td><td>{player['games_played']}</td><td>{minutes}</td><td>{points}</td>
          <td>{impact}<div class="report-note">{scope}. {escape(reason)}</div></td></tr>''')
    freshness = availability.get("cached_roster_at") or availability.get("fetched_at") or "Not available"
    changes = f"{len(team.get('added_ids',[]))} added / {len(team.get('removed_ids',[]))} removed since the previous roster snapshot" if team.get("has_previous_roster") else "First saved roster snapshot"
    coverage = availability.get("boxscore_coverage",{})
    table = '<div class="tblwrap"><table class="roster-table"><thead><tr><th>Player</th><th>Reported status</th><th>Report date</th><th>GP sample</th><th>MPG</th><th>PPG</th><th>Forecast treatment</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>' if rows else '<p class="lead">The roster could not be retrieved. No missing-player adjustment is assumed.</p>'
    return f'''<section id="roster"><div class="wrap"><span class="eyebrow">Who is listed, who may be missing</span><h2>Roster &amp; availability</h2>
      <p class="lead">Published predictions use the score-only model. The treatments below apply only to the optional injury adjustment. “No report” does not guarantee that a player will play.</p>
      <div class="availability-notice">{escape(availability.get('message','Player feeds unavailable; score-only forecasts are used.'))}</div>
      <div class="roster-source"><span>Fetched: {escape(freshness)}</span><span>{changes}</span><a class="team-link" href="{escape(team.get('roster_url','https://www.espn.com/wnba/teams'))}">ESPN season roster ↗</a></div>
      <p class="feature-note">GP, minutes, and points use covered 2026 regular-season box scores for this team. Archive coverage: {coverage.get('covered_games',0)}/{coverage.get('expected_games',0)} games across 2025–26. {team.get('missing_boxscores',0)} current-season box scores unavailable for this team.</p>
      {table}<p class="feature-note">Extra absence penalties are experimental point-margin estimates. Time already missed is discounted because it is already reflected in team form. Players with no usable participation comparison receive no invented effect.</p></div></section>'''


def overview(availability, results):
    enabled = availability.get("apply_adjustments",False)
    rows = []
    for result in results.sort_values("seed").itertuples():
        team = availability.get("teams",{}).get(result.team,{})
        baseline = getattr(result,"p_champion_baseline",result.p_champion)
        optional = getattr(result,"p_champion_availability",baseline)
        applied = sum(p.get("extra_absence_points",0)>0 for p in team.get("players",[])) if enabled else 0
        shift = team_shift(team) if enabled else 0
        rows.append(f'''<tr><td><a class="team-link" href="/teams/{slug(result.team)}/#roster">{escape(result.team)} ↗</a></td><td>{applied}</td><td>{shift:+.2f} pts</td><td>{baseline:.1%}</td><td>{optional:.1%}</td><td>{(optional-baseline)*100:+.1f} pp</td></tr>''')
    model = availability.get("model",{})
    stamp = availability.get("fetched_at","Not available")
    label = "Score-only is the default · injury adjustments are optional and experimental"
    return f'''<section id="availability"><div class="wrap"><span class="eyebrow">The players behind the forecast</span><h2>Injuries &amp; roster impact</h2>
      <p class="lead">{label}</p><div class="availability-notice">{escape(availability.get('message','No verified player feeds are available.'))}</div>
      <p>Historical testing has not shown a clear improvement from injury adjustments. <a class="team-link" href="#play">Try the optional toggle in the interactive bracket ↓</a></p>
      <p>Player reports fetched {escape(stamp)}. <a class="team-link" href="https://www.espn.com/wnba/injuries">View ESPN injury reports ↗</a></p>
      <div class="tblwrap"><table><thead><tr><th>Team / roster</th><th>Absences with estimated effect</th><th>Optional long-term adjustment</th><th>Score-only title (default)</th><th>Optional injury-adjusted title</th><th>Optional change</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <details class="availability-notice"><summary>How missing players affect the forecast</summary>
        <p>Player effects are shrunken associations between participation and score residuals in {model.get('training_games',0)} completed regular-season games from 2025–26. Only teams with complete current-season player history are adjusted.</p>
        <p>Confirmed season-long absences carry through the remaining bracket. Fresh game-specific “Out” reports apply only to the next scheduled game within 72 hours. Older reports contradicted by later appearances, ambiguous roster assignments, and questionable or probable statuses do not trigger an assumed absence.</p>
        <p>Estimated penalties are reduced by the player's regular-season participation rate to avoid counting existing absences twice. Effects are capped at four points per player and six per team. These are conservative modeling choices, not measured causal effects.</p>
        <p><strong>The availability layer is experimental.</strong> Historical calibration and validation on this page describe the score-only model. They do not establish injury-adjusted accuracy. Roster changes determine report assignment; transfers do not receive an unverified automatic boost.</p>
        <p>Minute restrictions and mid-game injuries are not forecast.</p>
      </details></div></section>'''
