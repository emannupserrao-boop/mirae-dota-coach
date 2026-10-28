import json
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from . import config
from .demo import payload
from .state import normalize
from .process import Detector


def show(value):
    return 'N/D' if value is None or value == '' else str(value)


def clock(value):
    if value is None:
        return 'N/D'
    n = abs(int(value))
    return ('-' if value < 0 else '') + f'{n//60:02d}:{n%60:02d}'


class Window:
    def __init__(self, root, service):
        self.root, self.service = root, service
        self.detector = Detector()
        self.last_rows = None
        self.demo_step = 0
        root.title('Dota AI Coach — Alpha 0.1' + (' — SIMULAÇÃO' if service.source == 'demo' else ''))
        root.geometry('1100x820')
        root.minsize(900, 700)
        root.protocol('WM_DELETE_WINDOW', self.close)
        outer = ttk.Frame(root, padding=12)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Dota AI Coach • Alpha 0.1', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        self.status = ttk.Label(outer, text='Aguardando GSI…', wraplength=1030)
        self.status.pack(fill='x', pady=6)
        self.notice = ttk.Label(outer, foreground='#a04a00', wraplength=1030)
        self.notice.pack(fill='x')
        bar = ttk.Frame(outer)
        bar.pack(fill='x', pady=6)
        ttk.Button(bar, text='Configurar GSI…', command=self.install).pack(side='left')
        ttk.Button(bar, text='Testar voz', command=self.test_voice).pack(side='left', padx=6)
        ttk.Button(bar, text='Exportar avaliações…', command=self.export).pack(side='left')
        ttk.Button(bar, text='Exportar diagnóstico…', command=self.diagnostic).pack(side='left', padx=6)
        settings = service.settings
        controls = ttk.LabelFrame(outer, text='Controles', padding=8)
        controls.pack(fill='x')
        self.coach = tk.BooleanVar(value=settings['coach'])
        self.voice = tk.BooleanVar(value=settings['voice'])
        self.volume = tk.IntVar(value=settings['volume'])
        self.frequency = tk.StringVar(value=settings['frequency'])
        ttk.Checkbutton(controls, text='Coach ON', variable=self.coach, command=self.apply).grid(row=0, column=0, sticky='w')
        ttk.Checkbutton(controls, text='Voz ON', variable=self.voice, command=self.apply).grid(row=0, column=1, sticky='w')
        ttk.Label(controls, text='Volume').grid(row=0, column=2)
        scale = ttk.Scale(controls, from_=0, to=100, variable=self.volume, length=160)
        scale.grid(row=0, column=3)
        scale.bind('<ButtonRelease-1>', lambda e: self.apply())
        scale.bind('<KeyRelease>', lambda e: self.apply())
        frequency = ttk.Combobox(controls, values=['frequente', 'normal', 'discreto'], textvariable=self.frequency, state='readonly', width=12)
        frequency.grid(row=0, column=4, padx=10)
        frequency.bind('<<ComboboxSelected>>', lambda e:self.apply())
        self.lh = tk.StringVar(value=str(settings['lh_per_minute']))
        self.target = tk.StringVar(value=settings['target_item'])
        self.cost = tk.StringVar(value=str(settings['target_remaining_cost']))
        ttk.Label(controls, text='Meta LH/min (0 desliga)').grid(row=1, column=0, sticky='w', pady=8)
        ttk.Entry(controls, textvariable=self.lh, width=8).grid(row=1, column=1)
        ttk.Label(controls, text='Item alvo (item_…)').grid(row=1, column=2)
        ttk.Entry(controls, textvariable=self.target, width=23).grid(row=1, column=3)
        ttk.Label(controls, text='Custo restante total').grid(row=1, column=4)
        ttk.Entry(controls, textvariable=self.cost, width=8).grid(row=1, column=5)
        ttk.Button(controls, text='Salvar', command=self.apply).grid(row=0, column=5, padx=10)
        board = ttk.LabelFrame(outer, text='Estado recebido • N/D = campo não enviado', padding=8)
        board.pack(fill='x', pady=8)
        self.values = {}
        fields = ['Tempo','Herói','Nível','LH','Denies','GPM','XPM','Gold','K/D/A','Buyback','Fase','Pausa']
        for i,name in enumerate(fields):
            r,c = divmod(i,3)
            frame = ttk.Frame(board)
            frame.grid(row=r, column=c, sticky='ew', padx=5, pady=3)
            board.columnconfigure(c, weight=1)
            ttk.Label(frame, text=name+': ', font=('Segoe UI',10,'bold')).pack(side='left')
            variable = tk.StringVar(value='N/D')
            self.values[name] = variable
            ttk.Label(frame, textvariable=variable).pack(side='left')
        tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        self.items = tk.Text(tabs, height=6, wrap='word', state='disabled')
        self.abilities = tk.Text(tabs, height=6, wrap='word', state='disabled')
        tabs.add(self.items, text='Itens / cooldowns')
        tabs.add(self.abilities, text='Habilidades / cooldowns')
        self.latest = ttk.Label(outer, text='Última recomendação: —', wraplength=1030, font=('Segoe UI',11,'bold'))
        self.latest.pack(fill='x', pady=8)
        ttk.Label(outer, text='Selecione uma recomendação no histórico para avaliar (últimas 100):').pack(anchor='w')
        self.history = ttk.Treeview(outer, columns=('source','text','rating','voice'), show='headings', height=7)
        for key,title,width in [('source','Origem',65),('text','Recomendação',700),('rating','Avaliação',85),('voice','Voz',110)]:
            self.history.heading(key, text=title)
            self.history.column(key, width=width, stretch=key=='text')
        self.history.pack(fill='both', expand=True)
        feedback = ttk.Frame(outer)
        feedback.pack(fill='x', pady=6)
        for rating in ('boa','ruim','irrelevante'):
            ttk.Button(feedback, text=rating.capitalize(), command=lambda v=rating:self.rate(v)).pack(side='left', padx=3)
        ttk.Label(outer, text=f'Dados locais: {service.directory}', wraplength=1030).pack(anchor='w')
        if service.source == 'demo':
            root.after(100, self.demo_tick)
        root.after(200, self.tick)

    def apply(self):
        try:
            settings = dict(self.service.settings)
            settings.update(coach=self.coach.get(), voice=self.voice.get(), volume=int(float(self.volume.get())),
                            frequency=self.frequency.get(), lh_per_minute=float(self.lh.get().replace(',','.')),
                            target_item=self.target.get().strip(), target_remaining_cost=int(self.cost.get()))
            config.save(self.service.directory, settings)
            self.service.update_settings(settings)
        except (ValueError, OSError, tk.TclError) as exc:
            messagebox.showerror('Configuração', str(exc))

    def install(self):
        path = filedialog.askdirectory(title='Selecione a pasta dota 2 beta (Steam → Dota 2 → Arquivos instalados → Explorar)')
        if not path:
            return
        try:
            dest = config.install_gsi(path, self.service.settings)
            messagebox.showinfo('GSI configurado', f'Criado:\n{dest}\n\nNa Steam, adicione às opções de inicialização:\n-gamestateintegration\n\nFeche e abra o Dota novamente.')
        except (ValueError, OSError) as exc:
            messagebox.showerror('GSI', str(exc))

    def test_voice(self):
        if not self.service.settings['voice']:
            messagebox.showinfo('Voz', 'Ative Voz ON primeiro.')
            return
        self.service.voice.say(None, 'Dota AI Coach pronto. Este é um teste de voz.', self.service.settings['volume'])

    def export(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='dota-coach-feedback.json', filetypes=[('JSON','*.json')])
        if path:
            try:
                self.service.store.export(path)
                messagebox.showinfo('Exportado', 'Recomendações, estados e avaliações exportados.')
            except OSError as exc:
                messagebox.showerror('Exportação', str(exc))

    def rate(self, rating):
        selected = self.history.selection()
        if not selected:
            messagebox.showinfo('Avaliação', 'Selecione uma recomendação na lista.')
            return
        self.service.store.rate(int(selected[0]), rating)

    def diagnostic(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='dota-coach-diagnostic.json', filetypes=[('JSON','*.json')])
        if path:
            try:
                self.service.export_diagnostic(path)
                messagebox.showinfo('Diagnóstico', 'Estado e status exportados, sem token ou Steam ID.')
            except OSError as exc:
                messagebox.showerror('Diagnóstico', str(exc))

    def replace_text(self, widget, text):
        widget.configure(state='normal')
        widget.delete('1.0','end')
        widget.insert('1.0',text)
        widget.configure(state='disabled')

    def tick(self):
        try:
            snap = self.service.snapshot()
            s = snap['state']
            process = {True:'SIM', False:'NÃO', None:'N/D'}[self.detector.detected]
            mode = 'SIMULAÇÃO — NÃO comprova GSI real' if self.service.source=='demo' else 'LIVE'
            age = 'nunca' if snap['age'] is None else f"{snap['age']:.1f}s atrás"
            self.status.configure(text=f"{mode} | Dota detectado: {process} | GSI: {'CONECTADO' if snap['connected'] else 'AGUARDANDO / SEM SINAL'} | Pacotes: {snap['packets']} | Último: {age}\nReceptor: 127.0.0.1:{self.service.settings['port']} | Voz: {snap['voice_status'] or 'pronta'}")
            reason = snap['error'] or ('Dados antigos; coaching suspenso até o próximo pacote.' if snap['age'] is not None and not snap['connected'] else ('Sem jogador local elegível: menu/espectador ou campos ausentes.' if snap['connected'] and not s.local else ''))
            self.notice.configure(text=reason)
            vals = {'Tempo':clock(s.time), 'Herói':s.hero.removeprefix('npc_dota_hero_'), 'Nível':s.level,
                    'LH':s.lh,'Denies':s.denies,'GPM':s.gpm,'XPM':s.xpm,'Gold':s.gold,
                    'K/D/A':' / '.join(show(v) for v in (s.kills,s.deaths,s.assists)),
                    'Buyback':{True:'Ouro + CD prontos',False:'Sem ouro / CD',None:'N/D'}[s.buyback],
                    'Fase':s.phase.removeprefix('DOTA_GAMERULES_STATE_'),'Pausa':'SIM' if s.paused else 'NÃO'}
            for k,v in vals.items():
                self.values[k].set(show(v))
            self.replace_text(self.items, json.dumps(s.items, ensure_ascii=False, indent=2))
            self.replace_text(self.abilities, json.dumps(s.abilities, ensure_ascii=False, indent=2))
            self.latest.configure(text='Última recomendação: '+(snap['last_advice'] or '—'))
            rows = self.service.store.recent()
            if rows != self.last_rows:
                selected = self.history.selection()
                self.history.delete(*self.history.get_children())
                for rid, created, source, text, rating, voice in rows:
                    self.history.insert('', 'end', iid=str(rid), values=(source,text,rating or '—',voice))
                if selected and self.history.exists(selected[0]):
                    self.history.selection_set(selected[0])
                self.last_rows = rows
        except Exception:
            logging.exception('Falha na atualização do painel')
            self.notice.configure(text='Erro no painel; consulte app.log.')
        self.root.after(500, self.tick)

    def demo_tick(self):
        t = 300 + self.demo_step * 5
        data = payload(t=t, lh=10 if self.demo_step < 22 else int(t/60*5))
        if self.demo_step >= 35:
            data['items']['slot1'] = {'name':'item_bfury', 'cooldown':0}
        self.service.ingest(normalize(data))
        self.demo_step += 1
        self.root.after(1000, self.demo_tick)

    def close(self):
        self.detector.close()
        self.service.close()
        self.root.destroy()
