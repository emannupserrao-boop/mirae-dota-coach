"""Prioritize candidates, recording every rejection without delayed stale calls."""
class Policy:
    def __init__(self): self.reset()
    def reset(self):
        self.last_global=-1e12; self.last_priority=0; self.last_rule={}; self.last_semantic={}
    def decide(self,candidates,t,profile,enabled=True):
        decisions=[]; seen=set()
        for event in sorted(candidates,key=lambda x:-x.priority):
            reason=None
            if not enabled: reason='coach_disabled'
            elif event.semantic_key in seen: reason='duplicate_batch'
            elif t-self.last_semantic.get(event.semantic_key,-1e12)<profile['semantic_cooldown']: reason='semantic_cooldown'
            elif t-self.last_rule.get(event.rule_id,-1e12)<profile['cooldowns'][event.rule_id]: reason='rule_cooldown'
            elif t-self.last_global<profile['global_cooldown'] and not (event.priority==4 and self.last_priority<4): reason='global_cooldown'
            seen.add(event.semantic_key)
            if reason is None:
                self.last_global=t; self.last_priority=event.priority
                self.last_rule[event.rule_id]=t; self.last_semantic[event.semantic_key]=t
            decisions.append((event,reason))
        return decisions
