"use strict";
// Production workspace: one set of stateful components over the desktop API.
(() => {
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const svg=(name)=>{const paths={focus:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',panel:'M9 4v16M3 4h18v16H3z',spark:'m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z',more:'M4 12h1m6 0h1m6 0h1',download:'M4 16v5h16v-5M12 3v12m-5-5 5 5 5-5',play:'m8 5 11 7-11 7z',arrow:'M4 12h16m-6-6 6 6-6 6',doc:'M5 3h9l5 5v13H5zM14 3v6h5M9 13h6M9 17h6',check:'m5 12 4 4L19 6',close:'m6 6 12 12M6 18 18 6',target:'M12 2v5m0 10v5M2 12h5m10 0h5',mic:'M9 3h6v12H9zM5 10v2a7 7 0 0 0 14 0v-2M12 19v3'};return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+(paths[name]||paths.doc)+'"/></svg>';};
  const button=(label,fn,cls='w-btn')=>{const b=el('button',cls);b.type='button';b.innerHTML=label;b.onclick=fn;return b;};
  const replaceControl=(id,fn)=>{const old=$(id),n=old.cloneNode(true);old.replaceWith(n);n.onclick=fn;return n;};
  let prefs={font_size:15,reduce_motion:false,last_minutes:'',terms:[]}, homeFilter='all',homeSearch='',activeTab='review',loadToken=0;
  let segments=null,speakers=null,playToken=0,currentPlay=null,revision=0,saveTimer=null,queue=Promise.resolve(),undo=new Map(),selectedTerm='',locationIndex={};
  let settingsLoaded=false;
  const audio=new Audio();audio.preload='metadata';
  const modal=el('dialog','w-dialog');modal.innerHTML='<div class="w-dialog-head"><h2></h2><button type="button" aria-label="关闭">×</button></div><div class="w-dialog-body"></div><div class="w-dialog-foot"></div>';document.body.append(modal);
  modal.querySelector('button').onclick=()=>modal.close();
  const body=modal.querySelector('.w-dialog-body'),foot=modal.querySelector('.w-dialog-foot');
  function showModal(title){modal.querySelector('h2').textContent=title;body.replaceChildren();foot.replaceChildren();if(!modal.open)modal.showModal();}
  function closeButton(){return button('完成',()=>modal.close(),'w-btn primary');}
  async function call(name,...args){if(!state.apiReady)throw Error('请在桌面程序中使用此功能');const r=await api()[name](...args);if(!r.ok)throw Error(r.error||'操作未完成');return r;}
  async function savePrefs(changes){const r=await call('save_workspace',changes);prefs={...prefs,...r};applyPrefs();return r;}
  function applyPrefs(){document.documentElement.style.setProperty('--reading-size',prefs.font_size+'px');document.body.classList.toggle('reduce-motion',prefs.reduce_motion);}
  async function initPrefs(){if(!state.apiReady)return;try{prefs={...prefs,...await call('get_workspace')};settingsLoaded=true;applyPrefs();renderRecent();}catch(e){toast(e.message);}}
  window.addEventListener('pywebviewready',()=>setTimeout(initPrefs,150));setTimeout(initPrefs,700);
  const originalTitle=sessionTitle;sessionTitle=s=>s.title||originalTitle(s);
  function pending(s){return Number(s.pending_terms)||0;}
  function statusText(s){return pending(s)?'待校对 · '+pending(s):s.review_status==='done'?'已完成':s.review_status==='failed'?'需人工检查':'未校对';}
  function badge(s){return el('span','w-tag '+(pending(s)?'amber':s.review_status==='done'?'green':''),statusText(s));}
  function timeLabel(s){return s.started_at?s.started_at.replace('T',' ').slice(0,16):s.mtime||'时间未记录';}
  function durationLabel(s){return s.duration_seconds>0?Math.max(1,Math.round(s.duration_seconds/60))+' 分钟':'—';}
  // Workbench replaces the old marketing layout; existing help overlays are retained.
  const guide=$('btnGuide'),changelog=$('btnChangelog'),metrics=['metricMeetings','metricTranscribe','metricMinutes'].map($);
  const home=$('viewHome');home.replaceChildren();home.classList.add('workspace-home');
  home.innerHTML='<div class="w-page-heading"><div><div class="w-date"></div><h1>把讨论，变成下一步。</h1><p>从这里开始会议，或接着整理上次的想法。</p></div><div class="w-home-actions"></div></div><div class="w-home-lead"><section class="w-resume"></section><section class="w-queue"><h2>需要你看一眼</h2><div></div></section></div><section class="w-meetings"><div class="w-section-head"><h2>最近会议 <span id="wMeetingCount" class="w-tag"></span></h2><div class="w-table-tools"><div id="wFilters"></div><input id="wHomeSearch" placeholder="搜索会议名称" aria-label="搜索会议名称"></div></div><div class="w-table-scroll"><table><thead><tr><th>会议名称</th><th>会议时间</th><th>时长</th><th>状态</th><th></th></tr></thead><tbody id="recentList"></tbody></table></div></section><footer class="w-home-footer"><span>文件保存在本机 · 转写与生成使用云端服务</span><div></div></footer>';
  home.querySelector('.w-date').textContent=new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'});
  home.querySelector('.w-home-actions').append(button('↑ 导入文件',()=>setActiveView('import')),button(svg('mic')+' 开始会议',()=>setActiveView('record'),'w-btn primary'));
  for(const n of [guide,changelog]){n.className='w-link';n.querySelectorAll('span,small,i').forEach(x=>x.remove());home.querySelector('footer>div').append(n);}
  const hidden=el('div','hidden');hidden.append(...metrics);home.append(hidden);
  ['全部','待校对'].forEach((name,i)=>$('wFilters').append(button(name,()=>{homeFilter=i?'pending':'all';renderRecent();},'w-filter')));
  $('wHomeSearch').oninput=e=>{homeSearch=e.target.value;renderRecent();};
  renderRecent=function(){
    $('metricMeetings').textContent=state.sessions.length;$('wMeetingCount').textContent=state.sessions.length;
    [...$('wFilters').children].forEach((n,i)=>n.classList.toggle('active',homeFilter===(i?'pending':'all')));
    const resume=state.sessions.find(s=>s.minutes===prefs.last_minutes)||state.sessions[0];const slot=home.querySelector('.w-resume');slot.replaceChildren();
    slot.append(el('div','w-resume-label','▤ 继续上次的工作'),el('h2','',resume?sessionTitle(resume):'从第一场会议开始'));
    slot.append(el('p','',resume?timeLabel(resume)+' · '+(resume.detail_label||'简要')+'纪要':'录制一场会议，或导入已有的音频和视频。'));
    const bottom=el('div','w-resume-bottom');
    if(resume){const avatars=el('div','w-avatars');(resume.attendees||[]).slice(0,4).forEach(n=>avatars.append(el('span','',n.slice(-1))));const track=el('div','w-mini-progress'),bar=el('i');bar.style.width=(resume.total_terms?100*(resume.total_terms-pending(resume))/resume.total_terms:resume.review_status==='done'?100:0)+'%';track.append(bar);bottom.append(avatars,track,el('small','',pending(resume)?'还有 '+pending(resume)+' 个词语待确认':statusText(resume)),button('继续编辑 '+svg('arrow'),()=>openMinutes(resume.minutes),'w-btn primary small'));}
    else bottom.append(button('开始会议',()=>setActiveView('record'),'w-btn primary'));
    slot.append(bottom);
    const todo=home.querySelector('.w-queue>div');todo.replaceChildren();
    const n=state.sessions.filter(s=>pending(s)).length;
    for(const [title,note,count,fn] of [['等待校对','确认术语后即可导出',n,()=>{homeFilter='pending';renderRecent();home.querySelector('.w-meetings').scrollIntoView({block:'nearest'});}],['我的术语库','记住准确名称，减少重复修改',prefs.terms.length,showDictionary]]){
      const b=button('',fn,'w-queue-row');b.append(el('span','w-queue-icon',title==='等待校对'?'✓':'✧'));const text=el('div');text.append(el('strong','',title),el('small','',note));b.append(text,el('b','',count),el('span','','›'));todo.append(b);
    }
    const list=$('recentList');list.replaceChildren();const rows=state.sessions.filter(s=>(homeFilter!=='pending'||pending(s))&&sessionTitle(s).toLowerCase().includes(homeSearch.toLowerCase()));
    for(const s of rows){const tr=el('tr');tr.tabIndex=0;tr.setAttribute('aria-label','打开 '+sessionTitle(s));tr.onclick=()=>openMinutes(s.minutes);tr.onkeydown=e=>{if(e.key==='Enter')tr.click();};const title=el('td'),name=el('div','w-meeting-name');const symbol=el('span','w-doc');symbol.innerHTML=svg('doc');const copy=el('div');copy.append(el('strong','',sessionTitle(s)),el('small','',(s.attendees||[]).join('、')||s.detail_label+'纪要'));name.append(symbol,copy);title.append(name);const status=el('td');status.append(badge(s));tr.append(title,el('td','',timeLabel(s)),el('td','',durationLabel(s)),status,el('td','','→'));list.append(tr);}
    if(!rows.length){const tr=el('tr'),td=el('td','w-empty',state.sessions.length?'没有符合条件的会议':'还没有会议记录，完成录制或导入后会显示在这里');td.colSpan=5;tr.append(td);list.append(tr);}
  };
  renderSessionList=function(){const box=$('sessionList');box.replaceChildren();$('sessionCount').textContent=state.sessions.length+' 个纪要';const query=$('sessionSearch').value.toLowerCase();for(const s of state.sessions.filter(x=>sessionTitle(x).toLowerCase().includes(query))){const row=el('div','session-row'),b=button('',()=>openMinutes(s.minutes),'session-item'+(s.minutes===state.activeMinutes?' active':''));b.append(el('strong','',sessionTitle(s)),el('small','',(s.mtime||'').slice(0,11)),badge(s));const del=button(svg('close'),()=>requestDeleteSession(s),'session-delete');del.title='删除这次会议';del.setAttribute('aria-label','删除 '+sessionTitle(s));row.append(b,del);box.append(row);}if(!box.children.length)box.append(el('div','sidebar-empty','没有符合条件的会议'));};
  // Compact toolbar: primary action remains visible, utilities live in More.
  const top=document.querySelector('.editor-topline'),left=top.firstElementChild,actions=top.querySelector('.editor-actions');
  left.replaceChildren(button(svg('panel'),()=>document.body.classList.toggle('hide-history'),'w-icon'),el('h1','','纪要工作区'));
  left.firstChild.title='展开 / 收起会议列表';left.firstChild.setAttribute('aria-label','展开或收起会议列表');
  const saved=$('saveState'),exportButton=$('btnExport');const utilities=el('div','w-more-menu');utilities.hidden=true;
  ['btnAudioCleanup','btnOpenFolder','btnSaveMinutes'].forEach(id=>utilities.append($(id)));
  $('btnSpeakerMapping').classList.add('hidden');$('btnTranscript').classList.add('hidden');
  const focus=button(svg('focus'),()=>toggleFocus(),'w-icon');focus.id='wFocus';focus.title='专注模式';focus.setAttribute('aria-label','专注模式');
  const reviewToggle=button(svg('spark')+' 校对','', 'w-btn subtle');reviewToggle.id='wReviewToggle';reviewToggle.onclick=()=>{document.body.classList.toggle('hide-review');if(!document.body.classList.contains('hide-review'))switchTab('review');};
  const more=button(svg('more'),()=>{utilities.hidden=!utilities.hidden;},'w-icon');more.title='更多操作';more.setAttribute('aria-label','更多操作');
  actions.prepend(saved,focus,reviewToggle,more);actions.append(exportButton,utilities);exportButton.innerHTML=svg('download')+' 导出纪要';exportButton.className='w-btn primary';
  document.addEventListener('click',e=>{if(!utilities.contains(e.target)&&!more.contains(e.target))utilities.hidden=true;});
  function toggleFocus(force){const on=typeof force==='boolean'?force:!document.body.classList.contains('focus-editor');document.body.classList.toggle('focus-editor',on);focus.setAttribute('aria-pressed',String(on));focus.title=on?'退出专注模式（Esc）':'专注模式';focus.setAttribute('aria-label',focus.title);if(on&&state.activeView!=='minutes')setActiveView('minutes');}
  document.addEventListener('keydown',e=>{if(e.key==='Escape')toggleFocus(false);});
  const gen=$('minutesGenerationBar');gen.classList.add('w-generation-popover');gen.hidden=true;
  const detailButton=button('纪要档位 ▾',()=>{gen.hidden=!gen.hidden;},'w-btn small');detailButton.id='wDetailButton';document.querySelector('.document-head').append(detailButton);
  const originalGeneration=renderMinutesGeneration;renderMinutesGeneration=function(status){originalGeneration(status);detailButton.textContent=(detailLabels[state.activeDetailLevel]||'简要')+'纪要 ▾';};
  // Inspector panes keep their own scrolling; all remain in the same grid cell.
  const review=$('proofreadingPanel'),inspector=el('aside','w-inspector');review.replaceWith(inspector);const tabs=el('div','w-tabs'),peoplePane=el('div','w-pane hidden'),sourcePane=el('div','w-pane hidden');peoplePane.id='wPeople';sourcePane.id='wSource';
  for(const [label,key] of [['校对','review'],['参会人','people'],['原文','source']]){const b=button(label,()=>switchTab(key),'w-tab');b.dataset.tab=key;tabs.append(b);}
  inspector.append(tabs,review,peoplePane,sourcePane,el('footer','w-inspector-footer','原文依据保留 · 修改可撤回'));
  const audioBar=el('div','w-audio-bar hidden');audioBar.append(el('span','','正在试听'),button('停止',stopAudio,'w-link'));inspector.append(audioBar);
  function stopAudio(){playToken++;audio.pause();audio.removeAttribute('src');audio.load();if(currentPlay){currentPlay.textContent='▶';currentPlay.classList.remove('playing');}currentPlay=null;audioBar.classList.add('hidden');}
  async function playSegment(segment,b){if(currentPlay===b){stopAudio();return;}stopAudio();const token=playToken;if(!segments?.audio_url)return toast(segments?.audio_message||'本场会议没有可播放的录音');currentPlay=b;b.textContent='…';try{audio.src=segments.audio_url;await new Promise((resolve,reject)=>{audio.onloadedmetadata=resolve;audio.onerror=()=>reject(Error('当前音频格式无法播放或文件已清理'));});if(token!==playToken)return;audio.currentTime=segment.begin;audio.ontimeupdate=()=>{if(audio.currentTime>=segment.end)stopAudio();};audio.onended=stopAudio;await audio.play();if(token!==playToken){audio.pause();return;}b.textContent='■';b.classList.add('playing');audioBar.firstChild.textContent='正在试听 '+formatTime(segment.begin)+' — '+formatTime(segment.end);audioBar.classList.remove('hidden');}catch(e){if(token===playToken){stopAudio();toast(e.message||'无法播放录音');}}}
  function playButton(segment){const b=button('▶',()=>playSegment(segment,b),'w-play');b.setAttribute('aria-label','试听 '+formatTime(segment.begin)+' 的发言');b.disabled=!segments?.audio_url||segment.end<=segment.begin;b.title=b.disabled?(segments?.audio_message||'这段发言没有可用时间戳'):'试听这段发言';return b;}
  async function loadContext(){const token=++loadToken,path=state.activeMinutes;segments=null;speakers=null;peoplePane.textContent=sourcePane.textContent='正在读取会议资料…';if(!state.apiReady||!path){peoplePane.textContent=sourcePane.textContent='选择会议后显示';return;}try{const [seg,sp]=await Promise.all([call('get_meeting_segments',path),call('get_speaker_mapping',path)]);if(token!==loadToken||path!==state.activeMinutes)return;segments=seg;speakers=sp;state.speakerMapping={...sp.mapping};renderSource();renderPeople();}catch(e){if(token===loadToken)peoplePane.textContent=sourcePane.textContent=e.message;}}
  function switchTab(key){activeTab=key;[...tabs.children].forEach(n=>n.classList.toggle('active',n.dataset.tab===key));review.classList.toggle('hidden',key!=='review');peoplePane.classList.toggle('hidden',key!=='people');sourcePane.classList.toggle('hidden',key!=='source');if(key!=='review'&&!segments&&state.activeMinutes)loadContext();}
  openSpeakerMapping=()=>{document.body.classList.remove('hide-review');switchTab('people');};
  replaceControl('btnSpeakerMapping',openSpeakerMapping).classList.add('hidden');replaceControl('btnTranscript',()=>switchTab('source')).classList.add('hidden');
  function renderSource(){sourcePane.replaceChildren(el('div','w-pane-heading','会议转写'),el('p','w-hint','保留原始表述，方便对照纪要。'));if(!segments)return;if(!segments.audio_url)sourcePane.append(el('p','w-audio-unavailable',segments.audio_message));for(const s of segments.segments){const row=el('div','w-transcript-segment'),head=el('div','w-speaker-head');head.append(el('span','w-avatar',s.speaker.slice(-1)),el('strong','',s.speaker),el('time','',formatTime(s.begin)),playButton(s));row.append(head,el('p','',s.text));sourcePane.append(row);}if(!segments.segments.length)sourcePane.append(el('div','w-plain-transcript',segments.content||'本次会议没有转写内容'));}
  function renderPeople(){peoplePane.replaceChildren(el('div','w-pane-heading','匹配发言人'),el('p','w-hint','听取发言片段，再把说话人与姓名对应。'));if(!speakers)return;for(const s of speakers.speakers){const card=el('section','w-speaker-card'),head=el('div','w-speaker-head'),name=speakers.mapping[String(s.number)]||'';head.append(el('span','w-avatar',name.slice(-1)||s.number),el('strong','','说话人 '+s.number));const sample=segments?.segments.find(x=>x.number===s.number&&x.end>x.begin);if(sample)head.append(playButton(sample));const input=el('input','w-input');input.value=name;input.placeholder='选择或输入准确姓名';input.setAttribute('aria-label','说话人 '+s.number+' 的姓名');input.setAttribute('list','wSpeakerNames');input.maxLength=40;input.onchange=()=>updateSpeaker(s.number,input);input.hidden=true;const select=el('select');select.setAttribute('aria-label','说话人 '+s.number+' 的参会人');const options=[['','选择参会人'],...[...new Set([...speakers.candidates,...Object.values(speakers.mapping)])].filter(Boolean).map(n=>[n,n]),['__custom__','输入其他姓名…']];for(const [value,label]of options){const option=el('option','',label);option.value=value;select.append(option);}select.value=name;select.onchange=()=>{if(select.value==='__custom__'){input.hidden=false;input.value='';input.focus();}else updateSpeaker(s.number,select);};card.append(head,el('p','w-speaker-quote',sample?.text||s.sample||'没有可用发言片段'),select,input);peoplePane.append(card);}const list=el('datalist');list.id='wSpeakerNames';speakers.candidates.forEach(n=>{const o=el('option');o.value=n;list.append(o);});peoplePane.append(list,el('p','w-hint','选择后自动保存，姓名应用于当前会议。'));if(!speakers.speakers.length)peoplePane.append(el('p','w-hint','这场会议没有可匹配的说话人标签。'));}
  async function updateSpeaker(number,input){const path=state.activeMinutes;const old={...speakers.mapping},map={...old,[number]:input.value.trim()};input.disabled=true;try{if(!await saveMinutes())return;const r=await call('save_speaker_mapping',path,map);if(path!==state.activeMinutes)return;speakers.mapping=r.mapping;state.speakerMapping=r.mapping;const oldName=old[number],newName=r.mapping[number]||('说话人'+number);if(oldName&&oldName!==newName)replaceText(oldName,newName);replaceSpeakerLabels(r.mapping);markDirty();await saveMinutes();await loadContext();toast('说话人姓名已保存');}catch(e){toast(e.message);input.value=old[number]||'';}finally{input.disabled=false;}}
  function textMatches(term){const nodes=[],w=document.createTreeWalker($('minutesBody'),NodeFilter.SHOW_TEXT);while(w.nextNode()){let pos=0,i;while((i=w.currentNode.data.indexOf(term,pos))!==-1){nodes.push([w.currentNode,i]);pos=i+term.length;}}return nodes;}
  function replaceText(from,to){const w=document.createTreeWalker($('minutesBody'),NodeFilter.SHOW_TEXT);while(w.nextNode())w.currentNode.data=w.currentNode.data.split(from).join(to);}
  function locateTerm(item){const matches=textMatches(item.term);if(!matches.length)return toast('正文中已没有这个词，请检查当前写法');const index=(locationIndex[item.term]||0)%matches.length;locationIndex[item.term]=index+1;const [node,at]=matches[index],range=document.createRange();range.setStart(node,at);range.setEnd(node,at+item.term.length);getSelection().removeAllRanges();getSelection().addRange(range);const container=$('minutesBody'),rect=range.getBoundingClientRect();container.scrollTop+=rect.top-container.getBoundingClientRect().top-100;selectedTerm=item.term;renderProofreading(state.proofreading);}
  function reviewItems(){return(state.proofreading?.uncertain||[]).filter(x=>x.term);}
  function updateReviewState(){const all=reviewItems(),n=all.filter(x=>!['confirmed','replaced'].includes(x.decision)).length;tabs.firstChild.textContent='校对 '+n;$('wReviewToggle').innerHTML=svg('spark')+' 校对'+(n?' '+n:'完成');$('btnExport').disabled=!state.activeMinutes||n>0;$('btnExport').title=n?'还需确认 '+n+' 个术语':'导出纪要';const s=state.sessions.find(x=>x.minutes===state.activeMinutes);if(s){s.pending_terms=n;s.total_terms=all.length;}renderRecent();renderSessionList();}
  renderProofreading=function(data){state.proofreading=data||{uncertain:[]};review.replaceChildren();const items=reviewItems(),todo=items.filter(x=>!['confirmed','replaced'].includes(x.decision)),done=items.length-todo.length;const header=el('div','w-review-head'),title=el('div','w-review-title');title.append(el('strong','','术语确认'),el('span','',done+' / '+items.length+' 已完成'));const progress=el('div','w-review-progress');progress.setAttribute('role','progressbar');progress.setAttribute('aria-valuemin','0');progress.setAttribute('aria-valuemax',String(items.length||1));progress.setAttribute('aria-valuenow',String(done));const bar=el('i');bar.style.width=(items.length?done/items.length*100:100)+'%';progress.append(bar);header.append(title,progress,el('p','w-hint',data?.status==='failed'?'自动校对未完成，请人工检查关键事实。':data?.status==='done'?'定位正文，确认写法或替换名称。完成全部确认后即可导出。':'此纪要尚无校对结果，可重新生成后自动校对。'));review.append(header);
    for(const [index,item] of todo.entries()){const card=el('section','w-review-card'+(item.term===selectedTerm?' selected':'')),title=el('div','w-term-title'),matches=textMatches(item.term);title.append(el('span','w-term-index',index+1),el('strong','',item.term),el('small','',matches.length+' 处'));card.append(title,el('p','w-hint',item.reason||'请确认准确名称'));if(matches.length){const[node,at]=matches[0];card.append(el('blockquote','w-context','“'+node.data.slice(Math.max(0,at-25),at+item.term.length+45)+'”'));}card.append(button('⌖ 定位正文'+(locationIndex[item.term]?' · 第 '+locationIndex[item.term]+' 处':''),()=>locateTerm(item),'w-locate'));
      const input=el('input','w-input');input.placeholder='输入准确名称';input.setAttribute('aria-label',item.term+'的准确名称');input.value=item.replacement_draft||prefs.terms.find(t=>t.from===item.term)?.to||'';input.oninput=()=>{item.replacement_draft=input.value;};const actions=el('div','w-review-actions');actions.append(button('✓ 确认无误',()=>{item.decision='confirmed';markDirty();renderProofreading(state.proofreading);},'w-btn small'),button('全文替换',()=>requestReplacement(item,input.value.trim()),'w-btn subtle small'));card.append(input,actions);review.append(card);
    }
    if(!todo.length&&data?.status==='done'){const ready=el('div','w-complete');ready.append(el('span','','✓'),el('strong','','校对任务已完成'),el('p','','这份纪要可以导出了。'));review.append(ready);}
    if(done){const details=el('details','w-resolved');details.open=true;details.append(el('summary','','已完成 '+done+' 项'));for(const item of items.filter(x=>['confirmed','replaced'].includes(x.decision))){const row=el('div','w-resolved-row'),copy=el('div');copy.append(el('strong','',item.replacement||item.term),el('small','',item.decision==='confirmed'?'已确认无误':'已替换'));row.append(el('span','','✓'),copy,button(undo.has(item.term)?'撤回替换':'重新确认',()=>undoDecision(item),'w-link'));details.append(row);}review.append(details);}updateReviewState();
  };
  function requestReplacement(item,value){if(!value||value===item.term)return toast('请输入不同的准确名称，或确认无误');const count=textMatches(item.term).length;if(!count)return toast('正文已没有该词');showModal('替换 '+count+' 处词语');body.append(el('p','','仅修改当前会议纪要，原始转写保留不变。'),el('div','w-context',item.term+' → '+value));const label=el('label','w-check'),check=el('input');check.type='checkbox';check.checked=true;label.append(check,document.createTextNode('记入我的术语库，下次作为名称参考'));body.append(label);foot.append(button('取消',()=>modal.close()),button('确认替换',async()=>{const nodes=[...new Set(textMatches(item.term).map(x=>x[0]))],patch=nodes.map(node=>({node,before:node.data,after:node.data.split(item.term).join(value)}));for(const p of patch)p.node.data=p.after;undo.set(item.term,patch);item.decision='replaced';item.replacement=value;markDirty();renderProofreading(state.proofreading);modal.close();if(check.checked){try{await savePrefs({terms:[...prefs.terms.filter(x=>x.from!==item.term),{from:item.term,to:value}]});renderRecent();}catch(e){toast('替换已完成，但术语库未保存：'+e.message);}}},'w-btn primary'));}
  function undoDecision(item){const patch=undo.get(item.term);if(patch){if(patch.some(p=>!$('minutesBody').contains(p.node)||p.node.data!==p.after))return toast('替换后的段落已继续编辑，请先手动恢复该词');patch.forEach(p=>p.node.data=p.before);undo.delete(item.term);delete item.replacement;}item.decision='pending';markDirty();renderProofreading(state.proofreading);}
  // A single save queue serializes manual saves, autosaves, navigation and mapping.
  function saveSnapshot(){const path=state.activeMinutes;if(!path||!state.apiReady)return Promise.resolve(false);const content=editorToMarkdown($('minutesBody')),rev=revision,decisions=Object.fromEntries(reviewItems().map(x=>[x.term,{decision:x.decision||'pending',replacement:x.replacement||''}]));const job=async()=>{try{await call('save_minutes',path,content,decisions);if(path===state.activeMinutes&&rev===revision)markSaved();return true;}catch(e){toast('保存失败：'+e.message);return false;}};queue=queue.then(job,job);return queue;}
  saveMinutes=async function(){clearTimeout(saveTimer);return saveSnapshot();};
  const dirty=markDirty;markDirty=function(){dirty();revision++;clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveSnapshot(),1200);};
  const openBase=openMinutes;openMinutes=async function(path){if(state.dirty&&!await saveMinutes())return;stopAudio();const token=++loadToken;await openBase(path);if(state.activeMinutes!==path)return;undo.clear();selectedTerm='';locationIndex={};gen.hidden=true;switchTab('review');loadContext();try{await savePrefs({last_minutes:path});}catch(e){toast(e.message);}renderRecent();};
  const clearBase=clearEditor;clearEditor=function(){stopAudio();loadToken++;clearBase();segments=speakers=null;renderProofreading({uncertain:[]});peoplePane.textContent=sourcePane.textContent='选择会议后显示';};
  document.querySelector('.editor-footer>span').textContent='更改自动保存到本机';
  function showPreferences(){showModal('偏好设置');const row=el('div','w-setting-row'),copy=el('div');copy.append(el('strong','','正文阅读字号'),el('small','','只影响屏幕显示，不影响导出'));const select=el('select');for(const [value,label] of [[14,'紧凑 · 14'],[15,'标准 · 15'],[17,'舒适 · 17']]){const o=el('option','',label);o.value=value;select.append(o);}select.value=prefs.font_size;select.onchange=async()=>{try{await savePrefs({font_size:Number(select.value)});}catch(e){toast(e.message);select.value=prefs.font_size;}};row.append(copy,select);body.append(row);const motion=el('div','w-setting-row'),mc=el('div');mc.append(el('strong','','减少动态效果'),el('small','','关闭过渡动画'));const toggle=button('',async()=>{try{await savePrefs({reduce_motion:!prefs.reduce_motion});toggle.classList.toggle('on',prefs.reduce_motion);toggle.setAttribute('aria-checked',String(prefs.reduce_motion));}catch(e){toast(e.message);}},'w-toggle'+(prefs.reduce_motion?' on':''));toggle.setAttribute('role','switch');toggle.setAttribute('aria-label','减少动态效果');toggle.setAttribute('aria-checked',String(prefs.reduce_motion));motion.append(mc,toggle);body.append(motion);const terms=el('div','w-setting-row'),tc=el('div');tc.append(el('strong','','个人术语库'),el('small','',prefs.terms.length+' 个已记住的名称'));terms.append(tc,button('管理',showDictionary));body.append(terms);const conn=el('div','w-setting-row');conn.append(el('strong','','模型、设备与输出目录'),button('连接设置',()=>{modal.close();openSettings();}));body.append(conn);foot.append(closeButton());}
  async function showDictionary(){showModal('我的术语库');body.append(el('p','','确认过的名称用于后续会议生成参考。删除不会改动历史纪要。'));const list=el('div','w-dictionary');for(const item of prefs.terms){const row=el('div','w-term-row');row.append(el('span','',item.from),el('span','','→'),el('strong','',item.to),button('删除',async()=>{try{await savePrefs({terms:prefs.terms.filter(x=>x.from!==item.from)});showDictionary();renderRecent();}catch(e){toast(e.message);}},'w-link'));list.append(row);}if(!prefs.terms.length)list.append(el('p','w-empty','还没有保存的术语'));body.append(list);const form=el('div','w-term-form'),from=el('input','w-input'),to=el('input','w-input');from.placeholder='原词 / 常见误写';to.placeholder='准确名称';from.setAttribute('aria-label','原词');to.setAttribute('aria-label','准确名称');form.append(from,to,button('添加',async()=>{try{await savePrefs({terms:[...prefs.terms,{from:from.value.trim(),to:to.value.trim()}]});showDictionary();renderRecent();}catch(e){toast(e.message);}},'w-btn primary'));body.append(form);foot.append(closeButton());}
  replaceControl('btnSettings',showPreferences);
  renderRecent();renderSessionList();switchTab('review');applyPrefs();
  const signal = document.createElement('div'); signal.className = 'capture-signals';
  signal.innerHTML = ['会议内声','麦克风'].map((name,i) => `<div class="signal-track"><div class="signal-label"><strong>${name}</strong><span id="signalState${i}">待机</span></div><svg class="signal-wave" viewBox="0 0 220 45" preserveAspectRatio="none" role="img" aria-label="${name}音量"><polyline id="signalLine${i}" points="0,22 220,22"/></svg></div>`).join('');
  $('recHint').after(signal);
  const floating = document.createElement('div'); floating.className = 'floating-capture hidden';
  floating.innerHTML = '<i></i><span>录制中</span><strong></strong><button type="button">暂停外录</button><button type="button">返回录制</button>';
  document.body.append(floating);
  floating.querySelectorAll('button')[0].onclick = () => toggleMicCapture();
  floating.querySelectorAll('button')[1].onclick = () => setActiveView('record');
  const originalRecorder = renderRecorder;
  let targets = [0,0], amplitudes = [0,0], isRecording = false;
  renderRecorder = function(status) {
    originalRecorder(status);
    isRecording = status.phase === 'recording';
    const levels = status.recording_levels || {};
    targets = [levels.system || 0, status.mic_capture_enabled === false ? 0 : levels.mic || 0];
    document.querySelector('.capture-console').classList.toggle('active-capture',isRecording);
    $('signalState0').textContent = isRecording ? (targets[0] > .01 ? '声音输入中' : '暂无声音') : '待机';
    $('signalState1').textContent = isRecording ? (status.mic_capture_enabled === false ? '已暂停' : targets[1] > .01 ? '声音输入中' : '暂无声音') : '待机';
    floating.classList.toggle('hidden',!isRecording || state.activeView === 'record');
    floating.querySelector('strong').textContent = formatTime(status.elapsed);
    floating.querySelectorAll('button')[0].textContent = status.mic_capture_enabled === false ? '恢复外录' : '暂停外录';
  };
  const originalView=setActiveView;
  setActiveView=function(name,force){originalView(name,force);floating.classList.toggle('hidden',!isRecording || state.activeView==='record');};
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function frame(t) {
    for(let k=0;k<2;k++) {
      amplitudes[k] += ((isRecording ? targets[k] : 0)-amplitudes[k])*.13;
      const a = amplitudes[k] * 19;
      // An envelope visualization driven by measured RMS, not a fabricated waveform.
      const points = Array.from({length:56},(_,j) => {
        const x = j*4, envelope = Math.sin(Math.PI*j/55)**1.5;
        return `${x},${22 + a*envelope*Math.sin(j*.71+((reduced.matches || document.body.classList.contains('reduce-motion')) ? 0 : t*.004))}`;
      }).join(' ');
      $('signalLine'+k).setAttribute('points',points);
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  const viewBase=setActiveView;setActiveView=function(name,force){viewBase(name,force);if(state.activeView!=='minutes')toggleFocus(false);if(state.activeView!=='minutes')stopAudio();};
})();
