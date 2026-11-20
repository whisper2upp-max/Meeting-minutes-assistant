"use strict";
// Production workspace: one set of stateful components over the desktop API.
(() => {
  const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const svg=(name)=>{const paths={focus:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',panel:'M9 4v16M3 4h18v16H3z',spark:'m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z',more:'M4 12h1m6 0h1m6 0h1',download:'M4 16v5h16v-5M12 3v12m-5-5 5 5 5-5',play:'m8 5 11 7-11 7z',arrow:'M4 12h16m-6-6 6 6-6 6',doc:'M5 3h9l5 5v13H5zM14 3v6h5M9 13h6M9 17h6',check:'m5 12 4 4L19 6',close:'m6 6 12 12M6 18 18 6',target:'M12 2v5m0 10v5M2 12h5m10 0h5',mic:'M9 3h6v12H9zM5 10v2a7 7 0 0 0 14 0v-2M12 19v3'};return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="'+(paths[name]||paths.doc)+'"/></svg>';};
  const button=(label,fn,cls='w-btn')=>{const b=el('button',cls);b.type='button';b.innerHTML=label;b.onclick=fn;return b;};
  const replaceControl=(id,fn)=>{const old=$(id),n=old.cloneNode(true);old.replaceWith(n);n.onclick=fn;return n;};
  let prefs={font_size:15,reduce_motion:false,last_minutes:'',terms:[]}, homeFilter='all',homeSearch='',activeTab='review',loadToken=0;
  let segments=null,speakers=null,playToken=0,currentPlay=null,revision=0,saveTimer=null,queue=Promise.resolve(),undo=new Map(),selectedTerm='',locationIndex=Object.create(null);
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
  const home = $('viewHome');
  home.querySelector('.w-date').textContent = new Date().toLocaleDateString('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric', weekday: 'long'
  });
  $('btnDictionary').onclick = showDictionary;
  for (const filter of $('wFilters').children) {
    filter.onclick = () => { homeFilter = filter.value; renderMeetingTable(); };
  }
  $('wHomeSearch').oninput = event => { homeSearch = event.target.value; renderMeetingTable(); };

  // The static cover needs painting only when its dimensions change.
  const canvas = home.querySelector('.soundprint');
  function drawSoundprint() {
    const {width, height} = canvas.getBoundingClientRect();
    if (!width || !height) return;
    const scale = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    const ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.fillStyle = 'rgba(212,193,228,.20)';
    for (let x = 8; x < width; x += 19) {
      for (let y = 8; y < height; y += 19) ctx.fillRect(x, y, 1, 1);
    }
    for (const second of [false, true]) {
      const gradient = ctx.createLinearGradient(0, 0, width, 0);
      gradient.addColorStop(0, 'rgba(169,137,213,.08)');
      gradient.addColorStop(.46, second ? 'rgba(179,219,207,.64)' : 'rgba(219,178,247,.87)');
      gradient.addColorStop(1, second ? 'rgba(200,238,219,.85)' : 'rgba(147,105,196,.60)');
      ctx.strokeStyle = gradient;
      ctx.lineWidth = .8;
      for (let row = 0; row <= 42; row++) {
        const u = row / 42;
        ctx.beginPath();
        for (let x = 0; x <= width + 2; x += 2) {
          const phase = x / width * 7.6 + (second ? 1.05 : -.35);
          const center = .49 + .16 * Math.sin(phase + u * 2.4) + .12 * Math.cos(phase * 1.85 - u * 2.8);
          const y = height * (center + (u - .5) * .29 + (second ? .09 : -.025));
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
    }
  }
  new ResizeObserver(drawSoundprint).observe(canvas);

  function renderResume() {
    const session = state.sessions.find(s => s.minutes === prefs.last_minutes) || state.sessions[0];
    $('resumeLabel').textContent = session ? '继续上次编辑' : '开始第一场会议';
    $('resumeTitle').textContent = session ? sessionTitle(session) : '录下你的第一场会议';
    $('resumeMeta').textContent = session
      ? [timeLabel(session), session.duration_seconds > 0 ? durationLabel(session) : '', (session.detail_label || '简要') + '纪要'].filter(Boolean).join(' · ')
      : '可以录制会议，也可以导入已有的音频或视频。';
    $('resumeStatus').textContent = session ? statusText(session) : '';
    $('resumeAction').innerHTML = (session ? '继续编辑 ' : '前往录制 ') + svg('arrow');
    $('resumeAction').onclick = () => session ? openMinutes(session.minutes) : setActiveView('record');
  }

  async function openTask(session, term) {
    if (!await openMinutes(session.minutes) || state.activeView !== 'minutes') return;
    toggleFocus(false);
    document.body.classList.remove('hide-review');
    switchTab('review');
    const item = reviewItems().find(x => x.term === term && !['confirmed', 'replaced'].includes(x.decision));
    if (!item) return toast('该术语已处理');
    selectedTerm = item.term;
    if (textMatches(item.term).length) locateTerm(item);
    else renderProofreading(state.proofreading);
    review.querySelector('.w-review-card.selected')?.scrollIntoView({block: 'nearest'});
  }

  function renderQueue() {
    const count = state.sessions.reduce((sum, s) => sum + pending(s), 0);
    $('queueCount').textContent = count + ' 项';
    const list = $('queueItems');
    list.replaceChildren();
    for (const session of state.sessions) {
      for (const term of session.pending_preview || []) {
        const row = button('', () => openTask(session, term), 'w-queue-row');
        const label = el('div');
        label.append(el('strong', '', term), el('small', '', sessionTitle(session)));
        const index = String(list.childElementCount + 1).padStart(2, '0');
        row.append(el('span', 'queue-index', index), label, el('span', 'queue-arrow', '›'));
        list.append(row);
        if (list.childElementCount === 3) return;
      }
    }
    if (!list.childElementCount) list.append(el('p', 'w-empty', state.sessions.length ? '当前没有待确认的术语' : '生成纪要后，待确认的术语会出现在这里。'));
  }

  function renderMeetingTable() {
    $('wMeetingCount').textContent = state.sessions.length;
    for (const filter of $('wFilters').children) {
      const active = filter.value === homeFilter;
      filter.classList.toggle('active', active);
      filter.setAttribute('aria-pressed', String(active));
    }
    const list = $('recentList');
    list.replaceChildren();
    const query = homeSearch.trim().toLowerCase();
    const rows = state.sessions.filter(s => (homeFilter !== 'pending' || pending(s)) && sessionTitle(s).toLowerCase().includes(query));
    for (const session of rows) {
      const tr = el('tr');
      tr.tabIndex = 0;
      tr.setAttribute('aria-label', '打开 ' + sessionTitle(session));
      tr.onclick = () => openMinutes(session.minutes);
      tr.onkeydown = e => { if (e.key === 'Enter') tr.click(); };
      const title = el('td'), name = el('div', 'w-meeting-name'), symbol = el('span', 'w-doc');
      symbol.innerHTML = svg('doc');
      const copy = el('div');
      copy.append(el('strong', '', sessionTitle(session)), el('small', '', (session.attendees || []).join('、') || (session.detail_label || '简要') + '纪要'));
      name.append(symbol, copy);
      title.append(name);
      const status = el('td');
      status.append(badge(session));
      tr.append(title, el('td', '', timeLabel(session)), el('td', '', durationLabel(session)), status, el('td', '', '→'));
      list.append(tr);
    }
    if (!rows.length) {
      const tr = el('tr'), td = el('td', 'w-empty', state.sessions.length ? '没有符合条件的会议' : '完成录制或导入后，可在这里打开纪要');
      td.colSpan = 5;
      tr.append(td);
      list.append(tr);
    }
  }
  renderRecent = function() {
    renderResume();
    renderQueue();
    renderMeetingTable();
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
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.open)toggleFocus(false);});
  const gen=$('minutesGenerationBar');gen.classList.add('w-generation-popover');gen.hidden=true;
  const detailButton=button('纪要档位 ▾',()=>{gen.hidden=!gen.hidden;},'w-btn small');detailButton.id='wDetailButton';document.querySelector('.document-head').append(detailButton);
  const originalGeneration=renderMinutesGeneration;renderMinutesGeneration=function(status){originalGeneration(status);detailButton.textContent=(detailLabels[state.activeDetailLevel]||'简要')+'纪要 ▾';};
  const titleInput=$('documentTitle');titleInput.maxLength=120;titleInput.title='点击修改会议标题，自动保存';
  let savedTitle='';
  titleInput.addEventListener('input',()=>{if(state.activeMinutes){markDirty();}});
  titleInput.addEventListener('blur',()=>{if(state.activeMinutes&&!titleInput.value.trim()){titleInput.value=savedTitle;markDirty();toast('标题不能为空，已恢复原标题');}});
  titleInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();titleInput.blur();saveMinutes();}if(e.key==='Escape'){titleInput.value=savedTitle;titleInput.blur();}});
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
  function textMatches(term){if(!term)return [];const nodes=[],w=document.createTreeWalker($('minutesBody'),NodeFilter.SHOW_TEXT);while(w.nextNode()){let pos=0,i;while((i=w.currentNode.data.indexOf(term,pos))!==-1){nodes.push([w.currentNode,i]);pos=i+term.length;}}return nodes;}
  function replaceText(from,to){const w=document.createTreeWalker($('minutesBody'),NodeFilter.SHOW_TEXT);while(w.nextNode())w.currentNode.data=w.currentNode.data.split(from).join(to);}
  function matchRange(node, offset, term) {
    const range = document.createRange();
    range.setStart(node, offset);
    range.setEnd(node, offset + term.length);
    return range;
  }
  function paintReviewTerms() {
    if (!window.CSS?.highlights || !window.Highlight) return;
    const pending = new Highlight();
    for (const item of reviewItems()) {
      if (['confirmed', 'replaced'].includes(item.decision)) continue;
      for (const [node, offset] of textMatches(item.term)) pending.add(matchRange(node, offset, item.term));
    }
    CSS.highlights.set('pending-terms', pending);
    CSS.highlights.delete('located-term');
    const index = locationIndex[selectedTerm];
    const match = index && textMatches(selectedTerm)[index - 1];
    if (match) CSS.highlights.set('located-term', new Highlight(matchRange(...match, selectedTerm)));
  }
  function locateTerm(item) {
    const matches = textMatches(item.term);
    if (!matches.length) return toast('正文中已没有这个词，请检查当前写法');
    const index = (locationIndex[item.term] || 0) % matches.length;
    locationIndex[item.term] = index + 1;
    selectedTerm = item.term;
    const range = matchRange(...matches[index], item.term);
    const container = $('minutesBody');
    container.scrollTop += range.getBoundingClientRect().top - container.getBoundingClientRect().top - 100;
    if (!window.CSS?.highlights || !window.Highlight) {
      getSelection().removeAllRanges();
      getSelection().addRange(range);
    }
    renderProofreading(state.proofreading);
  }
  function reviewItems(){return(state.proofreading?.uncertain||[]).filter(x=>x.term);}
  function updateReviewState() {
    const all = reviewItems();
    const pending = all.filter(item => !['confirmed', 'replaced'].includes(item.decision));
    const count = pending.length;
    tabs.firstChild.textContent = '校对 ' + count;
    $('wReviewToggle').innerHTML = svg('spark') + (count ? ' 校对 ' + count : ' 校对完成');
    $('btnExport').disabled = !state.activeMinutes || count > 0;
    $('btnExport').title = count ? '还需确认 ' + count + ' 个术语' : '导出纪要';
    const session = state.sessions.find(s => s.minutes === state.activeMinutes);
    if (session) {
      session.pending_terms = count;
      session.total_terms = all.length;
      session.pending_preview = pending.slice(0, 3).map(item => item.term);
    }
    renderRecent();
    renderSessionList();
  }
  function addManualTerm(value){
    const term=value.trim();
    if(!state.activeMinutes)return toast('请先选择会议');
    if(!term||term.length>120)return toast('请输入 1–120 个字符的术语');
    const existing=reviewItems().find(x=>x.term===term);
    if(existing){selectedTerm=term;renderProofreading(state.proofreading);return toast('这个术语已在校对列表中，可定位或重新确认');}
    if(!textMatches(term).length)return toast('正文中没有找到“'+term+'”，请检查大小写和写法');
    state.proofreading.uncertain=state.proofreading.uncertain||[];
    state.proofreading.uncertain.push({term,source:'manual',reason:'手动添加，请确认准确名称',decision:'pending'});
    selectedTerm=term;markDirty();renderProofreading(state.proofreading);
  }
  renderProofreading=function(data){state.proofreading=data||{uncertain:[]};review.replaceChildren();const items=reviewItems(),todo=items.filter(x=>!['confirmed','replaced'].includes(x.decision)),done=items.length-todo.length;const header=el('div','w-review-head'),title=el('div','w-review-title');title.append(el('strong','','术语确认'),el('span','',done+' / '+items.length+' 已完成'));const progress=el('div','w-review-progress');progress.setAttribute('role','progressbar');progress.setAttribute('aria-valuemin','0');progress.setAttribute('aria-valuemax',String(items.length||1));progress.setAttribute('aria-valuenow',String(done));const bar=el('i');bar.style.width=(items.length?done/items.length*100:100)+'%';progress.append(bar);header.append(title,progress,el('p','w-hint',data?.status==='failed'?'自动校对未完成，请人工检查关键事实。':(data?.status==='done'||items.length)?'定位正文，确认写法或替换名称。完成全部确认后即可导出。':'此纪要尚无校对结果，可重新生成后自动校对。'));review.append(header);
    const add=el('form','w-manual-term'),termInput=el('input','w-input');termInput.placeholder='输入漏检术语，如 AFC';termInput.setAttribute('aria-label','添加待确认术语');termInput.maxLength=120;termInput.disabled=!state.activeMinutes;const addButton=button('添加',null,'w-btn subtle small');addButton.type='submit';addButton.disabled=!state.activeMinutes;add.append(termInput,addButton);add.onsubmit=e=>{e.preventDefault();addManualTerm(termInput.value);};review.append(add);
    if (!todo.some(item => item.term === selectedTerm)) selectedTerm = todo[0]?.term || '';
    for(const [index,item] of todo.entries()){
      if (item.term !== selectedTerm) {
        const picker = button('', () => { selectedTerm = item.term; renderProofreading(state.proofreading); }, 'term-pick');
        picker.append(el('strong', '', item.term), el('small', '', textMatches(item.term).length + ' 处 ›'));
        review.append(picker);
        continue;
      }
      const card=el('section','w-review-card'+(item.term===selectedTerm?' selected':'')),title=el('div','w-term-title'),matches=textMatches(item.term);title.append(el('span','w-term-index',index+1),el('strong','',item.term),el('small','',matches.length+' 处'));card.append(title,el('p','w-hint',item.reason||'请确认准确名称'));if(matches.length){const[node,at]=matches[0];card.append(el('blockquote','w-context','“'+node.data.slice(Math.max(0,at-25),at+item.term.length+45)+'”'));}card.append(button('⌖ 定位正文'+(locationIndex[item.term]?' · 第 '+locationIndex[item.term]+' 处':''),()=>locateTerm(item),'w-locate'));
      const input=el('input','w-input');input.placeholder='输入准确名称';input.setAttribute('aria-label',item.term+'的准确名称');input.value=item.replacement_draft||prefs.terms.find(t=>t.from===item.term)?.to||'';input.oninput=()=>{item.replacement_draft=input.value;};const actions=el('div','w-review-actions');actions.append(button('✓ 确认无误',()=>{item.decision='confirmed';markDirty();renderProofreading(state.proofreading);},'w-btn small'),button('全文替换',()=>requestReplacement(item,input.value.trim()),'w-btn subtle small'));card.append(input,actions);review.append(card);
    }
    if(!todo.length&&data?.status==='done'){const ready=el('div','w-complete');ready.append(el('span','','✓'),el('strong','','校对任务已完成'),el('p','','这份纪要可以导出了。'));review.append(ready);}
    if(done){const details=el('details','w-resolved');details.open=true;details.append(el('summary','','已完成 '+done+' 项'));for(const item of items.filter(x=>['confirmed','replaced'].includes(x.decision))){const row=el('div','w-resolved-row'),copy=el('div');copy.append(el('strong','',item.replacement||item.term),el('small','',item.decision==='confirmed'?'已确认无误':'已替换'));row.append(el('span','','✓'),copy,button(undo.has(item.term)?'撤回替换':'重新确认',()=>undoDecision(item),'w-link'));details.append(row);}review.append(details);}paintReviewTerms();updateReviewState();
  };
  async function rememberCorrection(original, name) {
    const existing = prefs.terms.find(term => term.from === original);
    if (existing?.to === name) return;
    const terms = prefs.terms.filter(term => term.from !== original);
    const matching = terms.filter(term => term.to === name);
    if (matching.length === 1) {
      const entry = matching[0];
      const aliases = [...new Set([...(entry.aliases || []), original])];
      await savePrefs({terms: terms.map(term => term === entry ? {...entry, aliases} : term)});
    } else {
      await savePrefs({terms: [...terms, {from: original, to: name}]});
    }
  }
  function requestReplacement(item,value){if(!value||value===item.term)return toast('请输入不同的准确名称，或确认无误');const count=textMatches(item.term).length;if(!count)return toast('正文已没有该词');showModal('替换 '+count+' 处词语');body.append(el('p','','仅修改当前会议纪要，原始转写保留不变。'),el('div','w-context',item.term+' → '+value));const label=el('label','w-check'),check=el('input');check.type='checkbox';check.checked=true;label.append(check,document.createTextNode('记入我的术语库，下次作为名称参考'));body.append(label);foot.append(button('取消',()=>modal.close()),button('确认替换',async()=>{const nodes=[...new Set(textMatches(item.term).map(x=>x[0]))],patch=nodes.map(node=>({node,before:node.data,after:node.data.split(item.term).join(value)}));for(const p of patch)p.node.data=p.after;undo.set(item.term,patch);item.decision='replaced';item.replacement=value;markDirty();renderProofreading(state.proofreading);modal.close();if(check.checked){try{await rememberCorrection(item.term,value);renderRecent();}catch(e){toast('替换已完成，但术语库未保存：'+e.message);}}},'w-btn primary'));}
  function undoDecision(item){const patch=undo.get(item.term);if(patch){if(patch.some(p=>!$('minutesBody').contains(p.node)||p.node.data!==p.after))return toast('替换后的段落已继续编辑，请先手动恢复该词');patch.forEach(p=>p.node.data=p.before);undo.delete(item.term);delete item.replacement;}item.decision='pending';markDirty();renderProofreading(state.proofreading);}
  // A single save queue serializes manual saves, autosaves, navigation and mapping.
  function saveSnapshot(){const path=state.activeMinutes;if(!path||!state.apiReady)return Promise.resolve(false);const title=titleInput.value.trim();if(!title)return Promise.resolve(false);const heading=$('minutesBody').firstElementChild;if(title!==savedTitle){if(heading?.tagName==='H1')heading.textContent=title;else $('minutesBody').prepend(el('h1','',title));updateWordCount();}const content=editorToMarkdown($('minutesBody')),rev=revision,decisions=Object.fromEntries(reviewItems().map(x=>[x.term,{decision:x.decision||'pending',replacement:x.replacement||'',source:x.source||''}]));const job=async()=>{try{await call('save_minutes',path,content,decisions,title);const session=state.sessions.find(x=>x.minutes===path);if(session)session.title=title;if(path===state.activeMinutes&&rev===revision){savedTitle=title;markSaved();}renderRecent();renderSessionList();return true;}catch(e){toast('保存失败：'+e.message);return false;}};queue=queue.then(job,job);return queue;}
  saveMinutes=async function(){clearTimeout(saveTimer);return saveSnapshot();};
  const dirty=markDirty;markDirty=function(){dirty();revision++;clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveSnapshot(),1200);};
  const openBase=openMinutes;openMinutes=async function(path){if(state.dirty&&!await saveMinutes())return;stopAudio();if (!await openBase(path) || state.activeMinutes !== path) return false;savedTitle=titleInput.value;undo.clear();selectedTerm='';locationIndex=Object.create(null);renderProofreading(state.proofreading);gen.hidden=true;switchTab('review');loadContext();try{await savePrefs({last_minutes:path});}catch(e){toast(e.message);}renderRecent();return state.activeMinutes===path;};
  const clearBase=clearEditor;clearEditor=function(){stopAudio();loadToken++;clearBase();segments=speakers=null;renderProofreading({uncertain:[]});peoplePane.textContent=sourcePane.textContent='选择会议后显示';};
  document.querySelector('.editor-footer>span').textContent='更改自动保存到本机';

  const editor = $('minutesBody');
  let highlightTimer;
  editor.addEventListener('input', () => {
    clearTimeout(highlightTimer);
    highlightTimer = setTimeout(paintReviewTerms, 180);
  });
  function currentEditorRange() {
    const selection = getSelection();
    if (!selection.rangeCount) return null;
    const range = selection.getRangeAt(0);
    return editor.contains(range.commonAncestorContainer) ? range.cloneRange() : null;
  }
  const pasteTags = new Set('P H1 H2 H3 H4 H5 H6 BR STRONG B EM I CODE BLOCKQUOTE UL OL LI TABLE THEAD TBODY TR TD TH A'.split(' '));
  function cleanPasteHtml(source) {
    const template = document.createElement('template');
    template.innerHTML = source;
    const output = document.createElement('div');
    function append(node, parent) {
      if (node.nodeType === Node.TEXT_NODE) {
        parent.append(node.textContent);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE || node.namespaceURI !== 'http://www.w3.org/1999/xhtml' ||
          node.matches('script,style,head,title,link,meta,base,template,iframe,object,embed,noscript,button,input,textarea,select,[hidden]')) return;

      let tag = node.tagName;
      // Google Docs can wrap the entire copied selection in a normal-weight B element.
      if (['B', 'STRONG'].includes(tag) && ['normal', '400'].includes(node.style.fontWeight)) tag = 'SPAN';
      // Keep paragraph boundaries while unwrapping layout containers copied from websites.
      if (tag === 'DIV' && !node.querySelector('p,div,h1,h2,h3,h4,h5,h6,table,ul,ol,blockquote')) tag = 'P';
      const href = node.getAttribute('href')?.trim();
      if (tag === 'A' && !/^(https?:\/\/|mailto:)/i.test(href || '')) tag = '';
      let target = parent;
      if (pasteTags.has(tag)) {
        target = document.createElement(tag.toLowerCase());
        if (tag === 'A') target.setAttribute('href', href);
        parent.append(target);
      }
      if (['SPAN', 'FONT', 'P', 'B', 'I', 'EM', 'STRONG', 'A'].includes(tag)) {
        const weight = node.style.fontWeight;
        if (tag !== 'B' && tag !== 'STRONG' && (weight === 'bold' || Number(weight) >= 600)) {
          const bold = document.createElement('strong');
          target.append(bold);
          target = bold;
        }
        if (tag !== 'I' && tag !== 'EM' && node.style.fontStyle === 'italic') {
          const italic = document.createElement('em');
          target.append(italic);
          target = italic;
        }
      }
      for (const child of node.childNodes) append(child, target);
    }
    for (const node of template.content.childNodes) append(node, output);
    return output.textContent.trim() ? output.innerHTML : '';
  }
  function insertClipboard({text, html}, range) {
    if (!editor.isContentEditable) return;
    const rich = html && cleanPasteHtml(html);
    if (!rich && !text) return toast('剪贴板中没有可粘贴的文字');
    if (!range) {
      range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
    }
    if (!editor.contains(range.commonAncestorContainer)) return;
    restoreSelection(range);
    // Native editing commands preserve the selection, undo history and autosave input event.
    if (!document.execCommand(rich ? 'insertHTML' : 'insertText', false, rich || text.replace(/\r\n?/g, '\n'))) {
      toast('未能插入文字，请在正文中选定位置后再试。');
    }
  }
  editor.addEventListener('paste', event => {
    if (!editor.isContentEditable) return;
    event.preventDefault();
    const data = event.clipboardData;
    insertClipboard({text: data?.getData('text/plain'), html: data?.getData('text/html')}, currentEditorRange());
  });
  const menu = $('editorContextMenu');
  const menuButtons = [...menu.querySelectorAll('button')];
  let menuRange = null;
  function restoreSelection(range) {
    editor.focus({preventScroll: true});
    getSelection().removeAllRanges();
    getSelection().addRange(range);
  }
  function closeEditMenu(restore = false) {
    if (menu.hidden) return;
    menu.hidden = true;
    if (restore && menuRange && editor.contains(menuRange.commonAncestorContainer)) restoreSelection(menuRange);
    menuRange = null;
  }
  function pointRange(x, y) {
    if (document.caretPositionFromPoint) {
      const point = document.caretPositionFromPoint(x, y);
      if (!point) return null;
      const range = document.createRange();
      range.setStart(point.offsetNode, point.offset);
      range.collapse(true);
      return range;
    }
    return document.caretRangeFromPoint?.(x, y);
  }
  function openEditMenu(range, x, y) {
    if (!state.activeMinutes || !editor.isContentEditable || !range || !editor.contains(range.commonAncestorContainer)) return;
    menuRange = range.cloneRange();
    restoreSelection(menuRange);
    menuButtons[0].disabled = menuButtons[1].disabled = range.collapsed;
    menu.hidden = false;
    menu.style.left = Math.max(4, Math.min(x, innerWidth - menu.offsetWidth - 4)) + 'px';
    menu.style.top = Math.max(4, Math.min(y, innerHeight - menu.offsetHeight - 4)) + 'px';
    menu.querySelector('[data-edit="paste"]').focus({preventScroll: true});
  }

  // Record the selection before the system's secondary click can select a word of its own.
  let pointerRange = null;
  editor.addEventListener('mousedown', event => {
    if (event.button !== 2 && !(event.button === 0 && event.ctrlKey)) return;
    const {clientX: x, clientY: y} = event;
    const range = currentEditorRange();
    const inSelection = range && !range.collapsed && [...range.getClientRects()].some(
      rect => x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom);
    pointerRange = inSelection ? range : pointRange(x, y);
  });
  editor.addEventListener('contextmenu', event => {
    if (!editor.isContentEditable) return;
    event.preventDefault();
    openEditMenu(pointerRange || currentEditorRange() || pointRange(event.clientX, event.clientY), event.clientX, event.clientY);
    pointerRange = null;
  });
  editor.addEventListener('keydown', event => {
    if (!(event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10'))) return;
    const range = currentEditorRange();
    if (!range) return;
    event.preventDefault();
    const rect = range.getBoundingClientRect();
    openEditMenu(range, rect.left, rect.bottom);
  });

  menu.addEventListener('mousedown', event => event.preventDefault());
  menu.addEventListener('click', async event => {
    const command = event.target.closest('button')?.dataset.edit;
    const range = menuRange;
    if (!command || !range) return;
    closeEditMenu(true);
    if (command === 'selectAll') {
      range.selectNodeContents(editor);
      restoreSelection(range);
      return;
    }
    if (command !== 'paste' && command !== 'pastePlain') {
      if (!document.execCommand(command)) toast(command === 'copy' ? '请使用系统复制快捷键' : '请使用系统剪切快捷键');
      return;
    }
    const path = state.activeMinutes, request = state.minutesRequest, editRevision = revision;
    try {
      const formatted = command === 'paste';
      let payload;
      if (state.apiReady) {
        const result = await api().read_editor_clipboard(formatted);
        if (result.ok) payload = result;
      }
      if (!payload && formatted && navigator.clipboard?.read) {
        const items = await navigator.clipboard.read();
        const item = items.find(x => x.types.includes('text/html') || x.types.includes('text/plain'));
        const readType = async type => item?.types.includes(type) ? (await item.getType(type)).text() : '';
        payload = {text: await readType('text/plain'), html: await readType('text/html')};
      }
      if (!payload) payload = {text: await navigator.clipboard.readText()};
      if (state.activeView !== 'minutes' || path !== state.activeMinutes || request !== state.minutesRequest ||
          editRevision !== revision || !editor.contains(range.commonAncestorContainer)) return;
      insertClipboard(payload, range);
    } catch {
      toast('无法读取剪贴板，请在正文按 Ctrl+V 或 ⌘V');
    }
  });
  menu.addEventListener('keydown', event => {
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.preventDefault();
      event.stopPropagation();
      closeEditMenu(true);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const choices = menuButtons.filter(b => !b.disabled);
      const next = choices.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : -1);
      choices[(next + choices.length) % choices.length].focus();
    }
  });
  document.addEventListener('pointerdown', event => { if (!menu.contains(event.target)) closeEditMenu(); }, true);
  document.addEventListener('scroll', () => closeEditMenu(), true);
  window.addEventListener('resize', () => closeEditMenu());
  window.addEventListener('blur', () => closeEditMenu());

  const guideTopics = [...$('guideTopics').querySelectorAll('button')];
  const guideQuery = $('guideQuery');
  function showGuideTopic(active) {
    for (const link of guideTopics) {
      const article = $(link.getAttribute('aria-controls'));
      article.hidden = link !== active;
      if (link === active) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
    $('guideNoResults').hidden = Boolean(active);
    document.querySelector('.guide-reading').scrollTop = 0;
  }
  for (const link of guideTopics) link.onclick = () => showGuideTopic(link);
  for (const choice of document.querySelectorAll('[data-guide-target]')) {
    choice.onclick = () => {
      guideQuery.value = '';
      for (const link of guideTopics) link.hidden = false;
      const id = choice.dataset.guideTarget;
      showGuideTopic(guideTopics.find(link => link.getAttribute('aria-controls') === id));
      $(id).focus({preventScroll: true});
    };
  }
  guideQuery.oninput = () => {
    const query = guideQuery.value.trim().toLowerCase();
    const current = guideTopics.find(link => link.hasAttribute('aria-current'));
    for (const link of guideTopics) {
      link.hidden = !$(link.getAttribute('aria-controls')).textContent.toLowerCase().includes(query);
    }
    showGuideTopic(current && !current.hidden ? current : guideTopics.find(link => !link.hidden));
  };
  function showPreferences(){showModal('偏好设置');const row=el('div','w-setting-row'),copy=el('div');copy.append(el('strong','','正文阅读字号'),el('small','','只影响屏幕显示，不影响导出'));const select=el('select');for(const [value,label] of [[14,'紧凑 · 14'],[15,'标准 · 15'],[17,'舒适 · 17']]){const o=el('option','',label);o.value=value;select.append(o);}select.value=prefs.font_size;select.onchange=async()=>{try{await savePrefs({font_size:Number(select.value)});}catch(e){toast(e.message);select.value=prefs.font_size;}};row.append(copy,select);body.append(row);const motion=el('div','w-setting-row'),mc=el('div');mc.append(el('strong','','减少动态效果'),el('small','','关闭过渡动画'));const toggle=button('',async()=>{try{await savePrefs({reduce_motion:!prefs.reduce_motion});toggle.classList.toggle('on',prefs.reduce_motion);toggle.setAttribute('aria-checked',String(prefs.reduce_motion));}catch(e){toast(e.message);}},'w-toggle'+(prefs.reduce_motion?' on':''));toggle.setAttribute('role','switch');toggle.setAttribute('aria-label','减少动态效果');toggle.setAttribute('aria-checked',String(prefs.reduce_motion));motion.append(mc,toggle);body.append(motion);const terms=el('div','w-setting-row'),tc=el('div');tc.append(el('strong','','个人术语库'),el('small','',prefs.terms.length+' 个已记住的名称'));terms.append(tc,button('管理',showDictionary));body.append(terms);const conn=el('div','w-setting-row');conn.append(el('strong','','模型、设备与输出目录'),button('设置',()=>{modal.close();openSettings();}));body.append(conn);foot.append(closeButton());}
  function showDictionary() {
    showModal('我的术语库');
    body.append(el('p', '', '纪要会参考与转写匹配的词条。可为容易混淆的名称补充含义和使用场景。'));
    const list = el('div', 'w-dictionary');
    for (const item of prefs.terms) {
      const row = el('div', 'w-term-row'), copy = el('div', 'dictionary-copy');
      copy.append(el('strong', '', item.to), el('small', '', [item.from, ...(item.aliases || [])].join(' · ')));
      if (item.meaning) copy.append(el('p', '', item.meaning));
      row.append(copy, button(item.meaning ? '编辑' : '补充含义', () => editDictionaryTerm(item), 'w-link'));
      row.append(button('删除', async () => {
        try {
          await savePrefs({terms: prefs.terms.filter(term => term.from !== item.from)});
          showDictionary();
          renderRecent();
        } catch (error) { toast(error.message); }
      }, 'w-link'));
      list.append(row);
    }
    if (!list.children.length) list.append(el('p', 'w-empty', '还没有保存的术语'));
    body.append(list);
    foot.append(button('添加术语', () => editDictionaryTerm(null)), closeButton());
  }

  function editDictionaryTerm(item) {
    showModal(item ? '编辑术语' : '添加术语');
    const form = el('form', 'dictionary-form');
    function field(label, value, multiline = false) {
      const wrap = el('label'), input = el(multiline ? 'textarea' : 'input', 'w-input');
      wrap.append(el('span', '', label), input);
      input.value = value || '';
      form.append(wrap);
      return input;
    }
    const to = field('准确名称', item?.to), from = field('原词或常见误写（选填）', item?.from);
    from.maxLength = to.maxLength = 100;
    to.required = true;
    const aliases = field('其他别名（选填，每行一个）', item?.aliases?.join('\n'), true);
    const meaning = field('含义与使用场景（选填）', item?.meaning, true);
    meaning.maxLength = 500;
    meaning.placeholder = '这个名称在会议中指什么？哪些情况下使用？';
    body.append(form);
    const save = button('保存', () => form.requestSubmit(), 'w-btn primary');
    form.onsubmit = async event => {
      event.preventDefault();
      const name = to.value.trim();
      if (!name) return toast('请输入准确名称');
      const original = from.value.trim() || name;
      if (prefs.terms.some(term => term.from === original && term.from !== item?.from)) {
        return toast('这个原词已有词条，请在列表中编辑');
      }
      const entry = {from: original, to: name, meaning: meaning.value.trim(), aliases: aliases.value.split('\n')};
      const terms = item ? prefs.terms.map(term => term.from === item.from ? entry : term) : [...prefs.terms, entry];
      save.disabled = true;
      try {
        await savePrefs({terms});
        showDictionary();
        renderRecent();
      } catch (error) { toast(error.message); }
      finally { save.disabled = false; }
    };
    foot.append(button('取消', showDictionary), save);
    (item ? meaning : to).focus();
  }
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
