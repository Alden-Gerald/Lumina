"""Deterministic routing among installed, memory-bounded chat models."""
import re
from pathlib import Path
from .settings import PROFILES

CHAT_MODELS={
    'structured':{'profile':'roadmap','label':'Structured answer · 7B','thinking':False,'workflow':True,'ram_gib':8},
    'study':{'profile':'_chat','label':'Study · 14B','thinking':True,'ram_gib':12},
    'fast':{'profile':'_chat_fast','label':'Quick chat · 4B','thinking':True,'ram_gib':8},
    'coding':{'profile':'power','label':'Coding · 30B','thinking':False,'ram_gib':16},
    'code14':{'profile':'quality','label':'Coding · 14B','thinking':False,'ram_gib':8},
}

def available_ram_gib():
    fields=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(fields['MemAvailable'].split()[0])/1024**2

def choose(text,deep,selection='auto',installed=None,ram_gib=None,history_chars=0,has_documents=False,structured=False):
    if selection!='auto' and selection not in CHAT_MODELS:raise ValueError('Unknown chat model')
    names=set(installed) if installed is not None else {PROFILES[c['profile']]['model'] for c in CHAT_MODELS.values()}
    ram=available_ram_gib() if ram_gib is None else ram_gib
    viable=[k for k,c in CHAT_MODELS.items() if PROFILES[c['profile']]['model'] in names and ram>=c['ram_gib']]
    if selection!='auto':
        if selection not in viable:raise ValueError('Selected chat model is unavailable or needs more free RAM')
        chosen=selection;reason='Selected by you'
    else:
        coding=bool(re.search(r'\b(code|coding|debug|quickshell|qml|python|typescript|javascript|compiler|refactor)\b',text,re.I))
        simple=len(text)<500 and history_chars<1200 and bool(re.match(r'\s*(hi\b|hello\b|hey\b|thanks\b|thank you\b|translate\b)',text,re.I))
        preferred=['structured','study','fast'] if structured else ['study','fast'] if deep or has_documents else ['coding','code14','study','fast'] if coding else ['fast','study'] if simple else ['study','fast']
        chosen=next((k for k in preferred if k in viable),None)
        if chosen is None:raise ValueError('No suitable installed chat model fits the available RAM; close memory-heavy apps')
        reason=('Structured answer workflow requested' if structured else 'Deep Thinking requested' if deep else 'Study documents attached' if has_documents else 'Coding question' if coding else 'Short conversation or translation' if simple else 'Study or general question')
        if chosen!=preferred[0]:reason+='; using an available model within the RAM budget'
    config=CHAT_MODELS[chosen]
    return {'selection':selection,'choice':chosen,'profile':config['profile'],'model':PROFILES[config['profile']]['model'],
            'label':config['label'],'reason':reason,'thinking':bool(deep and config['thinking'])}
