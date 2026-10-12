const token = JSON.parse(document.getElementById('session').textContent).token;
let current=null,polling=false,info=null,attachments=[],uploading=false,mode="code",chatCurrent=null,chatPolling=false,lastChatRender="",lastPartialRender="",lastChatState=null,lastActivitySignature="";
let knownRunIds=null,runsRefreshing=false;
let knownStatuses=null;
let artifactMessages=[],selectedArtifactId=null,artifactClosed=false,artifactView='preview';
let lastRenderedChatId=null;
let contextSidebarOpen=false;
const $=id=>document.getElementById(id);
const SIDEBAR_MIN=190,SIDEBAR_MAX=420,SIDEBAR_DEFAULT=248;
let sidebarWidth=SIDEBAR_DEFAULT,sidebarCollapsed=false;
function sidebarLimit(){return window.innerWidth<=700?SIDEBAR_MAX:Math.max(SIDEBAR_MIN,Math.min(SIDEBAR_MAX,window.innerWidth-430))}
function setSidebarWidth(value,persist=false){sidebarWidth=Math.max(SIDEBAR_MIN,Math.min(sidebarLimit(),Math.round(value)));$('layout').style.setProperty('--sidebar-width',sidebarWidth+'px');$('sidebar-resizer').setAttribute('aria-valuenow',String(sidebarWidth));$('sidebar-resizer').setAttribute('aria-valuemax',String(sidebarLimit()));if(persist)try{localStorage.setItem('lumina-sidebar-width',String(sidebarWidth))}catch{}}
function setSidebarCollapsed(value,persist=false){sidebarCollapsed=!!value;$('layout').classList.toggle('sidebar-collapsed',sidebarCollapsed);$('sidebar-toggle').textContent=sidebarCollapsed?'»':'«';$('sidebar-toggle').setAttribute('aria-label',sidebarCollapsed?'Expand sidebar':'Minimize sidebar');$('sidebar-toggle').setAttribute('title',sidebarCollapsed?'Expand sidebar':'Minimize sidebar');$('sidebar-toggle').setAttribute('aria-expanded',String(!sidebarCollapsed));$('sidebar-resizer').tabIndex=sidebarCollapsed?-1:0;if(persist)try{localStorage.setItem('lumina-sidebar-collapsed',String(sidebarCollapsed))}catch{}}
try{const saved=Number(localStorage.getItem('lumina-sidebar-width'));if(Number.isFinite(saved)&&saved>=SIDEBAR_MIN)setSidebarWidth(saved);else setSidebarWidth(SIDEBAR_DEFAULT);setSidebarCollapsed(localStorage.getItem('lumina-sidebar-collapsed')==='true')}catch{setSidebarWidth(SIDEBAR_DEFAULT)}
$('sidebar-toggle').onclick=()=>setSidebarCollapsed(!sidebarCollapsed,true);
const sidebarResizer=$('sidebar-resizer');let resizingSidebar=false;
sidebarResizer.addEventListener('pointerdown',event=>{if(event.button!==0||sidebarCollapsed||window.innerWidth<=700)return;resizingSidebar=true;sidebarResizer.setPointerCapture(event.pointerId);$('layout').classList.add('resizing-sidebar');event.preventDefault()});
sidebarResizer.addEventListener('pointermove',event=>{if(resizingSidebar)setSidebarWidth(event.clientX-$('layout').getBoundingClientRect().left)});
function finishSidebarResize(){if(!resizingSidebar)return;resizingSidebar=false;$('layout').classList.remove('resizing-sidebar');setSidebarWidth(sidebarWidth,true)}
sidebarResizer.addEventListener('pointerup',finishSidebarResize);sidebarResizer.addEventListener('pointercancel',finishSidebarResize);
sidebarResizer.addEventListener('dblclick',()=>setSidebarWidth(SIDEBAR_DEFAULT,true));
sidebarResizer.addEventListener('keydown',event=>{let next=sidebarWidth;if(event.key==='ArrowLeft')next-=16;else if(event.key==='ArrowRight')next+=16;else if(event.key==='Home')next=SIDEBAR_MIN;else if(event.key==='End')next=sidebarLimit();else return;event.preventDefault();setSidebarWidth(next,true)});
window.addEventListener('resize',()=>setSidebarWidth(sidebarWidth));
const terminal=new Set(['completed','needs_attention','cancelled']);
function chatStatus(status){return status==='idle'?'Done':status==='failed'?'Failed':status==='cancelled'?'Stopped':'Working'}
async function api(path,body){const r=await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Local-Coder-Token':token,'X-Lumina-Queue':'true'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.error||'Request failed');return data}
function error(e){$('error').textContent=e.message||String(e);$('error').hidden=false}
function clearError(){$('error').hidden=true}
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function contextRows(target,items,empty){
 target.replaceChildren();
 if(!items.length){target.append(element('li',empty,'context-empty'));return}
 for(const item of items){const li=element('li');if(item.url){const link=element('a',item.label);link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';li.append(link)}else li.textContent=item.label;target.append(li)}
}
function renderContextSidebar(){
 if(!contextSidebarOpen)return;
 $('context-theme').textContent=$('theme-shell-name')?.textContent||$('theme-picker-status')?.textContent||'Current Lumina theme';
 const outputs=[],sources=[];
 if(mode==='chat'){
  const messages=lastChatState?.messages||[];
  messages.filter(message=>message.role==='assistant').forEach((message,index)=>outputs.push({label:`Answer ${index+1}${message.feedback?.rating?' · rated '+message.feedback.rating:''}`}));
  for(const artifact of artifactMessages)outputs.push({label:'Interactive preview · '+artifact.artifact.title});
  for(const message of messages){for(const source of message.sources||[])sources.push({label:source.title||source.url,url:source.url});for(const passage of message.file_passages||[])sources.push({label:passage.name+' · '+passage.citation})}
 }else if(mode==='code'){
  if(current){outputs.push({label:'Task status · '+$('status').textContent});if($('result').textContent.trim())outputs.push({label:$('result').textContent.trim().split('\n')[0]})}else outputs.push({label:'New coding task'});
  if($('source')?.value)sources.push({label:'Project · '+$('source').value});
 }else{
  const model=info?.models?.find(item=>item.model===$('neural-model').value);if(model){outputs.push({label:'Simplified five-stage diagram · '+model.model});sources.push({label:'Lumina configuration metadata'});for(const role of model.roles||[])sources.push({label:'Configured role · '+role})}
 }
 contextRows($('context-outputs'),outputs,'No outputs for the current selection.');contextRows($('context-sources'),sources,'No sources for the current selection.');
}
function setContextSidebar(open){contextSidebarOpen=!!open;$('context-sidebar').hidden=!contextSidebarOpen;$('layout').classList.toggle('context-sidebar-open',contextSidebarOpen);$('context-sidebar-toggle').setAttribute('aria-expanded',String(contextSidebarOpen));if(contextSidebarOpen)renderContextSidebar()}
$('context-sidebar-toggle').onclick=()=>setContextSidebar(!contextSidebarOpen);
$('context-sidebar-close').onclick=()=>setContextSidebar(false);
$('context-theme-open').onclick=()=>$('theme-picker-toggle').click();
new MutationObserver(renderContextSidebar).observe($('theme-shell-name'),{childList:true,subtree:true});
function svgElement(tag,attributes={},text){const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [name,value] of Object.entries(attributes))node.setAttribute(name,String(value));if(text!==undefined)node.textContent=text;return node}
function renderNeuralGraph(target,model,imageInput,moe){
 const svg=svgElement('svg',{class:'neural-svg',viewBox:'0 0 960 420',role:'img','aria-labelledby':'neural-svg-title neural-svg-desc',preserveAspectRatio:'xMidYMid meet'});
 svg.append(svgElement('title',{id:'neural-svg-title'},'Illustrative neural network for '+model.model),svgElement('desc',{id:'neural-svg-desc'},'A simplified fully connected diagram with input nodes, three hidden layers, and output nodes. It is a visual analogy and does not claim the model uses these exact nodes or connections.'));
 const defs=svgElement('defs'),arrowhead=svgElement('marker',{id:'neural-arrowhead',viewBox:'0 0 10 10',refX:8,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});
 arrowhead.append(svgElement('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'currentColor'}));defs.append(arrowhead);svg.append(defs);
 const layers=[
  {x:105,ys:[115,210,320],kind:'input'},
  {x:310,ys:[80,155,265,340],kind:'hidden'},
  {x:485,ys:[80,155,265,340],kind:'hidden'},
  {x:660,ys:[80,155,265,340],kind:'hidden'},
  {x:855,ys:[155,275],kind:'output'}
 ];
 const connections=svgElement('g',{class:'neural-connections','aria-hidden':'true'});
 for(let index=0;index<layers.length-1;index++)for(const y1 of layers[index].ys)for(const y2 of layers[index+1].ys)connections.append(svgElement('line',{class:'neural-link',x1:layers[index].x,y1,x2:layers[index+1].x,y2}));
 svg.append(connections);
 for(const x of [205,755])svg.append(svgElement('line',{class:'neural-separator',x1:x,y1:45,x2:x,y2:385,'aria-hidden':'true'}));
 svg.append(svgElement('text',{class:'neural-layer-label',x:105,y:28,'text-anchor':'middle'},'Input layer'),svgElement('text',{class:'neural-layer-label',x:485,y:28,'text-anchor':'middle'},moe?'Hidden computation · MoE':'Hidden computation'),svgElement('text',{class:'neural-layer-label',x:855,y:28,'text-anchor':'middle'},'Output layer'));
 layers.forEach((layer,layerIndex)=>layer.ys.forEach((y,nodeIndex)=>svg.append(svgElement('circle',{class:'neural-circle neural-'+layer.kind,cx:layer.x,cy:y,r:18,'data-layer':layerIndex,'data-node':nodeIndex}))));
 svg.append(svgElement('text',{class:'neural-ellipsis',x:105,y:270,'text-anchor':'middle'},'⋮'),svgElement('text',{class:'neural-ellipsis',x:310,y:222,'text-anchor':'middle'},'⋮'),svgElement('text',{class:'neural-ellipsis',x:485,y:222,'text-anchor':'middle'},'⋮'),svgElement('text',{class:'neural-ellipsis',x:660,y:222,'text-anchor':'middle'},'⋮'));
 const inputLabels=imageInput?['Text','Image','Context']:['Prompt','Context','Tokens'];inputLabels.forEach((label,index)=>{svg.append(svgElement('text',{class:'neural-side-label',x:72,y:layers[0].ys[index]+5,'text-anchor':'end'},label),svgElement('line',{class:'neural-arrow',x1:76,y1:layers[0].ys[index],x2:86,y2:layers[0].ys[index],'marker-end':'url(#neural-arrowhead)'}))});
 ['Next token','Response'].forEach((label,index)=>{svg.append(svgElement('line',{class:'neural-arrow',x1:876,y1:layers[4].ys[index],x2:897,y2:layers[4].ys[index],'marker-end':'url(#neural-arrowhead)'}),svgElement('text',{class:'neural-side-label',x:905,y:layers[4].ys[index]+5},label))});
 target.replaceChildren(svg);
}
function renderNeuralModel(){
 const models=info?.models||[],select=$('neural-model'),model=models.find(item=>item.model===select.value)||models[0];
 if(!model){$('neural-status').textContent='Model metadata is unavailable. Lumina can still use Chat and Code.';return}
 if(select.value!==model.model)select.value=model.model;
 $('neural-model-name').textContent=model.model;
 $('neural-availability').textContent=model.installed?'Installed':'Not installed';
 $('neural-availability').className='pill '+(model.installed?'neural-installed':'neural-missing');
 const contexts=(model.contexts||[]).map(value=>value.toLocaleString()+' tokens').join(' / ');
 $('neural-roles').textContent='Roles: '+(model.roles||[]).join(', ')+(contexts?' · Configured context: '+contexts:'');
 const imageInput=(model.roles||[]).includes('Image reader');
 const moe=model.architecture==='mixture-of-experts';
 const steps=[
  {title:imageInput?'Text or image input':'Text input',detail:imageInput?'Lumina prepares text tokens or a resized local image for this model role.':'Lumina prepares the prompt and selected context.'},
  {title:'Tokens',detail:'Input is converted into model tokens.'},
  {title:'Embeddings',detail:'Tokens become numeric representations.'},
  {title:moe?'Repeated transformer blocks with expert routing':'Repeated transformer processing',detail:moe?'The configured model is labeled mixture-of-experts; exact expert and layer counts are not stored here.':'Exact layer, attention, and internal topology details are not stored in Lumina.'},
  {title:'Output tokens',detail:'The pretrained network predicts tokens one at a time to form the response.'}
 ];
 renderNeuralGraph($('neural-diagram'),model,imageInput,moe);
 $('neural-steps').replaceChildren(...steps.map(step=>{const li=element('li');li.append(element('strong',step.title),document.createTextNode(' — '+step.detail));return li}));
 $('neural-diagram-description').textContent='Illustrative neural graph for '+model.model+'. The nodes and connections show the general idea of information flowing through a neural network; they are not the model’s exact transformer layers or live activations. '+(moe?'Lumina only knows this model is configured as mixture-of-experts. ':'')+'Unknown implementation details are intentionally omitted.';
 $('neural-status').textContent=(model.labels||[]).join(' · ');
 renderContextSidebar();
}
function initNeuralModels(){
 const models=info?.models||[],select=$('neural-model');select.replaceChildren();
 for(const model of models){const option=element('option',model.model+(model.installed?'':' · not installed'));option.value=model.model;select.append(option)}
 select.disabled=!models.length;renderNeuralModel();
}
$('neural-model').addEventListener('change',renderNeuralModel);
function renderAttachments(items,target,removable=true){
 if(!removable){const signature=JSON.stringify(items);if(target.dataset.attachmentSignature===signature)return;target.dataset.attachmentSignature=signature}
 target.replaceChildren();
 for(const item of items){
  const row=element('div',undefined,'attachment');
  if(item.kind==='document'){
   const icon=element('div',item.type,'file-preview');icon.setAttribute('aria-label',item.type+' document');row.append(icon);
   const link=element('a',item.name);link.href=item.url;link.download=item.name;link.title='Download '+item.name;row.append(link);
   row.append(element('small',`${item.units_read} ${item.units_read===1?({pages:'page',sheets:'sheet',slides:'slide',lines:'line','paragraphs/tables':'paragraph/table'}[item.unit]||item.unit):item.unit} · text ready`,'file-ready'));
   if(item.warnings?.length){const details=element('details');details.append(element('summary','Reading limits'));for(const warning of item.warnings)details.append(element('p',warning));row.append(details)}
  }else{const img=element('img');img.src=item.url;img.alt=item.name;row.append(img,element('span',item.name))}
  if(removable){const remove=element('button','Remove','secondary');remove.type='button';remove.setAttribute('aria-label','Remove '+item.name);remove.onclick=()=>{attachments=attachments.filter(a=>a.id!==item.id);renderAttachments(attachments,$('attachments'));$('chat-upload-status').textContent=attachments.length?`${attachments.length} file(s) ready`:''};row.append(remove)}
  target.append(row)
 }
}
async function addFiles(files){
 if(uploading)return;const chosen=Array.from(files);if(!chosen.length)return;clearError();
 if(attachments.length+chosen.length>4){error(new Error('Attach at most four files. Remove one first.'));return}
 const image=file=>file.type.startsWith('image/')||/\.(png|jpe?g|webp)$/i.test(file.name);
 if(attachments.filter(a=>a.kind!=='document').length+chosen.filter(image).length>2){error(new Error('Attach at most two images per message.'));return}
 uploading=true;$('start').disabled=true;$('chat-send').disabled=true;$('attach-file').disabled=true;$('chat-attach').disabled=true;
 try{
  for(const [index,file] of chosen.entries()){
   if(file.size>(image(file)?4:10)*1024*1024)throw new Error(file.name+': choose a file under '+(image(file)?'4MB':'10MB')+'.');
   const message=`Reading file locally… (${index+1}/${chosen.length})`;$('file-status').textContent=message;$('chat-upload-status').textContent=message;
   const r=await fetch('/api/attachments',{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream','X-Local-Coder-Token':token,'X-Upload-Name':encodeURIComponent(file.name||'Attachment')},body:file});
   const data=await r.json();if(!r.ok)throw new Error(file.name+': '+(data.error||'File could not be read'));
   attachments.push(data);renderAttachments(attachments,$('attachments'))
  }
  $('file-status').textContent=`${attachments.length} file(s) ready. Add your question or feature request.`;$('chat-upload-status').textContent=`${attachments.length} file(s) ready`;
 }catch(e){error(e);$('file-status').textContent='File could not be read. See the explanation below.';$('chat-upload-status').textContent='File could not be read'}
 finally{uploading=false;$('start').disabled=false;$('chat-send').disabled=!!lastChatState&&!['idle','failed','cancelled'].includes(lastChatState.status);$('attach-file').disabled=false;$('chat-attach').disabled=false;$('file-input').value=''}
}
$('attach-file').onclick=()=>$('file-input').click();$('chat-attach').onclick=()=>$('file-input').click();
$('file-input').onchange=e=>addFiles(e.target.files);
$('composer').addEventListener('paste',e=>{const files=Array.from(e.clipboardData?.files||[]);if(files.length){e.preventDefault();addFiles(files)}});
$('chat-composer').addEventListener('paste',e=>{const files=Array.from(e.clipboardData?.files||[]);if(files.length){e.preventDefault();addFiles(files)}});
for(const box of [$('file-drop'),$('chat-message-box')]){box.addEventListener('dragover',e=>{e.preventDefault();box.classList.add('dragging')});box.addEventListener('dragleave',()=>box.classList.remove('dragging'));box.addEventListener('drop',e=>{e.preventDefault();box.classList.remove('dragging');addFiles(e.dataTransfer.files)})}
async function refreshRuns(autoOpen=false){
 if(runsRefreshing)return;runsRefreshing=true;
 try{
  const query=$('history-search').value.trim(),[allRuns,chats]=await Promise.all([api('/runs'),api('/chats?query='+encodeURIComponent(query)+'&page_size=100')]),runs=query?allRuns.filter(run=>run.task.toLowerCase().includes(query.toLowerCase())):allRuns,previous=knownRunIds,previousStatuses=knownStatuses;
  knownStatuses=new Map([...runs.map(item=>['run:'+item.id,item.status]),...chats.map(item=>['chat:'+item.id,item.status])]);
  if(previousStatuses&&localStorage.getItem('lumina-notifications')==='true'&&'Notification'in window&&Notification.permission==='granted')for(const item of [...runs.map(value=>({key:'run:'+value.id,label:value.task,status:value.status,done:terminal.has(value.status)})),...chats.map(value=>({key:'chat:'+value.id,label:value.title,status:value.status,done:['idle','failed','cancelled'].includes(value.status)}))])if(item.done&&!['completed','needs_attention','cancelled','idle','failed'].includes(previousStatuses.get(item.key)))new Notification('Lumina finished',{body:item.label+' · '+item.status.replaceAll('_',' ')});
  knownRunIds=new Set(runs.map(run=>run.id));$('runs').replaceChildren();
  const addRun=run=>{const b=element('button',run.task.slice(0,68),run.id===current&&mode==='code'?'active':'');b.append(element('small',(run.origin==='codex'?'Codex handoff · ':'')+run.status.replaceAll('_',' ')));b.onclick=()=>select(run.id);$('runs').append(b)};
  const addChat=chat=>{const row=element('div',undefined,'history-row'),b=element('button',chat.title,chat.id===chatCurrent&&mode==='chat'?'active':'');b.dataset.chatId=chat.id;b.append(element('small','Chat · '+chatStatus(chat.status)));b.onclick=()=>selectChat(chat.id);const actions=element('button','•••','history-actions');actions.type='button';actions.title='Conversation actions';actions.onclick=async()=>{const choice=prompt('Conversation action: rename, archive, or continue');if(!choice)return;try{if(choice.toLowerCase()==='rename'){const title=prompt('New conversation title',chat.title);if(title)await api('/chats/'+chat.id+'/rename',{title})}else if(choice.toLowerCase()==='archive'){await api('/chats/'+chat.id+'/archive',{archived:true});if(chatCurrent===chat.id)$('new-task').click()}else if(choice.toLowerCase()==='continue'){const preview=await api('/chats/'+chat.id+'/continuation'),context=prompt('Review and edit the context for the new chat',preview.context);if(context){const created=await api('/chats/'+chat.id+'/continue-new',{context});await selectChat(created.id)}}else throw new Error('Choose rename, archive, or continue');await refreshRuns()}catch(e){error(e)}};row.append(b,actions);$('runs').append(row)};
  if(mode==='code'){runs.forEach(addRun);chats.forEach(addChat)}else{chats.forEach(addChat);runs.forEach(addRun)}
  const active=run=>run.origin==='codex'&&!terminal.has(run.status),fresh=run=>!previous||!previous.has(run.id);
  const handoff=runs.find(run=>active(run)&&fresh(run));
  if(autoOpen&&handoff&&(current!==handoff.id||mode!=='code')){
   showMode('code');current=handoff.id;location.hash=handoff.id;$('composer').hidden=true;$('work').hidden=false;clearError();await refresh();
  }
 }finally{runsRefreshing=false}
}
$('history-search').addEventListener('input',()=>refreshRuns().catch(error));
async function select(id){showMode('code');current=id;location.hash=id;$('composer').hidden=true;$('work').hidden=false;clearError();await refresh();await refreshRuns()}
async function refresh(){if(!current||polling)return;polling=true;try{const [s,events,d]=await Promise.all([api('/runs/'+current),api('/runs/'+current+'/events'),api('/runs/'+current+'/diff')]);if(mode!=='code')return;$('heading').textContent=terminal.has(s.status)?'Your task workspace.':'Building your feature.';$('status').textContent=s.status.replaceAll('_',' ');$('message').textContent=s.message;$('task-title').textContent=s.task;renderTeam(s,events);renderAttachments(s.attachments||[],$('task-attachments'),false);$('cancel').hidden=terminal.has(s.status);const recover=s.status==='needs_attention',limit=(s.resume_count||0)>=3,busy=s.cleanup_complete===false;for(const id of ['continue-once','continue-instructions']){$(id).hidden=!recover;$(id).disabled=busy||limit}$('follow-up').hidden=!recover;$('follow-up').disabled=busy;$('auto-solve').hidden=!recover;$('auto-solve').disabled=busy||limit;$('auto-solve').textContent=s.auto_solve?'Auto-solving…':'Auto solve';$('plan').replaceChildren();for(const step of s.plan?.steps||[])$('plan').append(element('li',step));$('events').replaceChildren();for(const event of events.filter(e=>e.kind!=='generating'||e===events.at(-1))){const row=element('div',undefined,'event');row.append(element('time',new Date(event.time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})),element('span',activityIcon(event.kind,event.details),'operation-icon'),element('span',event.message));if(Object.keys(event.details||{}).length)row.append(element('pre',JSON.stringify(event.details,null,2),'event-log'));$('events').append(row)}$('events').scrollTop=$('events').scrollHeight;$('diff').textContent=d.diff||'No edits yet.';$('result').replaceChildren();if(s.status==='completed'){const p=element('p',`${s.changed_files.length} file(s) changed. Checked and committed in the task workspace.`,'success');$('result').append(p,element('p','Commit '+s.commit.slice(0,12)));}else if(recover){$('result').append(element('p','Stopped with partial work preserved.'),element('p',s.message),element('p',limit?'This recovery generation reached its three-attempt safety limit. Create a reviewed follow-up to continue from preserved work.':`${3-(s.resume_count||0)} continuation attempt(s) remain. Choose one attempt, add instructions, or let Auto solve use the remaining budget.`,'check'))}else{$('result').textContent=s.auto_solve?'Automatic recovery is working through the preserved failure.':'The agent is working through its plan.'}$('checks').replaceChildren();if(s.validation){$('checks').append(element('p',s.validation.summary,'check'));for(const test of s.validation.task_tests||[])$('checks').append(element('p',(test.ok?'Passed: ':'Failed: ')+'required check ('+test.argv[0]+')','check'));if(!s.test_commands?.length)$('checks').append(element('p','Source checks and model review are available. No independent behavior test was supplied; review visual behavior after applying.','check'))}$('apply-box').hidden=s.status!=='completed'||s.cleanup_complete===false||!!s.applied;if(s.applied)$('result').append(element('p','Applied to the project. Backup: '+s.applied.backup,'success'));}catch(e){error(e)}finally{polling=false}}
$('new-task').onclick=()=>{if(mode==='neural')showMode('chat');clearAttachments();clearError();history.replaceState(null,'',location.pathname);if(mode==='chat'){chatCurrent=null;$('chat-messages').replaceChildren();$('chat-intro').hidden=false;resetChatProgress();artifactMessages=[];selectedArtifactId=null;artifactClosed=false;renderArtifactPanel();$('chat-model').value='auto';updateDeepChoice();$('chat-input').value='';$('chat-send').disabled=false;$('chat-stop').hidden=true;}else{current=null;$('composer').hidden=false;$('work').hidden=true;$('heading').textContent='Build one useful feature.';$('task').value='';$('acceptance').value='';$('check').value='';if(info)$('source').value=info.project}refreshRuns().catch(error)};
$('start').onclick=async()=>{clearError();$('start').disabled=true;try{const s=await api('/runs',{task:$('task').value.trim(),acceptance:$('acceptance').value.trim(),source:$('source').value.trim(),profile:$('profile').value,team:$('team').checked,attachments:attachments.map(a=>a.id),check_command:$('check').value.trim()});if(s.queued){$('connection').textContent='Queued · position '+s.position;await refreshRuns()}else await select(s.id)}catch(e){error(e)}finally{$('start').disabled=false}};
$('cancel').onclick=async()=>{try{await api('/runs/'+current+'/cancel',{});await refresh()}catch(e){error(e)}};
$('auto-solve').onclick=async()=>{const button=$('auto-solve');clearError();button.disabled=true;button.textContent='Starting auto solve…';try{await api('/runs/'+current+'/auto-solve',{});await refresh()}catch(e){error(e);button.disabled=false;button.textContent='Auto solve'}};
$('continue-once').onclick=async()=>{try{await api('/runs/'+current+'/continue',{});await refresh()}catch(e){error(e)}};
$('continue-instructions').onclick=async()=>{const instructions=prompt('What should Lumina do differently on this continuation?');if(!instructions)return;try{await api('/runs/'+current+'/continue',{instructions});await refresh()}catch(e){error(e)}};
$('follow-up').onclick=async()=>{const instructions=prompt('Review the preserved failure and describe the follow-up goal.');if(!instructions)return;try{await api('/runs/'+current+'/follow-up',{instructions});await refresh()}catch(e){error(e)}};
$('apply').onclick=async()=>{clearError();$('apply').disabled=true;try{await api('/runs/'+current+'/apply',{});await refresh()}catch(e){error(e)}finally{$('apply').disabled=false}};
function renderHardwareMode(hardware=info?.hardware,helperReady=false){const available=helperReady||hardware?.helper_indices?.length||hardware?.dual_available;$('hardware-mode').textContent='RX 6600 · local builder + CPU offload\n'+(available?'GTX 1050 Ti · optional 2B helper':'GTX reserved or unavailable · helper skipped')+'\n16GiB shared inference RAM limit\nChecks run alongside the builder'}
$('helper-check').onclick=async()=>{const button=$('helper-check'),status=$('helper-check-status');button.disabled=true;button.textContent='Checking GTX…';status.textContent='Checking ownership, availability, and the 2B worker.';try{const result=await api('/gpu/helper/check',{});if(info)info.hardware=result.hardware||info.hardware;renderHardwareMode(result.hardware,result.available);if(result.available){const supported=['quality','roadmap'].includes($('profile').value);if(supported){$('team').disabled=false;$('team').checked=true}status.textContent=supported?'GTX helper ready and enabled for new tasks.':'GTX helper ready. Choose Automatic 7B or Builder 14B to use it.'}else status.textContent=result.reason||'GTX helper is unavailable.'}catch(e){status.textContent=e.message||'GTX helper check failed.'}finally{button.disabled=false;button.textContent='Check GTX helper'}};
async function init(){try{info=await api('/info');$('connection').textContent=info.maintenance?'Testing local workers':info.error?'Inference unavailable':'Local inference ready';for(const option of $('profile').options){const p=info.profiles[option.value];option.disabled=!p?.installed;if(!p?.installed)option.textContent+=' · not installed'}if($('profile').selectedOptions[0]?.disabled)$('profile').value=Object.keys(info.profiles).find(k=>info.profiles[k].installed)||'roadmap';renderHardwareMode();initNeuralModels();await refreshRuns(true);initChatModels(info);$('chat-model-note').textContent='Runs locally. Interactive previews open beside the conversation.';if(/^#chat:[0-9a-f]{32}$/.test(location.hash))await selectChat(location.hash.slice(6));else if(/^#[0-9a-f]{32}$/.test(location.hash))await select(location.hash.slice(1));else if(!current){try{const saved=localStorage.getItem('local-coder-mode');showMode(['chat','code','neural'].includes(saved)?saved:'chat')}catch{showMode('chat')}}}catch(e){$('connection').textContent='Service unavailable';error(e)}}
init();setInterval(()=>{refreshRuns(true).catch(error);if(mode==='code'&&current)refresh();renderContextSidebar()},2500);setInterval(()=>{if(mode==='chat'&&chatCurrent)refreshChat();tickChatDuration();},1000);
function clearAttachments(){attachments=[];renderAttachments(attachments,$('attachments'));$('file-status').textContent='Paste an image or drop files here.';$('chat-upload-status').textContent=''}
function showMode(next){
 if(!['chat','code','neural'].includes(next))next='chat';
 try{localStorage.setItem('local-coder-mode',next)}catch{}
 if(mode!==next&&mode!=='neural'&&next!=='neural')clearAttachments();mode=next;
 $('mode-chat').setAttribute('aria-pressed',String(next==='chat'));$('mode-code').setAttribute('aria-pressed',String(next==='code'));$('mode-neural-networks').setAttribute('aria-pressed',String(next==='neural'));
 $('chat-space').hidden=next!=='chat';$('neural-space').hidden=next!=='neural';$('composer').hidden=next!=='code'||!!current;$('work').hidden=next!=='code'||!current;
 $('heading').textContent=next==='chat'?'Think, build, explore.':next==='neural'?'Explore your local models.':'Build one useful feature.';
 document.querySelector('.eyebrow').textContent=next==='chat'?'YOUR CREATIVE WORKSPACE':next==='neural'?'NEURAL NETWORKS':'ORBIT QUICKSHELL';
 $('new-task-label').textContent=next==='code'?'New task':'New chat';$('new-task').setAttribute('title',next==='code'?'New task':'New chat');
 if(next==='chat')$('chat-file-slot').append($('attachments'));else if(next==='code')document.querySelector('#file-drop .note').before($('attachments'));
 if(next==='neural')renderNeuralModel();renderContextSidebar();clearError()
}
$('mode-chat').onclick=()=>{showMode('chat');location.hash=chatCurrent?'chat:'+chatCurrent:'';if(chatCurrent)refreshChat();refreshRuns().catch(error)};
$('mode-code').onclick=()=>{showMode('code');location.hash=current||'';if(current)refresh();refreshRuns().catch(error)};
$('mode-neural-networks').onclick=()=>{showMode('neural');location.hash='';refreshRuns().catch(error)};
function inlineText(target,text,sources=[]){const pattern=/(`[^`\n]+`|\*\*[^*\n]+\*\*|\[\d+\])/g;let last=0;for(const m of text.matchAll(pattern)){target.append(document.createTextNode(text.slice(last,m.index)));const v=m[0];if(v.startsWith('`'))target.append(element('code',v.slice(1,-1)));else if(v.startsWith('**'))target.append(element('strong',v.slice(2,-2)));else{const index=Number(v.slice(1,-1))-1,source=sources[index];if(source){const a=element('a',v);a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';target.append(a)}else target.append(document.createTextNode(v))}last=m.index+v.length}target.append(document.createTextNode(text.slice(last)))}
function parseArtifact(content){const matches=[...content.matchAll(/<local_artifact\b([^>]*)>([\s\S]*?)<\/local_artifact\s*>/gi)];for(let i=matches.length-1;i>=0;i--){const attrs=Object.fromEntries([...matches[i][1].matchAll(/([\w-]+)\s*=\s*"([^"]*)"/g)].map(a=>[a[1],a[2]]));if(!['web_app','html'].includes(attrs.type))continue;const fenced=matches[i][2].match(/^\s*```html\s*\n([\s\S]*?)\n```\s*$/i);if(!fenced||new TextEncoder().encode(fenced[1]).length>250000||!/<(?:!doctype\s+html|html|body)\b/i.test(fenced[1]))continue;return {title:(attrs.title||'Untitled artifact').slice(0,100),html:fenced[1].trim()}}return null}
function visibleChatText(content){const start=content.search(/<local_artifact\b/i);return start<0?content:content.slice(0,start).trim()}
function openArtifact(id){selectedArtifactId=id;artifactClosed=false;renderArtifactPanel()}
function renderArtifactPanel(){const item=artifactMessages.find(m=>m.id===selectedArtifactId),panel=$('artifact-panel');panel.hidden=!item||artifactClosed;$('chat-layout').classList.toggle('has-artifact',!!item&&!artifactClosed);if(!item||artifactClosed)return;$('artifact-title').textContent=item.artifact.title;$('artifact-version').textContent='Version '+(artifactMessages.indexOf(item)+1)+' of '+artifactMessages.length;$('artifact-source').textContent=item.artifact.html;const src='/api/chats/'+chatCurrent+'/artifacts/'+item.id+'/preview';if($('artifact-frame').getAttribute('src')!==src)$('artifact-frame').src=src;$('artifact-frame').hidden=artifactView!=='preview';$('artifact-source').hidden=artifactView!=='code';$('artifact-preview-tab').setAttribute('aria-selected',String(artifactView==='preview'));$('artifact-code-tab').setAttribute('aria-selected',String(artifactView==='code'))}
$('artifact-close').onclick=()=>{artifactClosed=true;renderArtifactPanel()};
$('artifact-preview-tab').onclick=()=>{artifactView='preview';renderArtifactPanel()};
$('artifact-code-tab').onclick=()=>{artifactView='code';renderArtifactPanel()};
$('artifact-copy').onclick=async()=>{const item=artifactMessages.find(m=>m.id===selectedArtifactId);if(!item)return;try{await navigator.clipboard.writeText(item.artifact.html);$('artifact-copy').textContent='Copied';setTimeout(()=>$('artifact-copy').textContent='Copy code',1800)}catch(e){error(e)}};
function markdown(text,sources){const out=element('div',undefined,'markdown');let fenced=false,code=[],paragraph=[];function flush(){if(paragraph.length){const p=element('p');inlineText(p,paragraph.join('\n'),sources);out.append(p);paragraph=[]}}for(const line of text.split('\n')){if(line.startsWith('```')){flush();if(fenced){out.append(element('pre',code.join('\n')));code=[]}fenced=!fenced;continue}if(fenced){code.push(line);continue}const h=line.match(/^#{1,4}\s+(.+)/),li=line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);if(h){flush();const title=element('h3');inlineText(title,h[1],sources);out.append(title)}else if(li){flush();const item=element('p',undefined,'chat-list-item');inlineText(item,'• '+li[1],sources);out.append(item)}else if(!line.trim())flush();else paragraph.push(line)}flush();if(code.length)out.append(element('pre',code.join('\n')));return out}
function answerRoadmap(plan){const box=element('section',undefined,'answer-roadmap');box.append(element('strong','Answer roadmap · '+plan.subproblems.length+' parts'));const list=element('ol');for(const part of plan.subproblems){const status=part.status==='done'?'Solved':part.status==='limited'?'Limited':part.status||'Pending';const item=element('li');item.append(document.createTextNode(part.question+' '),element('small','· '+status));list.append(item)}box.append(list);return box}
function chatMessage(m){
 const card=element('article',undefined,'card chat-message '+m.role),artifact=m.role==='assistant'?parseArtifact(m.content):null;
 card.append(element('div',m.role==='user'?'You':'Lumina','speaker'),markdown(m.role==='assistant'&&(artifact||!m.id)?visibleChatText(m.content):m.content,m.sources||[]));
 if(m.answer_plan?.subproblems?.length)card.append(answerRoadmap(m.answer_plan));
 if(artifact&&m.id){const tile=element('button',undefined,'artifact-link');tile.type='button';tile.append(element('span','✦','artifact-link-icon'),element('span',artifact.title,'artifact-link-title'),element('span','Open preview →','artifact-link-action'));tile.onclick=()=>openArtifact(m.id);card.append(tile)}
 else if(m.role==='assistant'&&!m.id&&/<local_artifact\b/i.test(m.content))card.append(element('p','Preparing interactive preview…','artifact-pending'));
 if(m.attachments?.length){const area=element('div',undefined,'attachments');renderAttachments(m.attachments,area,false);card.append(area)}
 if(m.sources?.length){const details=element('details');details.append(element('summary','Web sources · '+m.sources.length));const list=element('ol');for(const source of m.sources){const li=element('li'),link=element('a',source.title||source.url);link.href=source.url;link.target='_blank';link.rel='noopener noreferrer';li.append(link,element('small',source.passages?.length?' · full source passages read':source.read_error?' · full read failed; snippet only':' · search snippet'));if(source.passages?.length)for(const [index,passage] of source.passages.entries())li.append(element('pre',`[${index+1}] ${passage}`,'file-passage'));list.append(li)}details.append(list);card.append(details)}
 if(m.file_passages?.length){const details=element('details');details.append(element('summary','File passages · '+m.file_passages.length));for(const passage of m.file_passages)details.append(element('p',passage.citation+' · '+passage.name),element('pre',passage.text,'file-passage'));card.append(details)}
 if(m.knowledge_passages?.length){const details=element('details');details.append(element('summary','Knowledge library · '+m.knowledge_passages.length));for(const passage of m.knowledge_passages)details.append(element('p',passage.citation+' · '+passage.name+' · '+passage.source),element('pre',passage.text,'file-passage'));card.append(details)}
 if(m.memory_used?.length){const details=element('details');details.append(element('summary','Personal memory used · '+m.memory_used.length),element('p','These editable memory items were selected for this reply. Manage or forget them in Settings → Memory.','note'));card.append(details)}
 if(m.work||m.failed_work)card.append(workHistory(m.work||m.failed_work));
 if(m.optimization?.older_exchanges){const opt=element('details',undefined,'context-memory');opt.append(element('summary','Conversation optimized · '+m.optimization.older_exchanges+' earlier exchanges condensed'),element('p','Selected excerpts keep relevant history within the memory limit. Some details may be omitted; the full conversation stays saved.','note'),element('pre',m.optimization.memory||'No older excerpts fit this reply’s context budget.'));card.append(opt)}
 for(const warning of m.warnings||[])card.append(element('p',warning,'note'));
 if(window.renderMathInElement)window.renderMathInElement(card,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'\\(',right:'\\)',display:false},{left:'$',right:'$',display:false}],throwOnError:false,trust:false,strict:'ignore',maxExpand:200,maxSize:10});
 if(m.role==='assistant'&&m.id)card.append(responseActions(m));return card
}
async function selectChat(id){chatCurrent=id;selectedArtifactId=null;artifactClosed=false;artifactMessages=[];showMode('chat');location.hash='chat:'+id;lastChatRender='';lastPartialRender='';lastActivitySignature='';await refreshChat();if(lastChatState){$('chat-model').value=lastChatState.model_selection||'auto';$('chat-deep').checked=lastChatState.deep;$('chat-web').checked=lastChatState.web;updateDeepChoice()}await refreshRuns()}
async function refreshChat(){if(!chatCurrent||chatPolling)return;chatPolling=true;const id=chatCurrent;try{const s=await api('/chats/'+id);if(mode!=='chat'||id!==chatCurrent)return;const signature=JSON.stringify([s.id,s.messages]);if(signature!==lastChatRender){const previousLatest=artifactMessages.at(-1)?.id;artifactMessages=s.messages.filter(m=>m.role==='assistant'&&m.id).map(m=>({...m,artifact:parseArtifact(m.content)})).filter(m=>m.artifact);if(!selectedArtifactId||(!artifactClosed&&previousLatest!==artifactMessages.at(-1)?.id))selectedArtifactId=artifactMessages.at(-1)?.id||null;const previousMessageCount=lastRenderedChatId===s.id?$('chat-messages').children.length:s.messages.length;const renderedMessages=s.messages.map(chatMessage);for(const card of renderedMessages.slice(previousMessageCount))card.classList.add('is-new');$('chat-messages').replaceChildren(...renderedMessages);lastRenderedChatId=s.id;renderArtifactPanel();lastChatRender=signature}const partial=JSON.stringify([s.id,s.partial,s.sources]);if(partial!==lastPartialRender){$('chat-partial').replaceChildren();if(s.partial)$('chat-partial').append(chatMessage({role:'assistant',content:s.partial,sources:s.sources,warnings:s.warnings}));lastPartialRender=partial}$('chat-intro').hidden=s.messages.length>0;renderChatProgress(s);const active=!['idle','failed','cancelled'].includes(s.status);$('chat-partial').dataset.active=String(active);$('chat-send').disabled=active||uploading;$('chat-stop').hidden=!active;$('chat-model').disabled=active;$('chat-web').disabled=active;$('chat-deep').disabled=active||!!info?.chat_models?.[$('chat-model').value]&&!info.chat_models[$('chat-model').value].thinking;for(const b of document.querySelectorAll('[data-requires-idle]'))b.disabled=active;renderChatLineage(s);if(s.status==='failed')error(new Error(s.message));}catch(e){if(id===chatCurrent){$('chat-activity').hidden=false;$('chat-state').textContent='Connection lost';$('chat-state').className='state-badge state-failed';$('chat-live-text').textContent='Could not reach the local service. Retrying…';error(e)}}finally{chatPolling=false}}
$('chat-send').onclick=async()=>{clearError();$('chat-send').disabled=true;try{const s=await api('/chats',{text:$('chat-input').value.trim(),id:chatCurrent,model:$('chat-model').value,deep:$('chat-deep').checked,structured:true,web:$('chat-web').checked,attachments:attachments.map(a=>a.id)});$('chat-input').value='';clearAttachments();if(s.queued){$('connection').textContent='Chat queued · position '+s.position;await refreshRuns();$('chat-send').disabled=false}else await selectChat(s.id)}catch(e){error(e);$('chat-send').disabled=false}};
$('chat-stop').onclick=async()=>{try{await api('/chats/'+chatCurrent+'/cancel',{});await refreshChat()}catch(e){error(e)}};
$('chat-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();if(!$('chat-send').disabled)$('chat-send').click()}});

function initChatModels(data){$('chat-model').replaceChildren(element('option','Auto · Choose for me'));$('chat-model').options[0].value='auto';for(const [key,cfg] of Object.entries(data.chat_models||{})){const option=element('option',cfg.label+(cfg.installed?'':' · not installed'));option.value=key;option.disabled=!cfg.installed;$('chat-model').append(option)}updateDeepChoice()}
function renderChatContextUsage(s){
 const badge=$('chat-context-usage'),usedLabel=$('chat-tokens-used'),leftLabel=$('chat-context-left');
 const active=!!s&&!['idle','failed','cancelled'].includes(s.status);
 let input=0,output=0,windowTokens=0,approximate=false;
 if(active&&s.optimization){input=Number(s.optimization.input_tokens_estimate);windowTokens=Number(s.optimization.input_token_budget)+5000;approximate=true}
 else if(s?.messages?.at(-1)?.role==='assistant'&&s.metrics?.length){
  const metric=s.metrics.at(-1),generation=s.messages.at(-1).generation;
  windowTokens=Number(metric.options?.num_ctx||generation?.num_ctx);
  input=Number(metric.prompt_eval_count);
  if(!(input>0)){input=Number(metric.estimated_input_tokens||s.optimization?.input_tokens_estimate);approximate=true}
  output=Number(metric.eval_count);
  if(!Number.isFinite(output)||output<0){output=0;approximate=true}
 }
 if(!(input>0)||!(windowTokens>0)){
  usedLabel.textContent='Tokens —';leftLabel.textContent='Context left —';
  badge.title=active?'Counting this reply’s context…':'Token use appears after the first reply';return
 }
 const used=Math.round(input+output),left=Math.max(0,Math.round(windowTokens-used));
 const prefix=approximate?'≈':'';
 usedLabel.textContent=`${prefix}${used.toLocaleString()} tokens used`;
 leftLabel.textContent=`${prefix}${left.toLocaleString()} context left`;
 badge.title=active?'Estimated prompt tokens while the reply is running; generation tokens are added when it finishes.':`Last reply: ${Math.round(input).toLocaleString()} prompt + ${Math.round(output).toLocaleString()} generated tokens in a ${windowTokens.toLocaleString()}-token context window. The next prompt may use a different model.`
}
function updateDeepChoice(){const selected=info?.chat_models?.[$('chat-model').value],direct=selected&&!selected.thinking&&!selected.workflow;$('chat-deep').disabled=!!direct||!!lastChatState&&!['idle','failed','cancelled'].includes(lastChatState.status);if(direct)$('chat-deep').checked=false;$('deep-note').textContent=direct?'This model answers directly. Choose Structured 7B or Study 14B for difficult questions.':'Complex questions are divided into smaller questions, solved locally, then combined into one answer.'}
$('chat-model').onchange=updateDeepChoice;
function resetChatProgress(){lastChatState=null;lastChatRender='';lastPartialRender='';lastActivitySignature='';$('chat-activity').hidden=true;$('chat-partial').replaceChildren();$('chat-log-entries').replaceChildren();$('chat-machine-log').replaceChildren();$('chat-lineage').hidden=true;$('chat-model').disabled=false;$('chat-web').disabled=false;renderChatContextUsage(null)}
function activityEntries(events,started){const list=[];for(const event of events||[]){const row=element('li'),time=element('time',started?formatDuration(Math.max(0,event.time-started)):'');row.append(time,element('span',activityIcon(event.phase,event.details),'operation-icon'),element('span',activityLabel(event)));if(Object.keys(event.details||{}).length){const details=element('details');details.append(element('summary','Details'),element('pre',JSON.stringify(event.details,null,2)));row.append(details)}list.push(row)}return list}
function workHistory(work){const details=element('details',undefined,'work-history'),state=work.status==='idle'?'Done':work.status==='cancelled'?'Stopped':'Failed';details.append(element('summary',`${state} · Worked for ${formatDuration(work.elapsed_seconds)}`));if(work.route)details.append(element('p',(work.route.selection==='auto'?'Auto → ':'')+work.route.label+' · '+work.route.reason,'note'));const list=element('ol',undefined,'activity-log');list.append(...activityEntries(work.activity,work.activity?.[0]?.time));details.append(list);return details}
function renderChatProgress(s){lastChatState=s;renderChatContextUsage(s);$('chat-activity').hidden=!s.started_at&&!(s.activity?.length);const active=!['idle','failed','cancelled'].includes(s.status);$('chat-activity').dataset.active=String(active);const state=chatStatus(s.status);const recent=document.querySelector('#runs button[data-chat-id="'+s.id+'"] small');if(recent)recent.textContent='Chat · '+state;$('chat-state').textContent=state;$('chat-state').className='state-badge state-'+(active?'working':s.status);$('chat-model-used').textContent=s.route?(s.route.selection==='auto'?'Auto → ':'')+s.route.label:(s.model_selection&&s.model_selection!=='auto'?'Preparing selected model':'Auto · selecting a model');$('chat-live-text').textContent=s.message;$('chat-live').classList.toggle('is-writing',active&&s.generation_phase==='writing');const signature=JSON.stringify(s.activity||[]);if(signature!==lastActivitySignature){$('chat-log-entries').replaceChildren(...activityEntries(s.activity,s.started_at));$('chat-machine-log').replaceChildren(...compactActivity(s.activity||[]).map(e=>{const li=element('li');li.append(element('span',activityIcon(e.phase,e.details),'machine-icon'),element('span',activityLabel(e)));return li}));lastActivitySignature=signature}tickChatDuration()}
function tickChatDuration(){if(!lastChatState||mode!=='chat')return;const s=lastChatState,active=!['idle','failed','cancelled'].includes(s.status);const seconds=active&&s.started_at?Math.max(0,(Date.now()/1000)-s.started_at):s.elapsed_seconds;const duration=seconds===undefined?'':formatDuration(seconds);$('chat-duration').textContent=duration;$('chat-work-summary').textContent=duration?'Activity log · '+(active?'Working for ':'Worked for ')+duration:'Activity log'}

function activityIcon(phase,details={}){const tool=details?.tool;return ({read_file:'▤',list_dir:'▱',search_code:'⌕',file_patch:'✎',create_file:'✎',run_command:'⌨',verify:'✓'}[tool]||{optimizing:'≋',optimized:'≋',decomposing:'⑂',solving:'◇',synthesizing:'◆',reading_images:'▧',reading_image:'▧',image_observation:'▧',reading_files:'▤',file_observation:'▤',searching:'⌕',answering:'✦',checking:'✓',check_result:'✓',idle:'✓',completed:'✓',failed:'!',cancelled:'■'}[phase]||'·')}
function renderChatLineage(s){const row=$('chat-lineage');row.replaceChildren();row.hidden=!s.parent;if(!s.parent)return;row.append(document.createTextNode(s.parent.action==='redo'?'Redo in a new branch · Your original answer is saved. ':'Branched conversation · '));const link=element('a','Open original chat');link.href='#chat:'+s.parent.id;link.onclick=e=>{e.preventDefault();selectChat(s.parent.id).catch(error)};row.append(link)}

function compactActivity(events){const important=events.filter(e=>(e.phase==='reading_images'&&e.details?.file_id)||(e.phase==='reading_files'&&e.details?.passages)||(e.phase==='searching'&&e.details?.engines)||(e.phase==='optimizing'&&e.details?.method));const recent=events.slice(-2);return [...important.slice(-6),...recent.filter(e=>!important.includes(e))]}
window.addEventListener('hashchange',()=>{const hash=location.hash;if(/^#chat:[0-9a-f]{32}$/.test(hash)&&(chatCurrent!==hash.slice(6)||mode!=='chat'))selectChat(hash.slice(6)).catch(error);else if(/^#[0-9a-f]{32}$/.test(hash)&&(current!==hash.slice(1)||mode!=='code'))select(hash.slice(1)).catch(error)});

function activityLabel(e){if(e.phase==='reading_files'&&e.details?.passages&&e.details?.files){const p=e.details.passages.length,f=e.details.files.length;return `Read ${p} ${p===1?'passage':'passages'} from ${f} ${f===1?'file':'files'}`}return e.message}

function renderTeam(s,events=[]){
 const box=$('team-status');box.replaceChildren();box.hidden=!s.team;if(!s.team)return;
 const finished=events.find(e=>e.lane==='builder'&&['completed','cancelled','needs_attention'].includes(e.kind));const end=s.finished_at?Date.parse(s.finished_at):terminal.has(s.status)&&finished?Date.parse(finished.time):Date.now();box.append(element('p',(terminal.has(s.status)?'Worked for ':'Working for ')+formatDuration(Math.max(0,(end-Date.parse(s.created_at))/1000)),'note'));
 const lanes=element('div',undefined,'team-lanes');
 const builder=element('div');builder.append(element('strong','Builder · '+(s.profile==='quality'?'14B':s.model_config?.label||s.profile)),element('p',terminal.has(s.status)?s.status.replaceAll('_',' '):s.status.replaceAll('_',' ')+' · RX + CPU'));
 const helper=element('div'),h=s.team.helper||{},cancelledAfterFinish=s.status==='completed'&&h.status==='unavailable'&&events.some(e=>e.kind==='helper_unavailable'&&e.details?.error==='Cancelled');helper.append(element('strong','Helper · 2B'),element('p',(cancelledAfterFinish?'stopped':h.status||'disabled')+(h.role?' · '+h.role:'')),element('small',cancelledAfterFinish?'Builder finished; optional review stopped':h.reason||'Read-only advice · GTX'));
 const checks=element('div'),c=s.team.checks||{};checks.append(element('strong','Checks · CPU'),element('p',c.status||'waiting'),element('small',c.revision?'Revision '+c.revision.slice(0,12):'Start after a completed patch'));
 lanes.append(builder,helper,checks);box.append(lanes);
 box.append(element('p','Helper findings are suggestions. Only executable checks and the final builder review can approve a revision.','note'));
}
$('profile').addEventListener('change',()=>{const profile=$('profile').value,supported=['quality','roadmap'].includes(profile);$('team').disabled=!supported;$('team-note').textContent=profile==='roadmap'?'The automatic 7B builder uses small actions, deterministic checks, bounded recovery, and a read-only GTX helper when available.':supported?'Read-only 2B assistants use the GTX alongside your 14B builder. CPU checks run after each patch. Shared inference memory limit: 16GiB.':'CPU checks remain parallel. GPU assistants are enabled with the automatic 7B and 14B builder profiles.'});
