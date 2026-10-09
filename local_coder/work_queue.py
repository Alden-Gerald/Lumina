"""Small persisted FIFO for model work that cannot start immediately."""
from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
import threading
import uuid


def _now():return datetime.datetime.now(datetime.timezone.utc).isoformat()


class WorkQueue:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock()
        if not self.path.exists():self._save({'version':1,'items':[]})
        else:
            data=self._load();changed=False
            for item in data['items']:
                if item['status']=='dispatching':item['status']='queued';changed=True
            if changed:self._save(data)

    def _load(self):
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('version')!=1 or not isinstance(data.get('items'),list):raise ValueError('Unsupported work queue format')
        return data

    def _save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.chmod(temporary,0o600);os.replace(temporary,self.path)

    def add(self,kind,payload,label):
        if kind not in {'chat','code'}:raise ValueError('Unknown queue work type')
        with self.lock:
            data=self._load();item={'id':uuid.uuid4().hex,'kind':kind,'label':str(label)[:120],
                'payload':payload,'status':'queued','created_at':_now(),'position':sum(row['status']=='queued' for row in data['items'])+1}
            data['items'].append(item);self._save(data);return self.public(item)

    @staticmethod
    def public(item):return {key:item.get(key) for key in ('id','kind','label','status','created_at','position','result_id','error')}

    def list(self):
        with self.lock:
            items=self._load()['items'];self._positions(items)
            return [self.public(item) for item in items if item['status'] in {'queued','dispatching','failed'}][-100:]

    @staticmethod
    def _positions(items):
        position=0
        for item in items:
            if item['status']=='queued':position+=1;item['position']=position
            else:item['position']=None

    def claim(self):
        with self.lock:
            data=self._load();item=next((row for row in data['items'] if row['status']=='queued'),None)
            if not item:return None
            item['status']='dispatching';item['started_at']=_now();self._save(data);return dict(item)

    def finish(self,item_id,result_id=None,error=None):
        with self.lock:
            data=self._load();item=next((row for row in data['items'] if row['id']==item_id),None)
            if not item:return
            item['status']='failed' if error else 'dispatched';item['result_id']=result_id;item['error']=str(error)[:500] if error else None;item['finished_at']=_now();self._positions(data['items']);self._save(data)

    def cancel(self,item_id):
        with self.lock:
            data=self._load();item=next((row for row in data['items'] if row['id']==item_id),None)
            if not item or item['status']!='queued':raise ValueError('Only queued work can be cancelled')
            item['status']='cancelled';item['finished_at']=_now();self._positions(data['items']);self._save(data);return {'cancelled':item_id}

    def move(self,item_id,direction):
        if direction not in {'up','down'}:raise ValueError('Queue direction must be up or down')
        with self.lock:
            data=self._load();queued=[row for row in data['items'] if row['status']=='queued'];index=next((i for i,row in enumerate(queued) if row['id']==item_id),None)
            if index is None:raise ValueError('Queued work not found')
            target=index+(-1 if direction=='up' else 1)
            if target<0 or target>=len(queued):return self.public(queued[index])
            first=data['items'].index(queued[index]);second=data['items'].index(queued[target]);data['items'][first],data['items'][second]=data['items'][second],data['items'][first]
            self._positions(data['items']);self._save(data);return self.public(queued[index])
