"""Synthetic fixture, never presented as a real Dota match."""
def payload(t=300, lh=10, **player):
    p = dict(team_name='radiant', activity='playing', kills=1, deaths=0, assists=2,
             last_hits=lh, denies=3, gold=1200, gpm=400, xpm=450)
    p.update(player)
    return dict(provider={'appid':570}, map={'matchid':'demo', 'clock_time':t,
                'game_state':'DOTA_GAMERULES_STATE_GAME_IN_PROGRESS', 'paused':False},
                player=p, hero={'name':'npc_dota_hero_juggernaut', 'level':5, 'alive':True,
                               'buyback_cost':700, 'buyback_cooldown':0},
                items={'slot0':{'name':'item_boots', 'cooldown':0}},
                abilities={'ability0':{'name':'juggernaut_blade_fury', 'level':3, 'cooldown':0, 'can_cast':True}})
