import copy
import ctypes
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from coach.process import Detector
from coach.ui import clock,show
from . import config
from .vision import capture_roi,ROLES

class Window:
    def __init__(self,root,service):
        self.root=root; self.s=service; self.detector=Detector(); self.tasks=queue.Queue()
        self.displayed_id=None; self.latest_rule=None; self.image=None; self.frame=None; self.corner=None
        self.closing=False; self.last_rows=None; self.busy_export=False
        root.title('Dota AI Coach — Alpha 0.2 — '+service.mode)
        root.geometry('1120x850'); root.minsize(950,720); root.protocol('WM_DELETE_WINDOW',self.close)
        base=ttk.Frame(root,padding=10); base.pack(fill='both',expand=True)
        color='#ad4600' if service.test_mode else '#16603a'
        ttk.Label(base,text='ALPHA 0.2 — '+('TEST MODE • SOMENTE BOTS' if service.test_mode else 'NORMAL MODE • Vision desligado'),
                  font=('Segoe UI',17,'bold'),foreground=color).pack(anchor='w')
        self.status=ttk.Label(base,wraplength=1050); self.status.pack(fill='x',pady=5)
        self.error=ttk.Label(base,foreground='#b03020',wraplength=1050); self.error.pack(fill='x')
        bar=ttk.Frame(base); bar.pack(fill='x',pady=5)
        for text,fn in [('Configurar GSI 0.2…',self.install),('Testar voz',self.test_voice),('Exportar diagnóstico + avaliações…',self.export),('Parâmetros…',self.parameters)]:
            ttk.Button(bar,text=text,command=fn).pack(side='left',padx=3)
        controls=ttk.Frame(base); controls.pack(fill='x',pady=6)
        self.coach=tk.BooleanVar(value=service.settings['coach']); self.voice=tk.BooleanVar(value=service.settings['voice'])
        self.volume=tk.DoubleVar(value=service.settings['volume']); self.frequency=tk.StringVar(value=service.settings['frequency'])
        self.goal=tk.StringVar(value=str(service.settings['lh_per_minute']))
        ttk.Checkbutton(controls,text='Coach ON',variable=self.coach,command=self.apply).pack(side='left')
        ttk.Checkbutton(controls,text='Voz ON',variable=self.voice,command=self.apply).pack(side='left',padx=10)
        ttk.Label(controls,text='Volume').pack(side='left')
        volume=ttk.Scale(controls,from_=0,to=100,variable=self.volume,length=140); volume.pack(side='left')
        volume.bind('<ButtonRelease-1>',lambda e:self.apply()); volume.bind('<KeyRelease>',lambda e:self.apply())
        frequency=ttk.Combobox(controls,textvariable=self.frequency,values=['frequente','normal','discreto'],state='readonly',width=11)
        frequency.pack(side='left',padx=10); frequency.bind('<<ComboboxSelected>>',lambda e:self.apply())
        ttk.Label(controls,text='Meta LH/min (0 = tendência)').pack(side='left')
        ttk.Entry(controls,textvariable=self.goal,width=6).pack(side='left',padx=5)
        ttk.Button(controls,text='Salvar',command=self.apply).pack(side='left')
        self.latest=ttk.Label(base,text='Última recomendação: —',font=('Segoe UI',11,'bold'),wraplength=1050)
        self.latest.pack(fill='x',pady=5)
        rating=ttk.Frame(base); rating.pack(fill='x')
        ttk.Label(rating,text='Avaliar a última ID exibida:').pack(side='left')
        for value in ('boa','ruim','irrelevante'):
            ttk.Button(rating,text=value.capitalize(),command=lambda r=value:self.rate_last(r)).pack(side='left',padx=3)
        self.ack=ttk.Label(rating); self.ack.pack(side='left',padx=8)
        book=ttk.Notebook(base); book.pack(fill='both',expand=True,pady=8)
        data=ttk.Frame(book,padding=8); book.add(data,text='Estado / Histórico')
        vision=ttk.Frame(book,padding=8); book.add(vision,text='Minimapa — EXPERIMENTAL')
        debug=ttk.Frame(book,padding=8); book.add(debug,text='Diagnóstico / Regras')
        self.board=ttk.Label(data,font=('Consolas',11),wraplength=1040); self.board.pack(fill='x')
        self.inventory=tk.Text(data,height=8,wrap='word'); self.inventory.pack(fill='both',expand=True,pady=5)
        ttk.Label(data,text='Histórico persistido (selecione uma linha para avaliar uma recomendação anterior):').pack(anchor='w')
        self.history=ttk.Treeview(data,columns=('id','mode','rule','text','voice','rating'),show='headings',height=6)
        for key,title,width in [('id','ID',45),('mode','Modo',50),('rule','Regra',155),('text','Texto',460),('voice','Voz',100),('rating','Avaliação',85)]:
            self.history.heading(key,text=title); self.history.column(key,width=width,stretch=key=='text')
        self.history.pack(fill='both',expand=True)
        rb=ttk.Frame(data); rb.pack(fill='x')
        for value in ('boa','ruim','irrelevante'):
            ttk.Button(rb,text='Selecionada: '+value,command=lambda r=value:self.rate_selected(r)).pack(side='left',padx=3)
        self.debug=tk.Text(debug,wrap='word'); self.debug.pack(fill='both',expand=True)
        self.build_vision(vision)
        ttk.Label(base,text=f'Dados 0.2: {service.directory}',wraplength=1050).pack(anchor='w')
        root.after(200,self.tick)
    def apply(self):
        try:
            c=copy.deepcopy(self.s.settings)
            c.update(coach=self.coach.get(),voice=self.voice.get(),volume=int(self.volume.get()),frequency=self.frequency.get(),lh_per_minute=float(self.goal.get().replace(',','.')))
            if self.s.update_settings(c): self.ack.configure(text='Configuração enviada.')
        except (ValueError,KeyError,TypeError) as exc: messagebox.showerror('Configuração',str(exc))
    def install(self):
        path=filedialog.askdirectory(title='Selecione a pasta dota 2 beta')
        if path:
            try:
                dest=config.install_gsi(path,self.s.settings)
                messagebox.showinfo('GSI 0.2',f'Criado: {dest}\n\nPorta 32124 por padrão. Mantenha -gamestateintegration e reinicie o Dota.\nO arquivo do Alpha 0.1 foi preservado.')
            except Exception as exc: messagebox.showerror('GSI',str(exc))
    def test_voice(self):
        if not self.s.test_voice(): messagebox.showinfo('Voz','Ative Voz ON e aguarde um instante.')
    def rate_last(self,rating):
        if self.displayed_id is None: messagebox.showinfo('Avaliação','Ainda não há recomendação nesta sessão.'); return
        rid=self.displayed_id
        if self.s.rate(rid,rating): self.ack.configure(text=f'Avaliação enviada para ID {rid}: {rating}')
    def rate_selected(self,rating):
        selection=self.history.selection()
        if selection:
            rid=int(selection[0]); self.s.rate(rid,rating); self.ack.configure(text=f'ID {rid}: {rating}')
    def export(self):
        if self.busy_export: return
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='dota-coach-alpha02-diagnostic.json')
        if not path: return
        self.busy_export=True
        def work():
            try: self.s.export(path); self.tasks.put(('info','Exportado','Diagnóstico e avaliações salvos.'))
            except Exception as exc: self.tasks.put(('error','Exportação',str(exc)))
            finally: self.busy_export=False
        threading.Thread(target=work,daemon=True).start()
    def parameters(self):
        win=tk.Toplevel(self.root); win.title('Parâmetros — alterações reiniciam baselines das regras'); win.geometry('850x700')
        ttk.Label(win,text='Normal e Test têm perfis separados. Prioridades: 1 baixa, 2 normal, 3 alta, 4 crítica.',wraplength=800).pack()
        text=tk.Text(win); text.pack(fill='both',expand=True)
        keys=('important_items','priorities','normal','test','vision')
        text.insert('1.0',json.dumps({k:self.s.settings[k] for k in keys},indent=2,ensure_ascii=False))
        def save():
            try:
                patch=json.loads(text.get('1.0','end'))
                if set(patch)!=set(keys): raise ValueError('Mantenha as cinco seções originais.')
                c=copy.deepcopy(self.s.settings); c.update(patch)
                if self.s.update_settings(c): win.destroy()
            except (ValueError,KeyError,TypeError) as exc: messagebox.showerror('Parâmetros',str(exc),parent=win)
        ttk.Button(win,text='Salvar parâmetros',command=save).pack(pady=5)
    def build_vision(self,parent):
        ttk.Label(parent,text='EXPERIMENTAL — BOT TEST ONLY. Pixels do minimapa; papéis atribuídos manualmente. Não usar em ranked.',foreground='#ad4600',wraplength=1040).pack(anchor='w')
        coords=ttk.Frame(parent); coords.pack(fill='x',pady=5)
        self.roi=[tk.StringVar(value=str(v)) for v in self.s.settings['vision']['roi']]
        for title,var in zip(('X','Y','Largura','Altura'),self.roi):
            ttk.Label(coords,text=title).pack(side='left'); ttk.Entry(coords,textvariable=var,width=6).pack(side='left',padx=3)
        ttk.Button(coords,text='Canto 1 em 5s',command=lambda:self.get_corner(1)).pack(side='left',padx=3)
        ttk.Button(coords,text='Canto 2 em 5s',command=lambda:self.get_corner(2)).pack(side='left',padx=3)
        ttk.Button(coords,text='Capturar ROI em 5s',command=self.capture).pack(side='left',padx=3)
        opts=ttk.Frame(parent); opts.pack(fill='x')
        self.role=tk.StringVar(value='enemy_mid'); self.fps=tk.StringVar(value=str(self.s.settings['vision']['fps']))
        ttk.Combobox(opts,textvariable=self.role,values=ROLES,state='readonly',width=24).pack(side='left')
        ttk.Label(opts,text='Selecione papel e arraste um retângulo JUSTO sobre o ícone na amostra.').pack(side='left',padx=5)
        ttk.Combobox(opts,textvariable=self.fps,values=['5','10','15'],state='readonly',width=4).pack(side='left')
        self.bot=tk.BooleanVar(value=False)
        ttk.Checkbutton(parent,text='Confirmo que estou em uma partida SOLO contra bots (esta confirmação não é salva).',variable=self.bot).pack(anchor='w',pady=3)
        controls=ttk.Frame(parent); controls.pack(fill='x')
        ttk.Button(controls,text='Ativar visão calibrada',command=self.activate_vision).pack(side='left')
        ttk.Button(controls,text='Desativar visão',command=lambda:self.s.vision.disable()).pack(side='left',padx=5)
        ttk.Button(controls,text='Marcar falso positivo',command=lambda:self.mark_vision('false_positive')).pack(side='left')
        ttk.Button(controls,text='Marcar falso negativo',command=lambda:self.mark_vision('false_negative')).pack(side='left',padx=5)
        self.vision_note=ttk.Label(parent,text='Vision DISABLED. ROI máximo 600×600; capture somente o minimapa.',wraplength=1040)
        self.vision_note.pack(fill='x',pady=5)
        pane=ttk.Panedwindow(parent,orient='horizontal'); pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane); right=ttk.Frame(pane); pane.add(left,weight=1); pane.add(right,weight=1)
        self.canvas=tk.Canvas(left,width=420,height=420,bg='#222')
        sx=ttk.Scrollbar(left,orient='horizontal',command=self.canvas.xview)
        sy=ttk.Scrollbar(left,orient='vertical',command=self.canvas.yview)
        sx.pack(side='bottom',fill='x'); sy.pack(side='right',fill='y')
        self.canvas.pack(fill='both',expand=True)
        self.canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        self.canvas.bind('<ButtonPress-1>',self.drag_start); self.canvas.bind('<B1-Motion>',self.drag_move); self.canvas.bind('<ButtonRelease-1>',self.drag_end)
        self.vision_debug=tk.Text(right,width=48,wrap='word'); self.vision_debug.pack(fill='both',expand=True)
        self.rect=None; self.drag=None
    def get_corner(self,which):
        if os.name!='nt': messagebox.showerror('ROI','Calibração de tela disponível no Windows.'); return
        self.vision_note.configure(text=f'Em 5s, o cursor marcará canto {which}. Volte ao Dota e posicione no minimapa.')
        def read():
            from ctypes import wintypes
            pt=wintypes.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            if which==1:
                self.corner=(pt.x,pt.y); self.roi[0].set(pt.x); self.roi[1].set(pt.y)
            elif self.corner:
                self.roi[2].set(pt.x-self.corner[0]); self.roi[3].set(pt.y-self.corner[1])
            self.vision_note.configure(text=f'Canto {which} registrado. Volte ao painel.')
        self.root.after(5000,read)
    def vision_config(self):
        c=copy.deepcopy(self.s.settings)
        roi=[int(v.get()) for v in self.roi]
        if roi!=c['vision']['roi']: c['vision']['roles']={}
        c['vision']['roi']=roi; c['vision']['fps']=int(self.fps.get())
        config.validate(c); return c
    def capture(self):
        if not self.s.test_mode or not self.bot.get(): messagebox.showinfo('Vision','Abra Start-Bot-Test.cmd e confirme partida solo com bots.'); return
        try: c=self.vision_config()
        except (ValueError,KeyError,TypeError) as exc: messagebox.showerror('ROI',str(exc)); return
        self.s.update_settings(c); self.s.vision.disable('Calibração em andamento.')
        self.vision_note.configure(text='Captura em 5s: volte ao Dota. Depois retorne ao painel para selecionar o ícone.')
        def capture_background():
            try:
                frame,latency=capture_roi(c['vision']['roi']); self.tasks.put(('capture',frame,latency))
            except Exception as exc: self.tasks.put(('error','Captura',str(exc)))
        self.root.after(5000,lambda:threading.Thread(target=capture_background,daemon=True).start())
    def drag_start(self,event):
        if self.frame is None: return
        event.x=int(self.canvas.canvasx(event.x)); event.y=int(self.canvas.canvasy(event.y))
        self.drag=(event.x,event.y)
        if self.rect: self.canvas.delete(self.rect)
        self.rect=self.canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='yellow',width=2)
    def drag_move(self,event):
        event.x=int(self.canvas.canvasx(event.x)); event.y=int(self.canvas.canvasy(event.y))
        if self.drag: self.canvas.coords(self.rect,*self.drag,event.x,event.y)
    def drag_end(self,event):
        if not self.drag or self.frame is None: return
        event.x=int(self.canvas.canvasx(event.x)); event.y=int(self.canvas.canvasy(event.y))
        x0,y0=self.drag; self.drag=None
        x,y=min(x0,event.x),min(y0,event.y); w,h=abs(event.x-x0),abs(event.y-y0)
        role=self.role.get()
        try:
            c=self.vision_config(); c['vision']['roles'][role]=[x,y,w,h]; config.validate(c)
            patch=self.frame[y:y+h,x:x+w].copy()
            if patch.size==0 or patch.std()<10: raise ValueError('Recorte sem detalhe suficiente. Escolha o ícone do herói.')
            import cv2
            ok,encoded=cv2.imencode('.png',patch)
            if not ok: raise ValueError('Falha ao salvar recorte')
            (self.s.directory/(role+'.png')).write_bytes(encoded.tobytes())
            self.s.update_settings(c)
            self.vision_note.configure(text=f'{role} calibrado ({w}×{h}). Repita para os outros papéis; novas amostras não apagam os já calibrados.')
        except (ValueError,KeyError,TypeError,OSError) as exc: messagebox.showerror('Ícone',str(exc))
    def activate_vision(self):
        if not self.bot.get(): messagebox.showinfo('Vision','Confirme partida solo com bots.'); return
        try:
            c=self.vision_config()
            if c['vision']!=self.s.settings['vision']:
                self.s.update_settings(c)
                self.vision_note.configure(text='Configuração enviada. Aguarde um instante e clique Ativar novamente.'); return
            self.s.vision.activate(c['vision'],self.s.test_mode)
            self.vision_note.configure(text='Vision ativo. Volte ao Dota e despause; Alt+Tab suspende captura e reinicia tracking.')
        except Exception as exc: messagebox.showerror('Vision',str(exc))
    def mark_vision(self,label):
        self.s.command('mark_vision',dict(label=label,latest_recommendation_id=self.displayed_id if self.latest_rule=='enemy_missing_v1' else None,
                                        vision=self.s.vision.snapshot(),game_time=self.s.snapshot()['state'].time))
        self.vision_note.configure(text='Marcação registrada: '+label)
    @staticmethod
    def text(widget,value):
        widget.configure(state='normal'); widget.delete('1.0','end'); widget.insert('1.0',value); widget.configure(state='disabled')
    def tick(self):
        if self.closing: return
        try:
            while True:
                try: task=self.tasks.get_nowait()
                except queue.Empty: break
                if task[0]=='capture':
                    from PIL import Image,ImageTk
                    self.frame=task[1]; self.image=ImageTk.PhotoImage(Image.fromarray(self.frame[:,:,::-1]))
                    self.canvas.delete('all'); self.canvas.create_image(0,0,image=self.image,anchor='nw')
                    self.canvas.configure(scrollregion=(0,0,self.frame.shape[1],self.frame.shape[0])); self.rect=None
                    self.vision_note.configure(text=f'AMOSTRA ESTÁTICA • captura {task[2]:.1f} ms. Selecione um papel e recorte seu ícone.')
                elif task[0]=='error': messagebox.showerror(task[1],task[2])
                else: messagebox.showinfo(task[1],task[2])
            snap=self.s.snapshot(); s=snap['state']; perf=self.s.performance.report(); vision=self.s.vision.snapshot()
            latest_perf=perf['latest']
            self.status.configure(text=f"LIVE | Dota: { {True:'SIM',False:'NÃO',None:'N/D'}[self.detector.detected] } | GSI: {'CONECTADO' if snap['connected'] else 'SEM SINAL'} | Pacotes {snap['packets']} | Rejeitados {snap['rejected']} | Fila descartados {snap['dropped']}\nVoz: {snap['voice_status']} | RAM app+TTS: {latest_perf.get('ram_mb',0):.1f} MB | CPU máquina: {latest_perf.get('cpu_percent_machine',0):.2f}% | {vision.get('status')}")
            self.error.configure(text=snap['error'])
            self.board.configure(text=f"Herói: {show(s.hero)}    Tempo: {clock(s.time)}    Nível: {show(s.level)}\nLH: {show(s.lh)}  Denies: {show(s.denies)}  GPM: {show(s.gpm)}  XPM: {show(s.xpm)}  Gold: {show(s.gold)}\nK/D/A: {show(s.kills)}/{show(s.deaths)}/{show(s.assists)}   Buyback (ouro/CD): {show(s.buyback)}   Pausa: {s.paused}\nBuyback custo: {show(s.buyback_cost)}  cooldown: {show(s.buyback_cooldown)}")
            self.text(self.inventory,json.dumps(dict(items=s.items,abilities=s.abilities),indent=2,ensure_ascii=False))
            latest=snap['latest']; self.displayed_id=latest['id'] if latest else None; self.latest_rule=latest['rule_id'] if latest else None
            self.latest.configure(text=f"Última #{latest['id']} • {latest['rule_id']} • P{latest['priority']}: {latest['text']}" if latest else 'Última recomendação desta sessão: —')
            if self.last_rows!=snap['rows']:
                selected=self.history.selection(); self.history.delete(*self.history.get_children())
                for row in snap['rows']:
                    self.history.insert('','end',iid=str(row['id']),values=(row['id'],row['mode'],row['rule_id'],row['text'],row['voice_status'],row['rating'] or '—'))
                if selected and self.history.exists(selected[0]): self.history.selection_set(selected[0])
                self.last_rows=snap['rows']
            self.text(self.debug,json.dumps(dict(engine=snap['engine_debug'],performance=perf,teamfight='UNSUPPORTED',session=snap['session_id'],mode=snap['mode']),indent=2,ensure_ascii=False))
            self.text(self.vision_debug,json.dumps(vision,indent=2,ensure_ascii=False))
        except Exception as exc:
            self.error.configure(text='Painel: '+type(exc).__name__+': '+str(exc))
        self.root.after(500,self.tick)
    def close(self):
        if self.busy_export: messagebox.showinfo('Exportação','Aguarde a exportação terminar antes de fechar.'); return
        self.closing=True; self.detector.close(); self.s.close(); self.root.destroy()
