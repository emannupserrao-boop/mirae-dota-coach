"""Normalize only local-player GSI snapshots. Never merge stale fields."""
from dataclasses import dataclass, asdict, field
import math


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def obj(value):
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class State:
    match_id: str = ''
    time: float | None = None
    phase: str = ''
    paused: bool = False
    local: bool = False
    hero: str = ''
    level: float | None = None
    kills: float | None = None
    deaths: float | None = None
    assists: float | None = None
    lh: float | None = None
    denies: float | None = None
    gold: float | None = None
    gpm: float | None = None
    xpm: float | None = None
    buyback_cost: float | None = None
    buyback_cooldown: float | None = None
    alive: bool | None = None
    items: dict = field(default_factory=dict)
    abilities: dict = field(default_factory=dict)

    @property
    def active(self):
        return self.local and bool(self.hero) and self.phase == 'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS' and self.time is not None and self.time >= 0 and not self.paused

    @property
    def buyback(self):
        if None in (self.gold, self.buyback_cost, self.buyback_cooldown):
            return None
        return self.gold >= self.buyback_cost and self.buyback_cooldown == 0

    def to_dict(self):
        return asdict(self)


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError('GSI deve ser um objeto JSON.')
    provider = obj(payload.get('provider'))
    if provider.get('appid') != 570:
        raise ValueError('Pacote não identificado como Dota 2 (appid 570).')
    m, p, h = (obj(payload.get(k)) for k in ('map', 'player', 'hero'))
    # Observer/replay payloads have team/player nesting. Never choose a player from them.
    spectator = any(str(k).startswith(('team', 'player')) and isinstance(v, dict) for k, v in p.items())
    local = (not spectator and p.get('team_name') in ('radiant', 'dire') and 'name' in h
             and p.get('activity', 'playing') == 'playing')
    if not local:
        p, h = {}, {}
    def slots(key, prefix):
        return {k: {f: v for f, v in value.items() if f in ('name', 'level', 'cooldown', 'can_cast', 'is_passive', 'ability_active', 'ultimate', 'charges', 'passive', 'purchaser') and isinstance(v, (str, int, float, bool))}
                for k, value in obj(payload.get(key)).items()
                if local and str(k).startswith(prefix) and isinstance(value, dict)}
    return State(match_id=str(m.get('matchid', '')), time=number(m.get('clock_time')),
                 phase=str(m.get('game_state', '')), paused=m.get('paused') is True,
                 local=local, hero=str(h.get('name', '')), level=number(h.get('level')),
                 kills=number(p.get('kills')), deaths=number(p.get('deaths')),
                 assists=number(p.get('assists')), lh=number(p.get('last_hits')),
                 denies=number(p.get('denies')), gold=number(p.get('gold')),
                 gpm=number(p.get('gpm')), xpm=number(p.get('xpm')),
                 buyback_cost=number(h.get('buyback_cost')),
                 buyback_cooldown=number(h.get('buyback_cooldown')),
                 alive=h.get('alive') if type(h.get('alive')) is bool else None,
                 items=slots('items', ('slot', 'stash', 'teleport', 'neutral')),
                 abilities=slots('abilities', ('ability',)))
