"""Google-first search plus bounded reads of explicitly permitted public sources."""
import html
from html.parser import HTMLParser
import ipaddress
import re
import socket
import tempfile
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import httpx
from .attachments import extract

SEARCH_URL='http://127.0.0.1:8788'

def public_url(url):
    try:
        p=urlsplit(url)
        if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password or p.port not in {None,80,443}:return False
        host=p.hostname.lower()
        if '.' not in host or host.endswith(('.localhost','.local','.internal','.test','.invalid')):return False
        try:return ipaddress.ip_address(host).is_global
        except ValueError:return True
    except (ValueError,TypeError):return False

def resolved_public(url):
    if not public_url(url):return False
    host=urlsplit(url).hostname
    try:addresses={row[4][0] for row in socket.getaddrinfo(host,None,type=socket.SOCK_STREAM)}
    except OSError:return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)

class _Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','noscript','svg'}:self.skip+=1
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript','svg'}:self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())

def read_url(url,max_bytes=2*1024**2):
    """Read a public HTML/PDF source with redirect, address, byte and time bounds."""
    current=url
    with httpx.Client(trust_env=False,timeout=15,follow_redirects=False,headers={'User-Agent':'Lumina local research reader/1.0'}) as client:
        for _ in range(4):
            if not resolved_public(current):raise ValueError('Source address is private, local, or could not be verified')
            with client.stream('GET',current,headers={'Accept':'text/html,application/pdf;q=0.9'}) as response:
                if response.status_code in {301,302,303,307,308}:
                    location=response.headers.get('location')
                    if not location:raise ValueError('Source redirect had no destination')
                    current=urljoin(current,location);continue
                response.raise_for_status();content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>max_bytes:raise ValueError('Source exceeded the 2MB research limit')
                mime=response.headers.get('content-type','').split(';')[0].lower()
            break
        else:raise ValueError('Source redirected too many times')
    if mime=='application/pdf' or current.lower().endswith('.pdf'):
        with tempfile.TemporaryDirectory(prefix='lumina-source-') as directory:
            path=Path(directory)/'source.pdf';path.write_bytes(bytes(content));result=extract(path,'pdf')
        text='\n'.join(section['location']+'\n'+section['text'] for section in result['sections'])
    elif mime in {'text/html','application/xhtml+xml','text/plain',''}:
        decoded=bytes(content).decode('utf-8','replace')
        if mime=='text/plain':text=decoded
        else:
            parser=_Text();parser.feed(decoded);text='\n'.join(parser.parts)
    else:raise ValueError('Source is not readable HTML, text, or PDF')
    text=re.sub(r'\s+',' ',text).strip()
    if len(text)<80:raise ValueError('Source did not contain enough readable text')
    passages=[text[offset:offset+1400] for offset in range(0,min(len(text),5600),1400)]
    return {'url':current,'content_type':mime or 'text/html','passages':passages}

def read_sources(results,limit=3):
    output=[]
    for result in results:
        item=dict(result)
        if len([row for row in output if row.get('passages')])<limit:
            try:item.update(read_url(item['url']))
            except Exception as exc:item['read_error']=str(exc)[:240]
        output.append(item)
    return output

def clean(text,limit):
    return html.unescape(re.sub('<[^>]*>','',str(text)))[:limit]

def relevant(query,result):
    # Reject obviously unrelated engine responses instead of grounding an answer in them.
    stop={'the','and','for','what','how','are','was','with','from','that','this','explain','about','www','com','site'}
    terms={w for w in re.findall(r'\w+',query.lower()) if len(w)>2 and w not in stop}
    words=set(re.findall(r'\w+',(result['title']+' '+result['snippet']+' '+result['url']).lower()))
    return not terms or len(terms & words)>=min(2,len(terms))

import logging
logging.basicConfig(filename='logs/search.log', level=logging.ERROR)
def search(query, limit=5):
    if not isinstance(query, str) or not 2 <= len(query) <= 240:
        raise ValueError('Search query must be 2–240 characters')

    warnings = []
    results = []
    engines_with_results = []

    with httpx.Client(trust_env=False, timeout=25) as client:
        for engines in ('google', 'yahoo,startpage', 'mwmbl,wikipedia', 'bing,duckduckgo'):
            try:
                response = client.get(SEARCH_URL + '/search', params={'q': query, 'format': 'json', 'engines': engines, 'language': 'en', 'safesearch': 1})
                response.raise_for_status()
                data = response.json()
                warnings.extend(str(e[0]) + ': ' + str(e[1]) for e in data.get('unresponsive_engines', []) if len(e) > 1)
                parsed_results = [{'title': clean(r.get('title', ''), 200), 'url': r['url'], 'snippet': clean(r.get('content', ''), 600),
                                  'engines': r.get('engines', [r.get('engine', engines)])}
                                 for r in data.get('results', []) if public_url(r.get('url', ''))][:limit]
                parsed_results = [r for r in parsed_results if relevant(query, r)]
                if parsed_results:
                    results.extend(parsed_results)
                    engines_with_results.append(engines.split(',')[0])  # Track the first successful engine
            except Exception as e:
                warnings.append(f'{engines}: {str(e)}')

    if results:
        if 'google' not in engines_with_results:
            warnings.append('Google was unavailable; used ' + ', '.join(sorted(engines_with_results)) + ' fallback.')
        return {'query': query, 'results': results, 'warnings': warnings}
    else:
        return {'query': query, 'results': [], 'warnings': ['No search results returned.']}
