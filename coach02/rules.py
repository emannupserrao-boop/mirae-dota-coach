"""Candidates on transitions only. No TTS, IO or platform dependencies."""
from collections import deque
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    rule_id: str
    semantic_key: str
    text: str
    evidence: dict
    priority: int
    version: int = 1

ITEM_TEXT = {
    'item_bfury':'Battle Fury no inventário. Você pode acelerar seu farm.',
    'item_maelstrom':'Maelstrom no inventário. Seu potencial de farm aumentou.',
    'item_manta':'Manta no inventário. Novo recurso para farm e defesa.',
    'item_black_king_bar':'BKB no inventário. Confira se está pronta antes de lutar.'}

class Engine:
    VERSION='alpha-0.2.0'
    def __init__(self): self.reset()
    def reset(self):
        self.prev=None; self.samples=deque(maxlen=2500); self.death_times=deque(maxlen=30)
        self.low=False; self.farm_since=None; self.recover_since=None; self.low_reference=None
        self.seen_items=set(); self.death_alerted=False
        self.bb=None; self.bb_pending=None; self.bb_since=None
        self.debug={}; self.generation=getattr(self,'generation',0)+1

    def evaluate(self,s,c,p):
        old=self.prev
        if old and (old.match_id!=s.match_id or old.hero!=s.hero or (old.time is not None and s.time is not None and s.time<old.time)):
            self.reset(); old=None
        if not s.active:
            if not s.paused: self.reset()
            return []
        if old and s.time==old.time: return []
        t=s.time; out=[]
        def emit(rid,key,text,evidence):
            out.append(Candidate(rid,key,text,evidence,c['priorities'][rid]))
        # Never announce initial inventory, backpack/stash movements, or a repurchase.
        names={v.get('name') for v in s.items.values() if v.get('name') not in (None,'empty','')}
        on_hero={v.get('name') for k,v in s.items.items() if k.startswith('slot')}
        if old and s.items:
            for name in sorted((on_hero-self.seen_items)&set(c['important_items'])):
                emit('item_power_spike_v1','item:'+name,ITEM_TEXT.get(name,f'{name.removeprefix("item_").replace("_"," ")} no inventário.'),{'item':name,'source':'items.slot','receipt_not_proof_of_purchase':True})
        # Stash arrival is not a power spike; retain baseline stash only on first packet.
        self.seen_items |= on_hero if old else names
        # Recent rolling LH rate vs configured goal OR prior rolling rate.
        if s.alive is not True or s.lh is None or (old and old.lh is not None and s.lh<old.lh):
            self.samples.clear(); self.farm_since=None; self.recover_since=None
        else:
            if not self.samples or t-self.samples[-1][0]>=1: self.samples.append((t,s.lh))
            w=p['farm_window']
            while self.samples and self.samples[0][0]<t-2*w-5: self.samples.popleft()
            def at(target):
                rows=[r for r in self.samples if r[0]<=target]
                return rows[-1] if rows and target-rows[-1][0]<=5 else None
            a,b=at(t-w),at(t-2*w)
            if a and t>=p['farm_min_time']:
                rate=(s.lh-a[1])*60/(t-a[0])
                prior=(a[1]-b[1])*60/(a[0]-b[0]) if b else None
                reference=c['lh_per_minute'] if c['lh_per_minute']>0 else prior
                self.debug.update(farm_recent_lh_min=round(rate,2),farm_prior_lh_min=prior,farm_reference=reference)
                if self.low or (reference is not None and reference>=1):
                    if not self.low:
                        if rate<reference*p['farm_drop_ratio']:
                            self.farm_since=t if self.farm_since is None else self.farm_since
                            if t-self.farm_since>=p['farm_hold']:
                                self.low=True; self.low_reference=reference; self.farm_since=None
                                emit('farm_low_v1','farm:low','Seu ritmo de farm caiu. Procure uma rota segura.',{'recent_lh_per_min':rate,'reference_lh_per_min':reference,'reference_source':'configured' if c['lh_per_minute'] else 'previous_window','window_seconds':w,'hold_seconds':p['farm_hold']})
                        else: self.farm_since=None
                    elif rate>=self.low_reference*p['farm_recovery_ratio']:
                        self.recover_since=t if self.recover_since is None else self.recover_since
                        if t-self.recover_since>=p['farm_hold']:
                            self.low=False; self.recover_since=None
                            emit('farm_recovered_v1','farm:recovered','Seu ritmo de farm voltou a melhorar.',{'recent_lh_per_min':rate,'recovery_reference':self.low_reference,'window_seconds':w})
                    else: self.recover_since=None
        self.debug['farm_state']='LOW' if self.low else 'NORMAL_OR_WARMUP'
        # Count observed +1 deaths only. Large gaps must not fabricate precise death times.
        if s.deaths is None:
            self.death_times.clear(); self.death_alerted=False
        elif old and old.deaths is not None:
            delta=s.deaths-old.deaths
            if delta==1: self.death_times.append(t)
            elif delta!=0: self.death_times.clear(); self.death_alerted=False
        while self.death_times and t-self.death_times[0]>p['death_window']: self.death_times.popleft()
        if len(self.death_times)<p['death_count']: self.death_alerted=False
        elif not self.death_alerted:
            self.death_alerted=True
            emit('death_pattern_v1','death:cluster','Mortes próximas umas das outras. Priorize farm seguro por alguns minutos.',{'observed_death_times':list(self.death_times),'window_seconds':p['death_window'],'deaths':s.deaths})
        # Unknown resets confirmation; never infer missing buyback fields.
        available=s.buyback
        if t<p['buyback_min_time'] or available is None:
            self.bb=None; self.bb_pending=None; self.bb_since=None
        elif self.bb is None:
            self.bb=available
        elif available==self.bb:
            self.bb_pending=None; self.bb_since=None
        else:
            if self.bb_pending!=available:
                self.bb_pending=available; self.bb_since=t
            if t-self.bb_since>=p['buyback_hold']:
                self.bb=available; self.bb_pending=None; self.bb_since=None
                emit('buyback_warning_v1','buyback:'+str(available),
                     'Ouro e cooldown prontos para buyback.' if available else 'Atenção. Você não possui buyback agora.',
                     {'gold':s.gold,'hero.buyback_cost':s.buyback_cost,'hero.buyback_cooldown':s.buyback_cooldown,'alive':s.alive,'available':available,'min_time':p['buyback_min_time']})
        self.prev=s
        return out
