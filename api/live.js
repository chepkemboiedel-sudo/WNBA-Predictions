// Only fixed ESPN WNBA resources are accepted. No caller-provided URLs.
const BASE='https://site.api.espn.com/apis/site/v2/sports/basketball/wnba';
async function get(path){
  const r=await fetch(BASE+path,{signal:AbortSignal.timeout(8000),headers:{'User-Agent':'WNBA forecast'}});
  if(!r.ok)throw new Error('Source unavailable');
  return r.json();
}
function reports(payload){
  return (payload.injuries||[]).map(t=>({team:t.displayName||t.name||t.id,id:String(t.id),players:(t.injuries||[]).map(p=>({
    id:String(p.athlete?.id||(p.athlete?.links||[]).map(l=>(l.href||'').match(/\/id\/(\d+)/)?.[1]).find(Boolean)||''),name:p.athlete?.displayName||p.athlete?.fullName||'Player',status:p.status||'Unknown',
    date:p.date,detail:p.details?.type||'',comment:p.shortComment||'',url:p.athlete?.links?.[0]?.href||'https://www.espn.com/wnba/injuries'
  }))}));
}
function game(event){
  const c=event.competitions?.[0]; if(!c)return null;
  return {id:String(event.id),date:event.date,name:event.name,season:event.season?.year,
    state:c.status?.type?.state,detail:c.status?.type?.detail,period:c.status?.period,clock:c.status?.displayClock,
    teams:(c.competitors||[]).map(t=>({id:String(t.team.id),name:t.team.displayName,home:t.homeAway==='home',score:t.score}))};
}
async function handler(req,res){
  if(req.method!=='GET'){res.statusCode=405;return res.end();}
  const q=req.query||Object.fromEntries(new URL(req.url,'http://localhost').searchParams);
  if(Object.keys(q).some(k=>!['event'].includes(k)) || (q.event && !/^\d{8,12}$/.test(q.event))){
    res.statusCode=400;return res.end('Invalid query');
  }
  try{
    const day=new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replaceAll('-','');
    const [injuries,board,summary]=await Promise.all([get('/injuries?limit=1000'),get('/scoreboard?dates='+day+'&limit=100'),q.event?get('/summary?event='+q.event):Promise.resolve(null)]);
    if(injuries.status!=='success' || injuries.season?.year!==new Date().getUTCFullYear() || !Array.isArray(board.events))throw new Error('Invalid or wrong-season feed');
    let selected=null;
    if(summary){
      if(summary.header?.league?.slug!=='wnba')throw new Error('Wrong league');
      const event={...summary.header,competitions:summary.header?.competitions};
      selected=game(event);
      if(!selected || !selected.teams.length)throw new Error('Missing game');
      selected.lineups=(summary.boxscore?.players||[]).map(t=>({team:t.team?.displayName,
        players:(t.statistics||[]).flatMap(s=>(s.athletes||[]).map(a=>({id:String(a.athlete?.id),name:a.athlete?.displayName,
          starter:a.starter===true,minutes:a.stats?.[s.labels?.indexOf('MIN')]||null,didNotPlay:a.didNotPlay===true})))
      }));
    }
    res.setHeader('Content-Type','application/json');
    res.setHeader('Cache-Control','public, s-maxage=45, max-age=0, stale-while-revalidate=15');
    res.end(JSON.stringify({fetched_at:new Date().toISOString(),source_timestamp:injuries.timestamp,season:injuries.season?.year,
      source:'ESPN public feeds',injuries:reports(injuries),games:board.events.map(game).filter(Boolean),selected}));
  }catch(e){res.statusCode=503;res.setHeader('Cache-Control','no-store');res.end(JSON.stringify({error:'Live source unavailable; saved forecasts remain available.'}));}
}
module.exports=handler;
module.exports.reports=reports;
module.exports.game=game;

