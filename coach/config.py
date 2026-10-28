import json
import os
import secrets
from pathlib import Path

DEFAULTS = dict(port=32123, coach=True, voice=True, volume=70, frequency='normal',
                lh_per_minute=5.0, target_item='', target_remaining_cost=0,
                important_items=['item_bfury', 'item_black_king_bar', 'item_manta',
                                 'item_radiance', 'item_butterfly', 'item_satanic'])


def data_dir():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'DotaAICoach'


def validate(settings):
    if type(settings['port']) is not int or not 1024 <= settings['port'] <= 65535:
        raise ValueError('Porta deve estar entre 1024 e 65535.')
    if settings['frequency'] not in ('frequente', 'normal', 'discreto'):
        raise ValueError('Frequência inválida.')
    if not 0 <= settings['volume'] <= 100 or not 0 <= settings['lh_per_minute'] <= 30:
        raise ValueError('Volume: 0–100. Meta LH/min: 0–30.')
    if not 0 <= settings['target_remaining_cost'] <= 20000:
        raise ValueError('Custo restante: 0–20000.')
    if not isinstance(settings['important_items'], list) or not all(isinstance(x,str) for x in settings['important_items']):
        raise ValueError('important_items deve ser uma lista de nomes.')
    if not isinstance(settings['token'], str) or len(settings['token']) < 32 or not all(c.isalnum() for c in settings['token']):
        raise ValueError('Token inválido.')


def save(directory, settings):
    validate(settings)
    tmp = directory / 'settings.tmp'
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(directory / 'settings.json')


def load(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'settings.json'
    settings = dict(DEFAULTS)
    if path.exists():
        settings.update(json.loads(path.read_text(encoding='utf-8')))
    else:
        settings['token'] = secrets.token_hex(32)
        save(directory, settings)
    validate(settings)
    return settings


def gsi_text(settings):
    return '''"Dota AI Coach Alpha"
{
    "uri" "http://127.0.0.1:%s/gsi"
    "timeout" "5.0"
    "buffer" "0.2"
    "throttle" "0.5"
    "heartbeat" "5.0"
    "auth" { "token" "%s" }
    "data"
    {
        "provider" "1"
        "map" "1"
        "player" "1"
        "hero" "1"
        "abilities" "1"
        "items" "1"
    }
}
''' % (settings['port'], settings['token'])


def install_gsi(dota_root, settings):
    root = Path(dota_root)
    cfg = root / 'game' / 'dota' / 'cfg'
    if not cfg.is_dir():
        raise ValueError('Selecione a pasta dota 2 beta, que contém game/dota/cfg.')
    folder = cfg / 'gamestate_integration'
    folder.mkdir(exist_ok=True)
    dest = folder / 'gamestate_integration_dota_ai_coach.cfg'
    if dest.exists():
        # Keep the previous configuration of THIS application only.
        dest.with_suffix('.cfg.bak').write_bytes(dest.read_bytes())
    dest.write_text(gsi_text(settings), encoding='utf-8')
    return dest
