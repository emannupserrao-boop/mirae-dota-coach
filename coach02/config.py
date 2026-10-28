"""Versioned preferences. Mode is a process argument, NEVER a saved preference."""
import copy
import json
import math
import os
import secrets
from pathlib import Path
from coach.config import gsi_text as base_gsi_text

RULE_IDS = ('farm_low_v1','farm_recovered_v1','item_power_spike_v1',
            'death_pattern_v1','buyback_warning_v1','enemy_missing_v1')
NORMAL = dict(farm_window=90, farm_hold=20, farm_drop_ratio=.65, farm_recovery_ratio=.9,
              farm_min_time=180, death_window=300, death_count=3, buyback_min_time=1200,
              buyback_hold=5, global_cooldown=30, semantic_cooldown=120,
              cooldowns=dict(zip(RULE_IDS, [180,90,30,300,120,60])))
TEST = {**NORMAL, 'farm_window':20,'farm_hold':5,'farm_min_time':0,
        'death_count':2, 'buyback_min_time':0, 'buyback_hold':3,
        'global_cooldown':5, 'semantic_cooldown':10,
        'cooldowns':dict(zip(RULE_IDS,[15,5,5,30,10,5]))}
DEFAULTS = dict(port=32124, coach=True, voice=True, volume=70, frequency='normal',
                lh_per_minute=5.0, important_items=['item_bfury','item_maelstrom','item_manta','item_black_king_bar'],
                priorities=dict(zip(RULE_IDS,[2,1,3,3,4,4])), normal=NORMAL, test=TEST,
                vision=dict(roi=[0,0,300,300], fps=5, visible_threshold=.90, absent_threshold=.65,
                            confirm_frames=3, missing_seconds=4., nearby_distance=.18,
                            with_us_distance=.08, ambiguity_margin=.06, roles={}))
GSI_FILENAME = 'gamestate_integration_dota_ai_coach_alpha02.cfg'

def data_dir():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'DotaAICoach02'

def validate(c):
    def numeric(value, low, high, name, integer=False):
        if type(value) not in (int,float) or not math.isfinite(value) or not low <= value <= high or (integer and type(value) is not int):
            raise ValueError(f'{name}: valor deve estar entre {low} e {high}.')
    if not isinstance(c,dict): raise ValueError('Configuração deve ser objeto JSON.')
    numeric(c['port'],1024,65535,'port',True)
    numeric(c['volume'],0,100,'volume')
    numeric(c['lh_per_minute'],0,30,'lh_per_minute')
    if c['frequency'] not in ('frequente','normal','discreto'): raise ValueError('frequency inválida')
    if any(type(c[k]) is not bool for k in ('coach','voice')): raise ValueError('coach e voice devem ser booleanos')
    if not isinstance(c['token'],str) or len(c['token'])<32 or not c['token'].isascii() or not c['token'].isalnum(): raise ValueError('token inválido')
    if not isinstance(c['important_items'],list) or not all(isinstance(x,str) and x.startswith('item_') and len(x)<100 for x in c['important_items']): raise ValueError('Lista de itens inválida')
    for rid in RULE_IDS: numeric(c['priorities'][rid],1,4,'priority',True)
    for mode in ('normal','test'):
        p=c[mode]
        for key in ('farm_window','death_window'): numeric(p[key],5,600,key)
        for key in ('farm_hold','buyback_hold'): numeric(p[key],1,120,key)
        for key in ('farm_min_time','buyback_min_time'): numeric(p[key],0,7200,key)
        for key in ('global_cooldown','semantic_cooldown'): numeric(p[key],1,600,key)
        numeric(p['death_count'],2,10,'death_count',True)
        numeric(p['farm_drop_ratio'],.1,.85,'farm_drop_ratio')
        numeric(p['farm_recovery_ratio'],.86,1.5,'farm_recovery_ratio')
        for rid in RULE_IDS: numeric(p['cooldowns'][rid],1,1200,'cooldown')
    v=c['vision']
    if len(v['roi'])!=4: raise ValueError('ROI deve ser [x,y,width,height]')
    for i,n in enumerate(v['roi']): numeric(n,-16000 if i<2 else 100,16000 if i<2 else 600,'roi',True)
    if v['fps'] not in (5,10,15): raise ValueError('FPS deve ser 5,10 ou 15')
    numeric(v['visible_threshold'],.75,.99,'visible_threshold')
    numeric(v['absent_threshold'],.1,.74,'absent_threshold')
    numeric(v['confirm_frames'],2,15,'confirm_frames',True)
    numeric(v['missing_seconds'],2,30,'missing_seconds')
    numeric(v['with_us_distance'],.01,.2,'with_us_distance')
    numeric(v['nearby_distance'],v['with_us_distance'],.5,'nearby_distance')
    numeric(v['ambiguity_margin'],.01,.3,'ambiguity_margin')
    if not isinstance(v['roles'],dict): raise ValueError('roles inválido')
    for role,box in v['roles'].items():
        if role not in ('enemy_mid','enemy_support_opposite','allied_support','local_player') or len(box)!=4: raise ValueError('Papel/corte inválido')
        x,y,w,h=box
        for n in box: numeric(n,0,600,'template box',True)
        if not 8<=w<=64 or not 8<=h<=64 or x+w>v['roi'][2] or y+h>v['roi'][3]: raise ValueError('Corte do ícone fora do ROI ou tamanho 8–64 necessário')

def load(directory):
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'settings02.json'
    c=copy.deepcopy(DEFAULTS)
    c['token']=secrets.token_hex(32)
    if path.exists(): c.update(json.loads(path.read_text(encoding='utf-8')))
    validate(c)
    if not path.exists(): save(directory,c)
    return c

def save(directory,c):
    validate(c)
    clean=copy.deepcopy(c)
    clean.pop('test_mode',None); clean.pop('vision_enabled',None)
    tmp=directory/'settings02.tmp'
    tmp.write_text(json.dumps(clean,indent=2,ensure_ascii=False),encoding='utf-8')
    tmp.replace(directory/'settings02.json')

def profile(c,test_mode):
    p=copy.deepcopy(c['test' if test_mode else 'normal'])
    p['global_cooldown']*= {'frequente':.5,'normal':1,'discreto':2}[c['frequency']]
    return p

def gsi_text(c):
    return base_gsi_text(c).replace('Dota AI Coach Alpha','Dota AI Coach Alpha 0.2')

def install_gsi(root,c):
    cfg=Path(root)/'game'/'dota'/'cfg'
    if not cfg.is_dir(): raise ValueError('Selecione a pasta dota 2 beta.')
    folder=cfg/'gamestate_integration'; folder.mkdir(exist_ok=True)
    path=folder/GSI_FILENAME
    if path.exists(): path.with_suffix('.cfg.bak').write_bytes(path.read_bytes())
    path.write_text(gsi_text(c),encoding='utf-8')
    return path
