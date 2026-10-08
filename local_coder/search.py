"""Google-first search through our loopback SearXNG; never fetch arbitrary URLs."""
import html
import ipaddress
import re
from urllib.parse import urlsplit
import httpx

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

def clean(text,limit):
    return html.unescape(re.sub('<[^>]*>','',str(text)))[:limit]

def relevant(query,result):
    # Reject obviously unrelated engine responses instead of grounding an answer in them.
    stop={'the','and','for','what','how','are','was','with','from','that','this','explain','about','www','com','site'}
    terms={w for w in re.findall(r'\w+',query.lower()) if len(w)>2 and w not in stop}
    words=set(re.findall(r'\w+',(result['title']+' '+result['snippet']+' '+result['url']).lower()))
    return not terms or len(terms & words)>=min(2,len(terms))

def search(query,limit=5):
    if not isinstance(query,str) or not 2<=len(query)<=240:raise ValueError('Search query must be 2–240 characters')
    warnings=[]
    with httpx.Client(trust_env=False,timeout=25) as client:
        for engines in ('google','yahoo,startpage','mwmbl,wikipedia','bing,duckduckgo'):
            response=client.get(SEARCH_URL+'/search',params={'q':query,'format':'json','engines':engines,'language':'en','safesearch':1})
            response.raise_for_status();data=response.json()
            warnings.extend(str(e[0])+': '+str(e[1]) for e in data.get('unresponsive_engines',[]) if len(e)>1)
            results=[{'title':clean(r.get('title',''),200),'url':r['url'],'snippet':clean(r.get('content',''),600),
                      'engines':r.get('engines',[r.get('engine',engines)])}
                     for r in data.get('results',[]) if public_url(r.get('url',''))][:limit]
            results=[r for r in results if relevant(query,r)]
            if results:
                if engines!='google':warnings.append('Google was unavailable; used '+', '.join(sorted({e for r in results for e in r['engines']}))+' fallback.')
                return {'query':query,'results':results,'warnings':warnings}
    return {'query':query,'results':[],'warnings':warnings or ['No search results returned.']}
