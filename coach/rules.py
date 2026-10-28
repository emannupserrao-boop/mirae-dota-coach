"""Deterministic, transport-independent rules. Match-clock timers ignore pause."""
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Advice:
    rule: str
    text: str
    evidence: dict


class Engine:
    VERSION = 'alpha-0.1'

    def __init__(self):
        self.reset()

    def reset(self):
        self.prev = None
        self.farm_low = False
        self.farm_since = None
        self.samples = deque(maxlen=360)
        self.seen_items = set()
        self.sent = {}
        self.last_notice = -1e9
        self.near_target = False
        self.target_signature = None

    def evaluate(self, s, settings):
        previous = self.prev
        if previous and (s.match_id != previous.match_id or s.hero != previous.hero or
                         (s.time is not None and previous.time is not None and s.time < previous.time)):
            self.reset()
            previous = None
        if not s.active:
            # Returning to menu/spectator ends the local rule session; pause preserves it.
            if not s.paused:
                self.reset()
            return []
        t = s.time
        if previous and t == previous.time:
            return []
        candidates = []
        def add(rule, text, **evidence):
            candidates.append(Advice(rule, text, evidence))
        names = {v.get('name') for k, v in s.items.items() if k.startswith(('slot', 'stash')) and v.get('name') not in (None, '', 'empty')}
        important = set(settings['important_items'])
        if previous:
            for name in sorted((names - self.seen_items) & important):
                add('item:' + name, f'Item importante recebido: {name.removeprefix("item_").replace("_", " ")}.', item=name)
            if s.level is not None and previous.level is not None:
                crossed = [lv for lv in (6, 12, 18) if previous.level < lv <= s.level]
                if crossed:
                    add('power_spike', f'Nível {int(s.level)}: possível power spike. Confira suas habilidades antes de lutar.', level=s.level)
            if s.deaths is not None and previous.deaths is not None and s.deaths > previous.deaths and s.deaths >= 3 and s.deaths >= t / 300:
                add('deaths', 'Muitas mortes para este tempo de partida. Reavalie a segurança da sua rota de farm.', deaths=s.deaths, minutes=t/60)
            if s.buyback is not None and previous.buyback is not None and s.buyback != previous.buyback:
                add('buyback', 'Há ouro e cooldown para buyback.' if s.buyback else 'Buyback sem ouro suficiente ou em cooldown.', available=s.buyback, cost=s.buyback_cost, gold=s.gold)
        self.seen_items |= names
        target = settings.get('target_item', '')
        cost = settings.get('target_remaining_cost', 0)
        signature = (target, cost)
        if signature != self.target_signature:
            self.near_target = False
            self.target_signature = signature
        near = bool(target and cost > 0 and target not in names and s.gold is not None and s.gold >= max(0, cost - 300))
        if near and not self.near_target:
            add('near_item', f'Ouro próximo da compra planejada de {target.removeprefix("item_").replace("_", " ")}. Confirme o custo restante na loja.', gold=s.gold, configured_remaining_cost=cost)
        self.near_target = near
        if s.lh is not None and t >= 300 and settings['lh_per_minute'] > 0:
            goal = settings['lh_per_minute'] * t / 60
            if not self.farm_low and s.lh < goal * .8:
                if self.farm_since is None:
                    self.farm_since = t
                if t - self.farm_since >= 30:
                    add('farm_low', 'Farm abaixo da meta configurada. Procure uma rota segura para recuperar last hits.', lh=s.lh, target=goal)
            elif self.farm_low and s.lh >= goal * .95:
                add('farm_recovered', 'Farm recuperado: você voltou à faixa da meta.', lh=s.lh, target=goal)
            elif not self.farm_low:
                self.farm_since = None
        # Average of samples around 2 minutes ago; missing metrics never count as zero.
        if not self.samples or t - self.samples[-1][0] >= 5:
            self.samples.append((t, s.gpm, s.xpm))
        while self.samples and self.samples[0][0] < t - 240:
            self.samples.popleft()
        for index, label in ((1, 'GPM'), (2, 'XPM')):
            baseline = [row[index] for row in self.samples if 120 <= t-row[0] <= 180 and row[index] is not None]
            recent = [row for row in self.samples if t-row[0] <= 60]
            if baseline and len(recent) >= 10 and t-recent[0][0] >= 50:
                base = sum(baseline)/len(baseline)
                if base > 0 and all(row[index] is not None and row[index] < base * .8 for row in recent):
                    add('drop_' + label, f'{label} caiu por cerca de um minuto. Reavalie sua rota de recursos.', baseline=round(base), current=recent[-1][index])
        self.prev = s
        if not settings.get('coach', True):
            return []
        gap = {'frequente': 15, 'normal': 45, 'discreto': 90}[settings['frequency']]
        if t-self.last_notice < gap:
            return []
        for advice in candidates:
            if t-self.sent.get(advice.rule, -1e9) < 180:
                continue
            self.sent[advice.rule] = t
            self.last_notice = t
            if advice.rule == 'farm_low':
                self.farm_low = True
            elif advice.rule == 'farm_recovered':
                self.farm_low = False
                self.farm_since = None
            return [advice]
        return []
