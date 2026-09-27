"""Sunday Edge collector. No keys needed for these supplied ESPN endpoints.
Unofficial upstream responses are not guaranteed. Do not run if provider terms prohibit your use.
Failed games retain their previous observation timestamp; no probabilities are produced.
"""
import json, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

def utc(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def get(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'Accept':'application/json'}),timeout=20) as r:
                return json.load(r)
        except Exception as e:
            print(f'  {url[:90]} -> {type(e).__name__}: {e}',file=sys.stderr)
            if attempt==2: raise
            time.sleep(2**attempt)
def number(value):
    try: return float(value)
    except (TypeError,ValueError): return None

def normalize(game,s,status):
    c=s['header']['competitions'][0]
    home=next(x for x in c['competitors'] if x['homeAway']=='home')
    away=next(x for x in c['competitors'] if x['homeAway']=='away')
    if (home['team']['abbreviation'],away['team']['abbreviation'])!=(game['home'],game['away']): raise ValueError('event/team mismatch')
    state=status['type']['state']
    if state not in ['pre','in','post']: raise ValueError('unsupported status')
    def score(x):
        v=x.get('score'); v=v.get('value') if isinstance(v,dict) else v
        if v is None and state=='pre': return 0
        if v is None: raise ValueError('missing score')
        return int(v)
    clock=status.get('displayClock')
    if clock is None and state=='in': raise ValueError('missing live clock')
    result={'id':game['id'],'away':game['away'],'home':game['home'],'awayScore':score(away),'homeScore':score(home),'period':status.get('period',0),'clock':clock or '0:00','state':state,'observedAt':utc(),'source':'ESPN summary + core status; collector v1.1','statusText':status['type'].get('detail',''),'stats':{'away':{},'home':{}},'drives':[],'plays':[],'players':[]}
    mapping={'totalOffensivePlays':'plays','totalYards':'yards','yardsPerPlay':'ypp','turnovers':'turnovers','thirdDownEff':'thirdDown','redZoneAttempts':'redZone','possessionTime':'possessionTime'}
    for t in s.get('boxscore',{}).get('teams',[]):
        side=t.get('homeAway')
        if side not in result['stats']: continue
        for stat in t.get('statistics',[]):
            k=mapping.get(stat.get('name'));v=stat.get('displayValue')
            if not k or v is None: continue
            val=str(v) if k in ['thirdDown','redZone','possessionTime'] else number(v)
            if val is not None and (isinstance(val,str) or val>=0): result['stats'][side][k]=val
    drives=list(s.get('drives',{}).get('previous',[]))
    if s.get('drives',{}).get('current'): drives.append(s['drives']['current'])
    seen=set();play_seen=set()
    for d in drives:
        key=str(d.get('id',''))
        if not key or key in seen: continue
        seen.add(key)
        row={'id':key,'team':d.get('team',{}).get('abbreviation',''),'text':d.get('description',''),'result':d.get('result') or d.get('displayResult') or ''}
        y=number(d.get('yards'))
        if y is not None and y>=0: row['yards']=y
        result['drives'].append(row)
        for p in d.get('plays',[]):
            pid=str(p.get('id',''))
            if not pid or pid in play_seen: continue
            play_seen.add(pid);row={'id':pid,'text':p.get('text','')}
            if p.get('period',{}).get('number') is not None: row['period']=p['period']['number']
            if p.get('clock',{}).get('displayValue') is not None: row['clock']=p['clock']['displayValue']
            result['plays'].append(row)
    players={}
    for team in s.get('boxscore',{}).get('players',[]):
        for group in team.get('statistics',[]):
            for a in group.get('athletes',[]):
                person=a.get('athlete',{});pid=str(person.get('id',''))
                if not pid: continue
                row=players.setdefault(pid,{'id':pid,'name':person.get('displayName',''),'team':team.get('team',{}).get('abbreviation',''),'stats':{}})
                row['stats'].update({k:str(v) for k,v in zip(group.get('keys',[]),a.get('stats',[])) if v is not None})
    result['players']=list(players.values())
    return result

def main():
    games=json.loads(Path('games.json').read_text());path=Path('latest.json')
    old=json.loads(path.read_text()) if path.exists() else {'games':[]}
    previous={g['id']:g for g in old.get('games',[]) if not g.get('source','').startswith('DOCUMENTATION')}
    merged=dict(previous);success=0
    for g in games:
        try:
            sid=g['id']
            s=get(f'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={sid}')
            status=get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{sid}/competitions/{sid}/status')
            merged[sid]=normalize(g,s,status);success+=1
        except Exception as e:
            print(f"Warning: {g['id']} fetch/normalize failed ({type(e).__name__}); previous time retained",file=sys.stderr)
        time.sleep(.25)
    if not success: raise RuntimeError('All games failed; no file overwritten')
    result={'schemaVersion':1,'generatedAt':utc(),'games':[merged[g['id']] for g in games if g['id'] in merged]}
    from jsonschema import Draft202012Validator,FormatChecker
    Draft202012Validator(json.loads(Path('latest.schema.json').read_text()),format_checker=FormatChecker()).validate(result)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result,separators=(',',':')));os.replace(tmp,path)
    print(f'Collected {success}/{len(games)} games; preserved failed games where available')
if __name__=='__main__': main()
