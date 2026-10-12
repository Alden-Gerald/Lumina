// Response actions capture their conversation ID so navigation cannot change their target.
function responseIcon(name){
 const paths={up:['M7 10v10H3V10h4z','M7 10l5-7h2v6h5a2 2 0 0 1 2 2l-2 8a2 2 0 0 1-2 1H7'],down:['M7 14V4H3v10h4z','M7 14l5 7h2v-6h5a2 2 0 0 0 2-2l-2-8a2 2 0 0 0-2-1H7'],redo:['M20 7v5h-5','M20 12a8 8 0 1 0-2 6'],copy:['M8 8h12v13H8z','M16 8V3H3v13h5']};
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
 for(const d of paths[name]||[]){const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path)}return svg
}
function responseActions(m){
 const conversation=chatCurrent,box=element('div',undefined,'response-controls'),bar=element('div',undefined,'response-actions'),notice=element('span','', 'response-notice');notice.setAttribute('role','status');box.dataset.responseId=m.id;box.append(bar);
 function button(label,icon,action,idle=false){const b=element('button',undefined,'response-action');b.type='button';b.title=label;b.setAttribute('aria-label',label);if(icon)b.append(responseIcon(icon));else b.textContent=label;if(idle)b.dataset.requiresIdle='true';b.onclick=async()=>{b.disabled=true;clearError();try{await action(b)}catch(e){notice.textContent=e.message;error(e)}finally{b.disabled=false}};return b}
 async function updateRating(rating,note=m.feedback?.note||''){
  await api('/chats/'+conversation+'/feedback',{message_id:m.id,rating,note});await refreshChat()
 }
 for(const [rating,label] of [['up','Good response'],['down','Poor response']]){
  const b=button(label,rating,()=>updateRating(m.feedback?.rating===rating?null:rating),true);b.setAttribute('aria-pressed',String(m.feedback?.rating===rating));bar.append(b)
 }
 bar.append(button('Redo in a new branch','redo',async()=>{
  const s=await api('/chats/'+conversation+'/redo',{message_id:m.id,model:$('chat-model').value,deep:$('chat-deep').checked,web:$('chat-web').checked});await selectChat(s.id)
 },true));
 bar.append(button('Copy response','copy',async b=>{
  try{await navigator.clipboard.writeText(m.content);notice.textContent='Copied';b.title='Copied'}
  catch{notice.textContent='Clipboard unavailable. Select the text below and copy it.';const text=element('textarea');text.value=m.content;text.readOnly=true;text.setAttribute('aria-label','Response text to copy');box.append(text);text.focus();text.select()}
 }));
 const more=element('details',undefined,'response-more'),summary=element('summary','•••');summary.title='More response actions';summary.setAttribute('aria-label','More response actions');const menu=element('div',undefined,'response-menu');more.append(summary,menu);bar.append(more,notice);
 menu.append(button('Branch in new chat',null,async()=>{const s=await api('/chats/'+conversation+'/branch',{message_id:m.id});await selectChat(s.id)}));
 function downloadLink(label,kind){const a=element('a',label,'response-action');a.href='/api/chats/'+conversation+'/responses/'+m.id+'/'+kind;a.download=kind;a.onclick=()=>{more.open=false;notice.textContent='Download requested'};return a}
 menu.append(downloadLink('Download response','response.md'));
 if(m.feedback)menu.append(downloadLink('Export feedback for training','feedback.json'));
 else{const disabled=button('Export feedback for training',null,()=>{});disabled.disabled=true;disabled.title='Rate this response first';menu.append(disabled)}
 menu.append(button('Show activity log',null,()=>{const history=box.parentElement.querySelector('.work-history');if(history){history.open=true;history.scrollIntoView({block:'nearest',behavior:'smooth'})}more.open=false}));
 if(m.feedback){
  const details=element('details',undefined,'feedback-editor');details.append(element('summary',(m.feedback.rating==='up'?'Rated helpful':'Rated needs improvement')+' · Saved locally · Add a note'));
  const form=element('form'),label=element('label','What was useful, or what should improve? (optional)'),input=element('textarea');input.rows=3;input.maxLength=2000;input.value=m.feedback.note;input.id='feedback-'+m.id;label.htmlFor=input.id;
  const save=element('button','Save feedback','secondary');save.type='submit';save.dataset.requiresIdle='true';form.append(label,input,save,element('p','Feedback stays on this computer for review or later training. It does not train the model automatically.','note'));
  form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await updateRating(m.feedback.rating,input.value)}catch(err){error(err)}finally{save.disabled=false}};details.append(form);box.append(details)
 }
 return box
}
document.addEventListener('click',e=>{for(const menu of document.querySelectorAll('.response-more[open]'))if(!menu.contains(e.target))menu.open=false});
document.addEventListener('keydown',e=>{if(e.key==='Escape')for(const menu of document.querySelectorAll('.response-more[open]')){menu.open=false;menu.querySelector('summary').focus()}});
