(() => {
  const settingsToken = JSON.parse(document.getElementById('session').textContent).token;
  async function settingsApi(path, body) {
    const response = await fetch('/api' + path, {method: body === undefined ? 'GET' : 'POST', headers: {'Content-Type':'application/json','X-Local-Coder-Token':settingsToken}, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data;
  }
  const make = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  function downloadJson(name, data) { const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})); link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000); }
  const dialog = document.getElementById('settings-dialog');
  const nav = document.getElementById('settings-nav');
  const body = document.getElementById('settings-section-body');
  const title = document.getElementById('settings-section-title');
  const search = document.getElementById('settings-search');
  const sections = [
    {id:'general', label:'General', icon:'⚙', group:'Settings', keywords:'appearance theme mode motion', content:`
      <p class="settings-lead">Make Lumina feel right for your workspace.</p>
      <h3>Appearance</h3>
      <div class="settings-row"><div><strong>Theme</strong><p>Follow your Quickshell theme or choose a Lumina theme.</p></div><button type="button" data-settings-action="theme" class="settings-row-action">Choose theme <span aria-hidden="true">↗</span></button></div>
      <div class="settings-row"><div><strong>Reduce motion</strong><p>Keep transitions and animation to a minimum in this browser.</p></div><label class="settings-switch"><input id="settings-motion" type="checkbox"><span aria-hidden="true"></span><span class="settings-sr-only">Reduce motion</span></label></div>
      <h3>Workspace</h3>
      <div class="settings-row"><div><strong>Current workspace</strong><p>Switch between conversation and coding. Lumina remembers the last mode you used.</p></div><div class="settings-button-group"><button type="button" data-settings-action="chat">Chat</button><button type="button" data-settings-action="code">Code</button></div></div>`},
    {id:'account', label:'Account', icon:'◎', group:'Settings', keywords:'profile local access login billing', content:`
      <p class="settings-lead">Your workspace runs on this computer.</p>
      <h3>Access</h3>
      <div class="settings-row"><div><strong>Local workspace</strong><p>Chats and coding runs are stored on the host computer.</p></div><span class="settings-badge">Active</span></div>
      <form id="settings-account-form" class="settings-form"><label>Username<input id="settings-username" autocomplete="username" required minlength="3" maxlength="40"></label><label>Current password<input id="settings-current-password" type="password" autocomplete="current-password" required></label><label>New password<input id="settings-new-password" type="password" autocomplete="new-password" minlength="12" required></label><label class="settings-checkbox"><input id="settings-signout-sessions" type="checkbox" checked> Sign out all existing home-network sessions, including this one</label><button class="primary" type="submit">Update credentials</button><p id="settings-account-status" class="settings-status" aria-live="polite"></p></form>
      <div class="settings-callout">Credentials protect the optional home-network gateway. They are never included in backups.</div>`},
    {id:'privacy', label:'Privacy', icon:'♧', group:'Settings', keywords:'data files search history storage', content:`
      <p class="settings-lead">Choose when a conversation can reach the web.</p>
      <h3>Data and web</h3>
      <div class="settings-row"><div><strong>Local inference</strong><p>Model requests and attached files are processed by services on this computer.</p></div><span class="settings-badge">Local</span></div>
      <div class="settings-row"><div><strong>Google web search</strong><p>Optional for each chat message. Search queries are sent online when you turn it on in the composer.</p></div><button type="button" data-settings-action="web">Open chat <span aria-hidden="true">↗</span></button></div>
      <div class="settings-row"><div><strong>Recovery preference collection</strong><p>Store sanitized local action pairs. Task text can still be private; inspect, redact, export, or delete it below.</p></div><label class="settings-switch"><input id="settings-preferences-enabled" type="checkbox"><span aria-hidden="true"></span><span class="settings-sr-only">Collect recovery preferences</span></label></div>
      <div class="settings-button-group"><button id="settings-preferences-redact" type="button">Redact sensitive patterns</button><button id="settings-preferences-export" type="button">Export records</button><button id="settings-preferences-delete" type="button">Delete all</button></div><p id="settings-preferences-status" class="settings-status" aria-live="polite"></p>
      <h3>Backup and restore</h3><div class="settings-button-group"><button id="settings-backup-export" type="button">Export backup</button><label class="settings-file-button">Restore backup<input id="settings-backup-import" type="file" accept="application/json,.json"></label></div><p class="settings-callout">Backups include conversations and user-controlled metadata. Credentials, raw attachment bytes, and model artifacts are excluded.</p>`},
    {id:'models', label:'Models & capabilities', icon:'✦', group:'Settings', keywords:'model deep thinking attachments parallel assistants artifact', content:`
      <p class="settings-lead">Use local models for chat and checked coding tasks.</p>
      <h3>Chat</h3>
      <div class="settings-row"><div><strong>Model and Deep Thinking</strong><p>Choose a model and reasoning option in the chat composer.</p></div><button type="button" data-settings-action="chat">Open chat <span aria-hidden="true">↗</span></button></div>
      <div class="settings-row"><div><strong>Files and previews</strong><p>Attach documents or images; generated interactive previews open beside the chat.</p></div><span class="settings-badge">Available</span></div>
      <h3>Code</h3>
      <div class="settings-row"><div><strong>Builder and assistants</strong><p>Choose a coding model and optional parallel assistants per task.</p></div><button type="button" data-settings-action="code">Open Code <span aria-hidden="true">↗</span></button></div>`},
    {id:'memory', label:'Memory', icon:'◷', group:'Settings', keywords:'context history persistent remembered cross chat', content:`
      <p class="settings-lead">Review exactly what Lumina may remember across chats.</p>
      <form id="settings-memory-form" class="settings-form"><label>Memory<textarea id="settings-memory-text" maxlength="2000" required placeholder="For example: Prefer concise explanations with a worked example."></textarea></label><label>Scope<select id="settings-memory-scope"><option value="global">All chats</option><option value="project">One project</option></select></label><label>Project<input id="settings-memory-project" placeholder="Project name or path"></label><button class="primary" type="submit">Add memory</button></form><div id="settings-memory-list" class="settings-managed-list"></div>
      <h3>Conversation context</h3>
      <div class="settings-row"><div><strong>Context optimization</strong><p>When a chat grows long, Lumina keeps selected excerpts from older messages within the model’s context limit.</p></div><span class="settings-badge">Automatic</span></div>
      <div class="settings-row"><div><strong>Saved history</strong><p>The full conversation remains available in Recent work even when older parts are condensed for a reply.</p></div><span class="settings-badge">On device</span></div>
      <div class="settings-callout">Used memories are listed in the saved response state and are always editable or forgettable here.</div>`},
    {id:'knowledge', label:'Knowledge library', icon:'▤', group:'Customize', keywords:'documents import retrieval citations provenance', content:`
      <p class="settings-lead">Import local documents for cited retrieval without changing model weights.</p><form id="settings-knowledge-form" class="settings-form"><label>Document<input id="settings-knowledge-file" type="file" accept=".pdf,.docx,.xlsx,.xls,.pptx,.csv,.txt,.md,.json,.log" required></label><label>Label<input id="settings-knowledge-label" maxlength="120"></label><label>Source or provenance<input id="settings-knowledge-source" maxlength="240" value="User import"></label><button class="primary" type="submit">Import document</button></form><p id="settings-knowledge-status" class="settings-status" aria-live="polite"></p><div id="settings-knowledge-list" class="settings-managed-list"></div>`},
    {id:'storage', label:'Storage & history', icon:'▱', group:'Settings', keywords:'attachments files usage delete archive chats search rename', content:`
      <p class="settings-lead">Find saved work and clean up files without breaking references.</p><h3>Attachments</h3><div id="settings-storage-summary"></div><div id="settings-storage-list" class="settings-managed-list"></div><h3>Archived conversations</h3><div id="settings-history-list" class="settings-managed-list"></div>`},
    {id:'datasets', label:'Datasets & training', icon:'◇', group:'Customize', keywords:'json jsonl dataset evaluation adapter train rollback', content:`
      <p class="settings-lead">Validate examples and keep evaluation separate from optional model training.</p><form id="settings-dataset-form" class="settings-form"><label>Name<input id="settings-dataset-name" maxlength="120" required></label><label>JSON dataset<input id="settings-dataset-file" type="file" accept="application/json,.json,.jsonl" required></label><label>Evaluation split (%)<input id="settings-dataset-eval" type="number" min="10" max="50" value="20"></label><button class="primary" type="submit">Validate and import</button></form><p id="settings-dataset-status" class="settings-status" aria-live="polite"></p><div id="settings-training-capability" class="settings-callout"></div><div id="settings-dataset-list" class="settings-managed-list"></div>`},
    {id:'queue', label:'Work queue', icon:'⑂', group:'Platform', keywords:'busy queued reorder cancel model owner', content:`
      <p class="settings-lead">Model work runs sequentially to preserve memory limits.</p><div id="settings-queue-owner" class="settings-callout"></div><div id="settings-queue-list" class="settings-managed-list"></div>`},
    {id:'skills', label:'Skills · Planned', icon:'▤', group:'Customize', keywords:'instructions reusable workflows planned', content:`
      <p class="settings-lead">Reusable instructions and workflows for Lumina.</p>
      <div class="settings-empty"><span aria-hidden="true">▤</span><h3>Skills library is planned</h3><p>There is no skill manager in Lumina yet. For now, include the instructions you need in a chat or coding task.</p></div>`},
    {id:'connectors', label:'Connectors · Planned', icon:'⊞', group:'Customize', keywords:'integration apps web google planned', content:`
      <p class="settings-lead">Connect Lumina to sources outside this computer.</p>
      <div class="settings-row"><div><strong>Google web search</strong><p>Available as an optional choice per chat message.</p></div><button type="button" data-settings-action="web">Open chat <span aria-hidden="true">↗</span></button></div>
      <div class="settings-callout">Account connectors are not available yet.</div>`},
    {id:'plugins', label:'Plugins · Planned', icon:'◇', group:'Customize', keywords:'extensions tools install planned', content:`
      <p class="settings-lead">Extend the workspace with additional tools.</p>
      <div class="settings-empty"><span aria-hidden="true">◇</span><h3>Plugin management is planned</h3><p>Lumina does not currently install or manage plugins from this dashboard.</p></div>`},
    {id:'notifications', label:'Notifications', icon:'♧', group:'Settings', keywords:'alerts completions desktop', content:`
      <p class="settings-lead">Keep track of responses and long running tasks.</p>
      <div class="settings-row"><div><strong>In app progress</strong><p>Chat responses and coding tasks show their progress in the workspace.</p></div><span class="settings-badge">Available</span></div>
      <div class="settings-row"><div><strong>Browser completion alerts</strong><p>Notify when a task or chat finishes while this page is open.</p></div><label class="settings-switch"><input id="settings-notifications" type="checkbox"><span aria-hidden="true"></span><span class="settings-sr-only">Browser completion alerts</span></label></div><div class="settings-callout">Email notifications are planned and are not available.</div>`},
    {id:'advanced', label:'Advanced', icon:'⌘', group:'Platform', keywords:'project checks hardware local', content:`
      <p class="settings-lead">Task specific controls for the local coding workspace.</p>
      <div class="settings-row"><div><strong>Project folder and required check</strong><p>Set these for each coding task under Project and checks.</p></div><button type="button" data-settings-action="code">Open Code <span aria-hidden="true">↗</span></button></div>
      <div class="settings-row"><div><strong>Hardware status</strong><p>The sidebar and connection indicator show local inference availability.</p></div><span class="settings-badge muted">Local</span></div>`}
  ];
  let selected = 'general';
  let returnFocus = null;
  let restoreFocus = true;
  let renderRevision = 0;
  const byId = id => sections.find(section => section.id === id);
  const setMotion = enabled => {
    document.documentElement.classList.toggle('settings-reduced-motion', enabled);
    try { localStorage.setItem('lumina-reduced-motion', String(enabled)); } catch {}
  };
  try { document.documentElement.classList.toggle('settings-reduced-motion', localStorage.getItem('lumina-reduced-motion') === 'true'); } catch {}

  function managedRow(title, detail, actions=[]) {
    const row=make('div',undefined,'settings-managed-row'),copy=make('div');copy.append(make('strong',title),make('p',detail));row.append(copy);
    const buttons=make('div',undefined,'settings-button-group');for(const [label,handler] of actions){const button=make('button',label);button.type='button';button.onclick=handler;buttons.append(button)}
    if(actions.length)row.append(buttons);return row;
  }
  async function hydrateSection(sectionId, revision) {
    const active = () => revision === renderRevision && selected === sectionId && dialog.open;
    if (!active()) return;
    if (sectionId === 'account') {
      const account=await settingsApi('/account');
      if(!active())return;
      const form=document.getElementById('settings-account-form');
      if(!account.configured){form.hidden=true;document.getElementById('settings-account-status').textContent='Home-network sign in is not configured.';return}
      document.getElementById('settings-username').value=account.username||'';
      form.onsubmit=async event=>{event.preventDefault();const status=document.getElementById('settings-account-status');status.textContent='Updating…';try{const result=await settingsApi('/account/credentials',{username:document.getElementById('settings-username').value,current_password:document.getElementById('settings-current-password').value,new_password:document.getElementById('settings-new-password').value,invalidate_sessions:document.getElementById('settings-signout-sessions').checked});form.reset();document.getElementById('settings-username').value=result.username;status.textContent=result.sessions_invalidated?'Credentials updated; other sessions were signed out.':'Credentials updated.'}catch(error){status.textContent=error.message}};
    } else if (sectionId === 'privacy') {
      const data=await settingsApi('/preferences');
      if(!active())return;
      const toggle=document.getElementById('settings-preferences-enabled'),status=document.getElementById('settings-preferences-status');toggle.checked=data.settings.collection_enabled;
      toggle.onchange=async()=>{try{await settingsApi('/preferences/settings',{collection_enabled:toggle.checked});status.textContent=toggle.checked?'Local collection enabled.':'Collection disabled.'}catch(error){status.textContent=error.message;toggle.checked=!toggle.checked}};
      document.getElementById('settings-preferences-redact').onclick=async()=>{try{const result=await settingsApi('/preferences/redact',{});status.textContent=`Redacted ${result.fields_redacted} field(s).`}catch(error){status.textContent=error.message}};
      document.getElementById('settings-preferences-export').onclick=()=>downloadJson('lumina-preferences.json',{format:'lumina-preferences-v1',records:data.records});
      document.getElementById('settings-preferences-delete').onclick=async()=>{if(!confirm('Delete all saved recovery preference records?'))return;try{const result=await settingsApi('/preferences/delete',{});status.textContent=`Deleted ${result.deleted} record(s).`}catch(error){status.textContent=error.message}};
      document.getElementById('settings-backup-export').onclick=async()=>downloadJson('lumina-backup.json',await settingsApi('/backup'));
      document.getElementById('settings-backup-import').onchange=async event=>{try{const payload=JSON.parse(await event.target.files[0].text());const result=await settingsApi('/backup/restore',payload);status.textContent=`Restored ${result.restored_chats} conversation(s). Safety backup: ${result.safety_backup}`}catch(error){status.textContent=error.message}};
    } else if (sectionId === 'memory') {
      const list=document.getElementById('settings-memory-list');async function reload(){const items=await settingsApi('/memories');if(!active())return;list.replaceChildren(...items.map(item=>managedRow(item.text,`${item.scope}${item.project?' · '+item.project:''} · ${item.source}`,[['Forget',async()=>{await settingsApi('/memories/'+item.id+'/delete',{});reload()}]])));if(!items.length)list.append(make('p','No cross-chat memories saved.','settings-callout'))}await reload();
      if(!active())return;
      document.getElementById('settings-memory-form').onsubmit=async event=>{event.preventDefault();await settingsApi('/memories',{text:document.getElementById('settings-memory-text').value,scope:document.getElementById('settings-memory-scope').value,project:document.getElementById('settings-memory-project').value||null,source:'Settings'});event.target.reset();await reload()};
    } else if (sectionId === 'knowledge') {
      const list=document.getElementById('settings-knowledge-list'),status=document.getElementById('settings-knowledge-status');async function reload(){const items=await settingsApi('/knowledge');if(!active())return;list.replaceChildren(...items.map(item=>managedRow(item.label,`${item.characters.toLocaleString()} characters · ${item.source}`,[['Remove',async()=>{await settingsApi('/knowledge/'+item.id+'/delete',{});reload()}]])));if(!items.length)list.append(make('p','No documents imported.','settings-callout'))}await reload();
      if(!active())return;
      document.getElementById('settings-knowledge-form').onsubmit=async event=>{event.preventDefault();const file=document.getElementById('settings-knowledge-file').files[0];if(!file)return;status.textContent='Reading document locally…';try{const upload=await fetch('/api/attachments',{method:'POST',headers:{'Content-Type':file.type||'application/octet-stream','X-Local-Coder-Token':settingsToken,'X-Upload-Name':encodeURIComponent(file.name)},body:file});const metadata=await upload.json();if(!upload.ok)throw new Error(metadata.error||'Upload failed');await settingsApi('/knowledge',{attachment_id:metadata.id,label:document.getElementById('settings-knowledge-label').value||file.name,source:document.getElementById('settings-knowledge-source').value||'User import',scope:'global'});event.target.reset();status.textContent='Imported. Future relevant chats can cite retrieved passages.';await reload()}catch(error){status.textContent=error.message}};
    } else if (sectionId === 'storage') {
      const data=await settingsApi('/attachments');if(!active())return;const summary=document.getElementById('settings-storage-summary'),list=document.getElementById('settings-storage-list');summary.textContent=`${data.active_files} active file(s) · ${(data.bytes/1048576).toFixed(1)} MB`;
      list.replaceChildren(...data.items.map(item=>managedRow(item.name,`${item.archived?'Archived · ':''}${item.reference_count} saved reference(s) · ${(item.bytes/1024).toFixed(1)} KB`,[[item.archived?'Restore':'Archive',async()=>{await settingsApi('/attachments/'+item.id+'/archive',{archived:!item.archived});hydrateSection(sectionId,revision)}],...(item.reference_count?[]:[['Delete',async()=>{if(confirm('Permanently delete this unreferenced file?')){await settingsApi('/attachments/'+item.id+'/delete',{});hydrateSection(sectionId,revision)}}]])])));if(!data.items.length)list.append(make('p','No stored attachments.','settings-callout'));
      const chats=await settingsApi('/chats?archived=true&page_size=100');if(!active())return;const history=document.getElementById('settings-history-list');history.replaceChildren(...chats.map(chat=>managedRow(chat.title,new Date(chat.updated_at).toLocaleString(),[['Restore',async()=>{await settingsApi('/chats/'+chat.id+'/archive',{archived:false});hydrateSection(sectionId,revision)}]])));if(!chats.length)history.append(make('p','No archived conversations.','settings-callout'));
    } else if (sectionId === 'datasets') {
      const data=await settingsApi('/datasets');if(!active())return;const list=document.getElementById('settings-dataset-list'),status=document.getElementById('settings-dataset-status');document.getElementById('settings-training-capability').textContent=data.training.available?'Local adapter training is available.':data.training.reason;
      list.replaceChildren(...data.items.map(item=>managedRow(item.name,`${item.training_rows} training · ${item.evaluation_rows} evaluation · ${item.rejected_rows} rejected`,[['Delete',async()=>{await settingsApi('/datasets/'+item.id+'/delete',{});hydrateSection(sectionId,revision)}],['Train',async()=>{try{await settingsApi('/datasets/'+item.id+'/train',{})}catch(error){status.textContent=error.message}}]])));
      document.getElementById('settings-dataset-form').onsubmit=async event=>{event.preventDefault();try{const file=document.getElementById('settings-dataset-file').files[0],text=await file.text();let rows;if(file.name.toLowerCase().endsWith('.jsonl'))rows=text.split(/\r?\n/).filter(Boolean).map(line=>JSON.parse(line));else{const parsed=JSON.parse(text);rows=Array.isArray(parsed)?parsed:parsed.rows}const result=await settingsApi('/datasets/import',{name:document.getElementById('settings-dataset-name').value,rows,evaluation_percent:Number(document.getElementById('settings-dataset-eval').value),provenance:file.name});status.textContent=`Imported ${result.rows} unique row(s); ${result.rejected_rows} rejected.`;event.target.reset();await hydrateSection(sectionId,revision)}catch(error){status.textContent=error.message}};
    } else if (sectionId === 'queue') {
      const data=await settingsApi('/activity');if(!active())return;const owner=document.getElementById('settings-queue-owner'),list=document.getElementById('settings-queue-list');owner.textContent=data.active?data.active.label:'The local model is available.';list.replaceChildren(...data.queue.map(item=>managedRow(`${item.position||'—'} · ${item.label}`,`${item.kind} · ${item.status}${item.error?' · '+item.error:''}`,item.status==='queued'?[['↑',async()=>{await settingsApi('/queue/'+item.id+'/up',{});hydrateSection(sectionId,revision)}],['↓',async()=>{await settingsApi('/queue/'+item.id+'/down',{});hydrateSection(sectionId,revision)}],['Cancel',async()=>{await settingsApi('/queue/'+item.id+'/cancel',{});hydrateSection(sectionId,revision)}]]:[])));if(!data.queue.length)list.append(make('p','No queued work.','settings-callout'));
    } else if (sectionId === 'notifications') {
      const toggle=document.getElementById('settings-notifications');toggle.checked=localStorage.getItem('lumina-notifications')==='true';toggle.onchange=async()=>{if(toggle.checked&&'Notification'in window&&Notification.permission==='default')await Notification.requestPermission();localStorage.setItem('lumina-notifications',String(toggle.checked&&Notification.permission==='granted'));toggle.checked=localStorage.getItem('lumina-notifications')==='true'};
    }
  }

  function renderNav() {
    const query = search.value.trim().toLowerCase();
    const matches = sections.filter(section => (section.label + ' ' + section.keywords + ' ' + section.content.replace(/<[^>]+>/g, ' ')).toLowerCase().includes(query));
    nav.replaceChildren();
    if (!matches.length) {
      const empty = document.createElement('p'); empty.className = 'settings-no-results'; empty.textContent = 'No settings found.'; nav.append(empty); return;
    }
    if (!matches.some(section => section.id === selected)) selected = matches[0].id;
    for (const group of ['Settings', 'Customize', 'Platform']) {
      const items = matches.filter(section => section.group === group);
      if (!items.length) continue;
      const heading = document.createElement('p'); heading.className = 'settings-nav-group'; heading.textContent = group; nav.append(heading);
      for (const section of items) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'settings-nav-item'; button.dataset.section = section.id;
        button.setAttribute('aria-current', section.id === selected ? 'page' : 'false');
        const icon = document.createElement('span'); icon.className = 'settings-nav-icon'; icon.setAttribute('aria-hidden', 'true'); icon.textContent = section.icon;
        button.append(icon, document.createTextNode(section.label)); button.addEventListener('click', () => select(section.id)); nav.append(button);
      }
    }
    renderSection();
  }
  function select(id) { selected = id; renderNav(); document.querySelector('.settings-content').scrollTop = 0; }
  function renderSection() {
    const section = byId(selected),revision=++renderRevision; title.textContent = section.label; body.innerHTML = section.content;
    const motion = document.getElementById('settings-motion');
    if (motion) {
      motion.checked = document.documentElement.classList.contains('settings-reduced-motion');
      motion.addEventListener('change', () => setMotion(motion.checked));
    }
    hydrateSection(section.id,revision).catch(error => { if(revision!==renderRevision||selected!==section.id)return;const status=body.querySelector('.settings-status'); if(status)status.textContent=error.message; else body.append(make('p',error.message,'settings-callout')); });
  }
  function close(restore = true) { restoreFocus = restore; dialog.close(); }
  document.getElementById('settings-open').addEventListener('click', () => {
    returnFocus = document.activeElement; search.value = ''; selected = 'general'; renderNav(); dialog.showModal(); search.focus();
  });
  document.getElementById('settings-close').addEventListener('click', () => close());
  document.getElementById('settings-close-mobile').addEventListener('click', () => close());
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  dialog.addEventListener('close', () => { renderRevision++;if (restoreFocus) returnFocus?.focus(); restoreFocus = true; });
  search.addEventListener('input', renderNav);
  body.addEventListener('click', event => {
    const action = event.target.closest('[data-settings-action]')?.dataset.settingsAction;
    if (!action) return;
    close(false);
    if (action === 'theme') document.getElementById('theme-picker-toggle').click();
    else {
      document.getElementById(action === 'code' ? 'mode-code' : 'mode-chat').click();
      if (action === 'web') document.getElementById('chat-web').focus();
    }
  });
})();
