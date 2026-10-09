(() => {
 const dock=document.getElementById('theme-dock');
 const toggle=document.getElementById('theme-picker-toggle');
 const panel=document.getElementById('theme-picker-panel');
 const closeButton=document.getElementById('theme-picker-close');
 const followButton=document.getElementById('theme-follow');
 const shellName=document.getElementById('theme-shell-name');
 const search=document.getElementById('theme-search');
 const options=document.getElementById('theme-options');
 const status=document.getElementById('theme-picker-status');
 let snapshot=null,signature='',pinned=false,suppressHover=false;
 let choice='follow';
 try{choice=localStorage.getItem('lumina-theme-choice')||'follow'}catch{}

 const displayName=name=>name.split('-').map(word=>word[0].toUpperCase()+word.slice(1)).join(' ');
 const formatColor=hex=>parseInt(hex.slice(1,3),16)*.2126+parseInt(hex.slice(3,5),16)*.7152+parseInt(hex.slice(5,7),16)*.0722;
 const colorKeys={background:'--theme-background',surface:'--theme-surface',surfaceHover:'--theme-surface-hover',textPrimary:'--theme-text-primary',textSecondary:'--theme-text-secondary',accent:'--theme-accent',border:'--theme-border',danger:'--theme-danger',windows:'--theme-cyan',orange:'--theme-orange',warning:'--theme-yellow'};
 function activeTheme(){
  if(!snapshot)return null;
  const requested=choice.startsWith('manual:')?choice.slice(7):snapshot.selected;
  return snapshot.themes.find(theme=>theme.name===requested)||snapshot.themes.find(theme=>theme.name===snapshot.selected)||null;
 }
 function applyTheme(theme){
  if(!theme)return;
  const root=document.documentElement,colors=theme.palette;
  for(const [key,property] of Object.entries(colorKeys))root.style.setProperty(property,colors[key]);
  const light=formatColor(colors.background)>150;
  root.style.colorScheme=light?'light':'dark';
  root.style.setProperty('--theme-background-dark',theme.name==='dracula'?'#21222c':`color-mix(in srgb, ${colors.background} ${light?84:83}%, ${light?'white':'black'})`);
  root.style.setProperty('--theme-background-darker',theme.name==='dracula'?'#191a21':`color-mix(in srgb, ${colors.background} ${light?74:70}%, ${light?'white':'black'})`);
  root.style.setProperty('--theme-green',theme.name==='dracula'?'#50fa7b':colors.accent);
  root.style.setProperty('--theme-pink',theme.name==='dracula'?'#ff79c6':colors.accent);
  document.getElementById('theme-current-dot').style.background=colors.accent;
 }
 function render(){
  if(!snapshot)return;
  const selected=activeTheme();
  applyTheme(selected);
  const following=choice==='follow';
  followButton.setAttribute('aria-pressed',String(following));
  shellName.textContent='Current: '+displayName(snapshot.selected);
  status.textContent=following?'Following Quickshell · '+displayName(snapshot.selected):'Lumina only · '+displayName(selected.name);
  const query=search.value.trim().toLowerCase();
  options.replaceChildren();
  const matches=snapshot.themes.filter(theme=>theme.name.includes(query));
  if(!matches.length){const empty=document.createElement('p');empty.className='theme-picker-empty';empty.textContent='No themes found';options.append(empty);return}
  for(const theme of matches){
   const p=theme.palette,button=document.createElement('button');
   button.type='button';button.className='theme-option';button.setAttribute('aria-pressed',String(selected.name===theme.name));
   button.setAttribute('aria-label',displayName(theme.name)+' theme');
   for(const [key,value] of Object.entries({'--theme-option-background':p.background,'--theme-option-surface':p.surface,'--theme-option-text':p.textPrimary,'--theme-option-border':p.border,'--theme-option-accent':p.accent}))button.style.setProperty(key,value);
   const name=document.createElement('span');name.textContent=displayName(theme.name);
   const preview=document.createElement('span');preview.className='theme-option-preview';
   const sample=document.createElement('span');sample.className='sample';sample.textContent='Aa';preview.append(sample);
   for(const color of [p.accent,p.windows,p.orange]){const dot=document.createElement('i');dot.style.setProperty('--swatch',color);preview.append(dot)}
   const mark=document.createElement('i');mark.className='mark';mark.textContent=selected.name===theme.name?'✓':'';preview.append(mark);
   button.append(name,preview);button.onclick=()=>{choice='manual:'+theme.name;try{localStorage.setItem('lumina-theme-choice',choice)}catch{}render()};
   options.append(button);
  }
 }
 function open(){panel.hidden=false;toggle.setAttribute('aria-expanded','true');toggle.setAttribute('aria-label','Close theme picker')}
 function close(){panel.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Open theme picker');pinned=false}
 toggle.onclick=()=>{if(pinned){close();suppressHover=true}else{pinned=true;open()}};
 closeButton.onclick=()=>{close();suppressHover=true;toggle.focus()};
 dock.addEventListener('mouseenter',()=>{if(!suppressHover)open()});
 dock.addEventListener('mouseleave',()=>{suppressHover=false;if(!pinned)close()});
 dock.addEventListener('focusin',()=>{if(!suppressHover)open()});
 dock.addEventListener('focusout',()=>{if(!pinned&&!dock.contains(document.activeElement))close()});
 document.addEventListener('pointerdown',event=>{if(!dock.contains(event.target))close()});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!panel.hidden){close();suppressHover=true;toggle.focus()}});
 followButton.onclick=()=>{choice='follow';try{localStorage.setItem('lumina-theme-choice',choice)}catch{}render()};
 search.oninput=render;
 search.onkeydown=event=>{if(event.key==='Enter'){const first=options.querySelector('button');if(first)first.click()}};
 async function refresh(){
  try{
   const response=await fetch('/api/theme',{cache:'no-store'});
   if(!response.ok)throw new Error('Theme service unavailable');
   const next=await response.json(),nextSignature=JSON.stringify(next);
   if(nextSignature===signature)return;
   if(!Array.isArray(next.themes)||!next.themes.length)throw new Error('No themes available');
   snapshot=next;signature=nextSignature;
   if(choice.startsWith('manual:')&&!next.themes.some(theme=>theme.name===choice.slice(7))){choice='follow';try{localStorage.removeItem('lumina-theme-choice')}catch{}}
   render();
  }catch{if(!snapshot){shellName.textContent='Quickshell theme unavailable';status.textContent='Could not load theme choices.'}}
 }
 refresh();setInterval(refresh,5000);
})();
