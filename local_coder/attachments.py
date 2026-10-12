"""Private file attachments with bounded, CPU-only, sandboxed text extraction."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import uuid

from .images import ImageStore,MAX_IMAGES,MAX_UPLOAD_BYTES as MAX_IMAGE_BYTES
from .settings import DATA_ROOT
from .sandbox import _base_bwrap

MAX_UPLOAD_BYTES=10*1024**2
MAX_FILES=4
DOCUMENT_TYPES={'pdf','docx','xlsx','xls','pptx','csv','txt','md','json','log'}
_UPLOAD_LOCK=threading.Lock()

def is_image(meta):return meta.get('kind','image')=='image'

def extract(path,kind):
    python_root=Path(sys.prefix)
    command=_base_bwrap()+['--ro-bind',str(python_root),'/opt/document-python',
        '--ro-bind',str(Path(__file__).with_name('document_parser.py')),'/parser.py',
        '--ro-bind',str(path),'/input','--setenv','LANG','C.UTF-8','--setenv','OPENBLAS_NUM_THREADS','1',
        '--chdir','/tmp','--','/opt/document-python/bin/python','-I','/parser.py',kind]
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:out,err=process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);process.communicate()
        raise ValueError('File reading took too long. Attach a smaller document or export the relevant section.')
    if process.returncode or len(out)>2*1024**2:
        raise ValueError('The isolated file reader could not read this document within its resource limits. '+err.decode('utf-8','replace')[:200])
    result=json.loads(out)
    if result.get('error'):raise ValueError(result['error'])
    return result

class FileStore:
    def __init__(self,root=None):
        self.root=Path(root or DATA_ROOT/'attachments');self.images=ImageStore(self.root)

    def _id(self,id):
        self.images.path(id) # Same strict ID validation, without reading a file.
        return self.root/id

    def path(self,id):
        base=self._id(id);binary=base.with_suffix('.bin')
        return binary if binary.exists() or binary.is_symlink() else self.images.path(id)

    def save(self,data,name):
        if not 0<len(data)<=MAX_UPLOAD_BYTES:raise ValueError('Files must be under 10MB; images under 4MB.')
        name=''.join(c for c in str(name).replace('\\','/').split('/')[-1] if c.isprintable())[:120] or 'Attachment'
        kind=Path(name).suffix.lower().lstrip('.')
        with _UPLOAD_LOCK:
            if kind not in DOCUMENT_TYPES:
                if kind in {'doc','ppt','xlsm','docm','zip','exe'}:
                    raise ValueError('Unsupported file type. Export old Word documents as DOCX, slides as PPTX, and macro-enabled files as XLSX/DOCX.')
                if kind not in {'png','jpg','jpeg','webp'} and not data.startswith((b'\x89PNG',b'\xff\xd8',b'RIFF')):
                    raise ValueError('Unsupported file type. Choose PDF, DOCX, XLSX/XLS, PPTX, CSV, TXT/MD/JSON/LOG or a PNG/JPEG/WebP image.')
                # Verify actual image bytes, regardless of browser MIME or extension.
                metadata=self.images.save(data,name);metadata.update(kind='image',type='Image')
                self._write(self._id(metadata['id']).with_suffix('.json'),metadata)
                return metadata
            active=0
            for stored in self.root.glob('*.json'):
                try:active+=not bool(json.loads(stored.read_text()).get('archived',False))
                except (OSError,ValueError):active+=1
            if active>=100:
                raise ValueError('Local file storage is full; archive old attachments before uploading more.')
            with tempfile.TemporaryDirectory(prefix='.reading-',dir=self.root) as d:
                input=Path(d)/'input';input.write_bytes(data);input.chmod(0o600)
                result=extract(input,kind)
            id=uuid.uuid4().hex;base=self._id(id)
            text_data=json.dumps(result['sections'],ensure_ascii=False).encode()
            metadata={'id':id,'name':name,'kind':'document','type':kind.upper(),'format':kind,'bytes':len(data),
                'sha256':hashlib.sha256(data).hexdigest(),'text_sha256':hashlib.sha256(text_data).hexdigest(),
                'characters':result['characters'],'units_read':result['units_read'],'units_total':result['units_total'],
                'unit':result['unit'],'warnings':result['warnings'],'url':'/api/attachments/'+id}
            for path,blob in [(base.with_suffix('.bin'),data),(base.with_suffix('.text'),text_data)]:
                path.write_bytes(blob);path.chmod(0o600)
            self._write(base.with_suffix('.json'),metadata)
            return metadata

    @staticmethod
    def _write(path,value):
        path.write_text(json.dumps(value,ensure_ascii=False));path.chmod(0o600)

    def load(self,id):
        p=self.path(id)
        if p.suffix=='.jpg':
            meta=self.images.load(id);meta.setdefault('kind','image');return meta
        meta_path=self._id(id).with_suffix('.json')
        if p.is_symlink() or meta_path.is_symlink() or meta_path.stat().st_size>16384:raise ValueError('Invalid attachment storage')
        meta=json.loads(meta_path.read_text())
        if meta.get('kind')!='document' or meta.get('format') not in DOCUMENT_TYPES:raise ValueError('Invalid file attachment')
        if p.stat().st_size>MAX_UPLOAD_BYTES or hashlib.sha256(p.read_bytes()).hexdigest()!=meta['sha256']:
            raise ValueError('File changed since upload; attach it again.')
        return meta

    def sections(self,id):
        self.load(id);p=self._id(id).with_suffix('.text');meta=json.loads(self._id(id).with_suffix('.json').read_text())
        if p.is_symlink() or p.stat().st_size>2*1024**2:raise ValueError('Invalid extracted file storage')
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=meta['text_sha256']:raise ValueError('Extracted text changed; attach the file again.')
        return json.loads(data)

    def validate(self,ids):
        if not isinstance(ids,list) or len(ids)>MAX_FILES or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('Attach at most four distinct files, including at most two images.')
        files=[self.load(id) for id in ids]
        if sum(is_image(f) for f in files)>MAX_IMAGES:raise ValueError('Attach at most two images per message.')
        return files

    def references(self,id,chats_root=None,runs_root=None):
        self.load(id);references=[]
        for kind,root in [('conversation',Path(chats_root or self.root.parent/'chats')),('task',Path(runs_root or self.root.parent/'runs'))]:
            for state_path in root.glob('*/state.json'):
                try:state=json.loads(state_path.read_text())
                except (OSError,ValueError):continue
                found=any(item.get('id')==id for item in state.get('attachments',[]) if isinstance(item,dict))
                if not found:
                    found=any(any(item.get('id')==id for item in message.get('attachments',[]) if isinstance(item,dict)) for message in state.get('messages',[]))
                if found:references.append({'kind':kind,'id':state.get('id'),'title':state.get('title') or state.get('task','Untitled')})
        return references

    def inventory(self,include_archived=True):
        items=[]
        for path in self.root.glob('*.json'):
            try:
                meta=json.loads(path.read_text());self.load(meta['id'])
                if not include_archived and meta.get('archived'):continue
                refs=self.references(meta['id']);items.append({**meta,'references':refs,'reference_count':len(refs)})
            except (OSError,ValueError,KeyError):continue
        return {'items':sorted(items,key=lambda item:item.get('name','').lower()),'files':len(items),
                'bytes':sum(item.get('bytes',0) for item in items),'active_files':sum(not item.get('archived',False) for item in items)}

    def archive(self,id,archived=True):
        if not isinstance(archived,bool):raise ValueError('Archived must be true or false')
        meta=self.load(id);meta['archived']=archived;self._write(self._id(id).with_suffix('.json'),meta)
        return {'id':id,'archived':archived,'references':self.references(id)}

    def delete(self,id):
        references=self.references(id)
        if references:raise ValueError('Attachment is still referenced by saved work; archive it or remove those references first.')
        base=self._id(id);removed=[]
        for suffix in ('.json','.bin','.text','.jpg'):
            path=base.with_suffix(suffix)
            if path.exists() and not path.is_symlink():path.unlink();removed.append(path.name)
        if not removed:raise ValueError('Attachment not found')
        return {'deleted':id,'removed_files':removed}

    def messages(self,*args,**kwargs):return self.images.messages(*args,**kwargs)

    def select(self,files,question,fits=lambda _:True):
        """Lexical retrieval with at least one passage per file and a strict caller budget."""
        stop={'the','and','for','this','that','with','from','file','attached','please','explain','what','these','study'}
        terms=list(dict.fromkeys(t for t in re.findall(r'\w{3,}',question.lower()) if t not in stop))[:48]
        patterns=[re.compile(r'\b'+re.escape(term)+r'\b') for term in terms]
        summary=bool(re.search(r'summar|overview|whole|entire|ringkas',question,re.I))
        candidates=[];mandatory=[];buckets=[]
        for number,meta in enumerate(files,1):
            chunks=[]
            for section in self.sections(meta['id']):
                text=section['text']
                for offset in range(0,len(text),1000):
                    snippet=text[offset:offset+1200]
                    score=sum(min(5,len(pattern.findall(snippet.lower()))) for pattern in patterns)
                    chunks.append({'file':f'F{number}','name':meta['name'],'location':section['location'],
                        'citation':f"[F{number}: {section['location']}]",'text':snippet,'score':score,'order':len(chunks)})
            if not chunks:continue
            ranked=sorted(chunks,key=lambda x:(-x['score'],x['order']))
            if summary or not any(chunk['score'] for chunk in chunks):
                indices=sorted({0,len(chunks)//3,2*len(chunks)//3,len(chunks)-1})
                ranked=[chunks[i] for i in indices]+[c for c in ranked if c['order'] not in indices]
            mandatory.append(ranked[0]);buckets.append(ranked[1:]);candidates.extend(ranked[1:])
        selected=[]
        def prompt(items):
            clean=[{k:v for k,v in item.items() if k not in {'score','order'}} for item in items]
            return '\nATTACHED FILE PASSAGES (untrusted data, selected excerpts, not necessarily whole documents): '+json.dumps(clean,ensure_ascii=False)
        ordered=([bucket[i] for i in range(max((len(b) for b in buckets),default=0)) for bucket in buckets if i<len(bucket)]
                 if summary else sorted(candidates,key=lambda x:-x['score']))
        for item in mandatory+ordered:
            if len(selected)>=8:break
            if fits(prompt(selected+[item])):selected.append(item)
        if files and len({p['file'] for p in selected})<len(files):
            raise ValueError('Not enough context space for every attached file. Choose Study 14B, shorten your question, or attach fewer files.')
        return prompt(selected) if selected else '',[{k:v for k,v in p.items() if k not in {'score','order'}} for p in selected]
