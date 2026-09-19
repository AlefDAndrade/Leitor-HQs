(function(){
  "use strict";
  if (window['pdfjsLib']) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  }

  // ---------------- State ----------------
  let pages = [];            // {id,name,url,frames:[{id,x,y,w,h}]}
  let pageIdSeq = 1, frameIdSeq = 1;
  let currentPageIndex = -1;
  let addFrameMode = false;
  let selectedFrameId = null;

  let readerOpen = false;
  let readerPageIndex = 0;
  let readerFrameIndex = -1;

  // ---------------- Elements ----------------
  const el = (id) => document.getElementById(id);
  const thumbsEl = el('thumbs');
  const stageEl = el('stage');
  const toolbarEl = el('toolbar');
  const panelFramesEl = el('panel-frames');
  const frameListEl = el('frame-list');
  const statusEl = el('status');
  const pageCounterEl = el('page-counter');
  const addFrameBtn = el('add-frame-btn');
  const readBtn = el('read-btn');
  const autoDetectBtn = el('auto-detect-btn');
  const autoDetectScopeEl = el('auto-detect-scope');
  const autoDetectRangeInputEl = el('auto-detect-range-input');
  autoDetectScopeEl.addEventListener('change', () => {
    autoDetectRangeInputEl.style.display = (autoDetectScopeEl.value === 'range') ? '' : 'none';
  });

  // Interpreta algo como "11-25", "11,13,16,19" ou uma combinação
  // ("11-13,16,19-22"). Devolve índices de página 0-based (já validados
  // dentro do total de páginas do arquivo), em ordem crescente e sem
  // repetição, mais uma lista de erros (se algum trecho não fez sentido).
  function parsePageRangeSpec(spec, totalPages){
    const result = new Set();
    const errors = [];
    const parts = (spec || '').split(',').map(s => s.trim()).filter(Boolean);
    if(parts.length === 0){
      errors.push('Digite ao menos uma página ou intervalo (ex: 11-25).');
      return { pages: [], errors };
    }
    for(const part of parts){
      const rangeMatch = part.match(/^(\d+)\s*-\s*(\d+)$/);
      if(rangeMatch){
        let a = parseInt(rangeMatch[1], 10), b = parseInt(rangeMatch[2], 10);
        if(a > b){ const t = a; a = b; b = t; }
        for(let n = a; n <= b; n++) result.add(n);
      } else if(/^\d+$/.test(part)){
        result.add(parseInt(part, 10));
      } else {
        errors.push('"' + part + '" não é uma página ou intervalo válido.');
      }
    }
    const nums = [...result];
    const outOfRange = nums.filter(n => n < 1 || n > totalPages);
    if(outOfRange.length){
      errors.push('Página(s) fora do arquivo (tem ' + totalPages + ' no total): ' + outOfRange.join(', ') + '.');
    }
    const valid = nums.filter(n => n >= 1 && n <= totalPages).sort((a,b) => a-b);
    return { pages: valid.map(n => n-1), errors };
  }
  const autoDetectRtlEl = el('auto-detect-rtl');
  const autoDetectKumikoReviewEl = el('auto-detect-kumiko-review');
  let autoDetectRunning = false;

  function setStatus(msg){ statusEl.textContent = msg || ''; }
  function clamp(v,min,max){ return Math.max(min, Math.min(max, v)); }
  function naturalSort(a,b){ return a.localeCompare(b, undefined, {numeric:true, sensitivity:'base'}); }
  function currentPage(){ return currentPageIndex>=0 ? pages[currentPageIndex] : null; }

  // ---------------- Import: images / cbz / pdf ----------------
  el('import-btn').onclick = () => el('file-input').click();
  el('dropzone-btn').onclick = () => el('file-input').click();
  el('file-input').addEventListener('change', (e) => handleFiles(e.target.files));

  const dropzone = el('dropzone');
  ['dragenter','dragover'].forEach(evt => stageEl.addEventListener(evt, e => {
    e.preventDefault();
    if(currentPageIndex === -1) dropzone.classList.add('drag');
  }));
  ['dragleave','drop'].forEach(evt => stageEl.addEventListener(evt, e => {
    e.preventDefault();
    dropzone.classList.remove('drag');
  }));
  stageEl.addEventListener('drop', e => {
    if(e.dataTransfer.files && e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
  });

  async function handleFiles(fileList){
    const files = Array.from(fileList);
    if(!files.length) return;
    const wasEmpty = pages.length === 0;
    const imageFiles = files.filter(f => f.type.startsWith('image/'));
    const cbzFiles = files.filter(f => /\.(cbz|zip)$/i.test(f.name));
    const pdfFiles = files.filter(f => /\.pdf$/i.test(f.name) || f.type === 'application/pdf');
    const cbrFiles = files.filter(f => /\.(cbr|rar)$/i.test(f.name));

    imageFiles.sort((a,b) => naturalSort(a.name,b.name));
    for(const f of imageFiles){
      addPage(f.name, URL.createObjectURL(f));
    }

    for(const f of cbzFiles){
      setStatus('Lendo ' + f.name + '…');
      try{
        const zip = await JSZip.loadAsync(f);
        const entries = Object.values(zip.files)
          .filter(e => !e.dir && /\.(jpe?g|png|gif|webp|bmp)$/i.test(e.name))
          .sort((a,b) => naturalSort(a.name,b.name));
        for(const entry of entries){
          const blob = await entry.async('blob');
          addPage(entry.name, URL.createObjectURL(blob));
        }
        setStatus(entries.length + ' páginas de ' + f.name);
      }catch(err){
        console.error(err);
        setStatus('Não consegui ler ' + f.name);
      }
    }

    for(const f of pdfFiles){
      if(!window.pdfjsLib){ setStatus('Leitor de PDF não carregou.'); continue; }
      setStatus('Lendo ' + f.name + '…');
      try{
        const buf = await f.arrayBuffer();
        const pdf = await pdfjsLib.getDocument({data: buf}).promise;
        for(let i=1; i<=pdf.numPages; i++){
          setStatus('Renderizando ' + f.name + ' — página ' + i + '/' + pdf.numPages);
          const page = await pdf.getPage(i);
          const viewport = page.getViewport({scale: 2});
          const canvas = document.createElement('canvas');
          canvas.width = viewport.width; canvas.height = viewport.height;
          await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
          addPage(f.name + ' p.' + i, canvas.toDataURL('image/png'));
        }
      }catch(err){
        console.error(err);
        setStatus('Não consegui ler ' + f.name);
      }
    }

    for(const f of cbrFiles){
      setStatus('Carregando suporte a CBR/RAR…');
      try{
        const Archive = await loadRarSupport();
        setStatus('Lendo ' + f.name + '…');
        const archive = await Archive.open(f);
        const encrypted = await archive.hasEncryptedData().catch(() => null);
        if(encrypted){ setStatus(f.name + ' está protegido por senha — não consigo abrir.'); continue; }
        const extracted = await archive.extractFiles();
        const flat = [];
        (function flatten(obj, prefix){
          for(const key in obj){
            const val = obj[key];
            if(val instanceof File) flat.push({path: prefix+key, file: val});
            else if(val && typeof val === 'object') flatten(val, prefix+key+'/');
          }
        })(extracted, '');
        const imgs = flat
          .filter(e => /\.(jpe?g|png|gif|webp|bmp)$/i.test(e.path))
          .sort((a,b) => naturalSort(a.path,b.path));
        for(const e of imgs){ addPage(e.path, URL.createObjectURL(e.file)); }
        setStatus(imgs.length + ' páginas de ' + f.name);
      }catch(err){
        console.error(err);
        setStatus('Não consegui ler ' + f.name + ' — tente converter para .cbz.');
      }
    }

    if(wasEmpty && pages.length){ currentPageIndex = 0; }
    setStatus(pages.length + ' página(s) carregada(s)');
    el('save-frames-btn').disabled = false;
    el('load-frames-btn').disabled = false;
    el('clear-btn').disabled = false;
    toolbarEl.style.display = 'flex';
    panelFramesEl.style.display = 'flex';
    renderAll();
  }

  let rarSupportPromise = null;
  function loadRarSupport(){
    if(!rarSupportPromise){
      // O módulo é carregado localmente (pasta ./libarchive) porque:
      // 1) a versão da CDN não expõe main.js (só existe dist/libarchive.js);
      // 2) navegadores proíbem criar um Worker cujo script fique em outra
      //    origem (ex.: uma CDN) — precisa ser da mesma origem da página.
      // Por isso os arquivos libarchive.js, worker-bundle.js e libarchive.wasm
      // ficam junto do app, e o worker é apontado para o arquivo local.
      rarSupportPromise = import('./libarchive/libarchive.js').then(mod => {
        mod.Archive.init({ workerUrl: 'libarchive/worker-bundle.js' });
        return mod.Archive;
      });
    }
    return rarSupportPromise;
  }

  function addPage(name, url){
    pages.push({ id: pageIdSeq++, name, url, frames: [] });
  }

  // ---------------- Clear all ----------------
  el('clear-btn').onclick = () => {
    if(!confirm('Limpar todos os quadrinhos e marcações carregados?')) return;
    pages = []; currentPageIndex = -1; selectedFrameId = null; addFrameMode = false;
    toolbarEl.style.display = 'none';
    panelFramesEl.style.display = 'none';
    el('save-frames-btn').disabled = true;
    el('load-frames-btn').disabled = true;
    el('clear-btn').disabled = true;
    setStatus('');
    renderAll();
  };

  // ---------------- Save / load frame data ----------------
  el('save-frames-btn').onclick = () => {
    const data = {
      version: 1,
      pages: pages.map(p => ({ name: p.name, frames: p.frames.map(f => ({x:f.x,y:f.y,w:f.w,h:f.h})) }))
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], {type:'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'marcacoes-de-quadros.json';
    a.click();
  };
  el('load-frames-btn').onclick = () => el('frames-json-input').click();
  el('frames-json-input').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if(!file) return;
    try{
      const text = await file.text();
      const data = JSON.parse(text);
      (data.pages||[]).forEach((saved, i) => {
        if(pages[i]){
          pages[i].frames = (saved.frames||[]).map(f => ({id: frameIdSeq++, x:f.x, y:f.y, w:f.w, h:f.h}));
        }
      });
      setStatus('Marcações carregadas (por ordem das páginas — confira se bate com os arquivos atuais).');
      renderAll();
    }catch(err){
      alert('Não consegui ler esse arquivo de marcações.');
    }
    e.target.value = '';
  });

  // ---------------- Render ----------------
  function renderAll(){
    renderThumbs();
    renderStage();
    renderFrameList();
    renderToolbar();
  }

  function renderThumbs(){
    thumbsEl.innerHTML = '';
    pages.forEach((p, i) => {
      const d = document.createElement('div');
      d.className = 'thumb' + (i === currentPageIndex ? ' active' : '');
      d.innerHTML = '<img src="'+p.url+'" loading="lazy">' +
        '<span class="n">'+(i+1)+'</span>' +
        '<span class="badge'+(p.frames.length?' has':'')+'">'+p.frames.length+'</span>';
      d.onclick = () => { currentPageIndex = i; selectedFrameId = null; renderAll(); };
      thumbsEl.appendChild(d);
    });
  }

  function renderStage(){
    if(currentPageIndex === -1){
      stageEl.innerHTML = '';
      const empty = el('empty-state') || buildEmptyState();
      stageEl.appendChild(empty);
      return;
    }
    const page = currentPage();
    stageEl.innerHTML =
      '<div class="mat"><div id="page-wrap">' +
      '<img id="page-img" src="'+page.url+'" draggable="false">' +
      '<div id="frame-layer" class="'+(addFrameMode?'add-mode':'')+'"></div>' +
      '</div></div>';

    const layer = el('frame-layer');
    page.frames.forEach((f, idx) => {
      const fEl = document.createElement('div');
      fEl.className = 'frame' + (f.id === selectedFrameId ? ' selected' : '');
      fEl.style.left = (f.x*100)+'%';
      fEl.style.top = (f.y*100)+'%';
      fEl.style.width = (f.w*100)+'%';
      fEl.style.height = (f.h*100)+'%';
      fEl.innerHTML =
        '<div class="fill"></div>' +
        '<span class="num">'+(idx+1)+'</span>' +
        '<i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>';
      if(f.id === selectedFrameId){
        ['nw','n','ne','e','se','s','sw','w'].forEach(h => {
          const hEl = document.createElement('div');
          hEl.className = 'handle ' + h;
          hEl.addEventListener('pointerdown', (e) => startResize(e, f, h));
          fEl.appendChild(hEl);
        });
      }
      fEl.addEventListener('pointerdown', (e) => {
        if(e.target.classList.contains('handle')) return;
        e.preventDefault();
        e.stopPropagation();
        selectedFrameId = f.id;
        startMove(e, f);
        renderAll();
      });
      layer.appendChild(fEl);
    });

    layer.addEventListener('pointerdown', (e) => {
      if(e.target !== layer) return;
      selectedFrameId = null;
      if(addFrameMode){ e.preventDefault(); startCreate(e, layer); }
      else renderAll();
    });
  }

  function buildEmptyState(){
    const d = document.createElement('div');
    d.id = 'empty-state';
    d.innerHTML =
      '<div id="dropzone"><h2>Nenhum quadrinho carregado</h2>' +
      '<p>Importe imagens soltas, um arquivo .cbz/.zip, .cbr/.rar ou um PDF do seu computador. Nada sai da sua máquina — a leitura e marcação rodam no navegador; a detecção automática de quadros (opcional) usa um servidor local do Kumiko, se você optar por ligá-lo.</p>' +
      '<button class="topbtn primary" id="dropzone-btn">Escolher arquivos</button></div>';
    d.querySelector('#dropzone-btn').onclick = () => el('file-input').click();
    return d;
  }

  function renderFrameList(){
    frameListEl.innerHTML = '';
    const page = currentPage();
    if(!page || !page.frames.length){
      frameListEl.innerHTML = '<li class="empty" style="border:none;background:none;cursor:default;">Nenhum quadro marcado ainda. Ative "Marcar quadros" e desenhe sobre a página.</li>';
      return;
    }
    page.frames.forEach((f, idx) => {
      const li = document.createElement('li');
      li.className = f.id === selectedFrameId ? 'selected' : '';
      li.dataset.idx = idx;
      li.innerHTML = '<span class="idx">'+(idx+1)+'</span><span class="lbl">Quadro '+(idx+1)+'</span>' +
        '<button class="move-btn up" title="Mover para cima" '+(idx===0?'disabled':'')+'>▲</button>' +
        '<button class="move-btn down" title="Mover para baixo" '+(idx===page.frames.length-1?'disabled':'')+'>▼</button>' +
        '<button class="del" title="Apagar quadro">×</button>';
      li.querySelector('.del').onclick = (e) => {
        e.stopPropagation();
        page.frames = page.frames.filter(fr => fr.id !== f.id);
        if(selectedFrameId === f.id) selectedFrameId = null;
        renderAll();
      };
      li.querySelector('.up').onclick = (e) => {
        e.stopPropagation();
        if(idx === 0) return;
        [page.frames[idx-1], page.frames[idx]] = [page.frames[idx], page.frames[idx-1]];
        renderAll();
      };
      li.querySelector('.down').onclick = (e) => {
        e.stopPropagation();
        if(idx === page.frames.length-1) return;
        [page.frames[idx+1], page.frames[idx]] = [page.frames[idx], page.frames[idx+1]];
        renderAll();
      };
      li.onclick = () => { selectedFrameId = f.id; renderAll(); };
      // arrastar com o mouse continua funcionando (desktop); em telas de toque,
      // os botões ▲▼ acima cobrem a reordenação, já que drag-and-drop nativo
      // do HTML5 não funciona em touch.
      li.draggable = true;
      li.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/plain', idx); });
      li.addEventListener('dragover', (e) => e.preventDefault());
      li.addEventListener('drop', (e) => {
        e.preventDefault();
        const from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        const to = idx;
        if(from === to) return;
        const [moved] = page.frames.splice(from, 1);
        page.frames.splice(to, 0, moved);
        renderAll();
      });
      frameListEl.appendChild(li);
    });
  }

  function renderToolbar(){
    pageCounterEl.textContent = pages.length ? (currentPageIndex+1)+' / '+pages.length : '0 / 0';
    el('prev-page').disabled = currentPageIndex <= 0;
    el('next-page').disabled = currentPageIndex >= pages.length-1;
    addFrameBtn.classList.toggle('active', addFrameMode);
    addFrameBtn.innerHTML = '<span class="sw"></span>' + (addFrameMode ? 'Marcando quadros…' : 'Marcar quadros');
    readBtn.disabled = pages.length === 0;
    autoDetectBtn.disabled = pages.length === 0 || autoDetectRunning;
    autoDetectScopeEl.disabled = autoDetectRunning;
    autoDetectRtlEl.disabled = autoDetectRunning;
    autoDetectRangeInputEl.disabled = autoDetectRunning;
    autoDetectKumikoReviewEl.disabled = autoDetectRunning;
    autoDetectBtn.textContent = autoDetectRunning ? 'Detectando…' : '✨ Auto-detectar';
  }

  el('prev-page').onclick = () => { if(currentPageIndex>0){ currentPageIndex--; selectedFrameId=null; renderAll(); } };
  el('next-page').onclick = () => { if(currentPageIndex<pages.length-1){ currentPageIndex++; selectedFrameId=null; renderAll(); } };
  addFrameBtn.onclick = () => { addFrameMode = !addFrameMode; selectedFrameId=null; renderAll(); };
  readBtn.onclick = () => openReader(currentPageIndex);

  // ---------------- Frame creation / move / resize ----------------
  function fracFromEvent(e, layer){
    const r = layer.getBoundingClientRect();
    return { x: clamp((e.clientX-r.left)/r.width,0,1), y: clamp((e.clientY-r.top)/r.height,0,1) };
  }

  function startCreate(e, layer){
    const start = fracFromEvent(e, layer);
    const preview = document.createElement('div');
    preview.className = 'frame-preview';
    layer.appendChild(preview);

    function onMove(ev){
      const cur = fracFromEvent(ev, layer);
      const x = Math.min(start.x, cur.x), y = Math.min(start.y, cur.y);
      const w = Math.abs(cur.x-start.x), h = Math.abs(cur.y-start.y);
      preview.style.left = (x*100)+'%'; preview.style.top = (y*100)+'%';
      preview.style.width = (w*100)+'%'; preview.style.height = (h*100)+'%';
      preview.dataset.x=x; preview.dataset.y=y; preview.dataset.w=w; preview.dataset.h=h;
    }
    function onUp(){
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      const x = parseFloat(preview.dataset.x||0), y = parseFloat(preview.dataset.y||0);
      const w = parseFloat(preview.dataset.w||0), h = parseFloat(preview.dataset.h||0);
      preview.remove();
      if(w > 0.015 && h > 0.015){
        const f = {id: frameIdSeq++, x, y, w, h};
        currentPage().frames.push(f);
        selectedFrameId = f.id;
      }
      renderAll();
    }
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  function startMove(e, f){
    const layer = el('frame-layer');
    const start = fracFromEvent(e, layer);
    const orig = {x:f.x, y:f.y, w:f.w, h:f.h};
    function onMove(ev){
      const cur = fracFromEvent(ev, layer);
      const dx = cur.x-start.x, dy = cur.y-start.y;
      f.x = clamp(orig.x+dx, 0, 1-orig.w);
      f.y = clamp(orig.y+dy, 0, 1-orig.h);
      renderFrameGeometryOnly();
    }
    function onUp(){
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      renderAll();
    }
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  function startResize(e, f, handle){
    e.stopPropagation();
    e.preventDefault();
    const layer = el('frame-layer');
    const start = fracFromEvent(e, layer);
    const orig = {x:f.x, y:f.y, w:f.w, h:f.h};
    function onMove(ev){
      const cur = fracFromEvent(ev, layer);
      const dx = cur.x-start.x, dy = cur.y-start.y;
      let x=orig.x, y=orig.y, x2=orig.x+orig.w, y2=orig.y+orig.h;
      if(handle.includes('n')) y = clamp(orig.y+dy, 0, y2-0.02);
      if(handle.includes('s')) y2 = clamp(orig.y+orig.h+dy, y+0.02, 1);
      if(handle.includes('w')) x = clamp(orig.x+dx, 0, x2-0.02);
      if(handle.includes('e')) x2 = clamp(orig.x+orig.w+dx, x+0.02, 1);
      f.x=x; f.y=y; f.w=x2-x; f.h=y2-y;
      renderFrameGeometryOnly();
    }
    function onUp(){
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      renderAll();
    }
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  // cheap geometry-only update during drag (avoids full re-render jank)
  function renderFrameGeometryOnly(){
    const layer = el('frame-layer');
    if(!layer) return;
    const page = currentPage();
    const nodes = layer.querySelectorAll('.frame');
    nodes.forEach((node, i) => {
      const f = page.frames[i];
      if(!f) return;
      node.style.left = (f.x*100)+'%';
      node.style.top = (f.y*100)+'%';
      node.style.width = (f.w*100)+'%';
      node.style.height = (f.h*100)+'%';
    });
  }

  // ---------------- Reader mode ----------------
  const readerEl = el('reader');
  const readerImg = el('reader-img');
  const readerSpotlight = el('reader-spotlight');
  const readerCaption = el('reader-caption');
  const readerHint = el('reader-hint');

  function openReader(pageIdx){
    if(!pages.length) return;
    readerOpen = true;
    readerPageIndex = pageIdx;
    readerFrameIndex = pages[pageIdx].frames.length ? 0 : -1;
    readerEl.classList.add('open');
    document.body.style.overflow = 'hidden';
    readerHint.style.opacity = '1';
    setTimeout(() => { readerHint.style.opacity = '0'; }, 2600);
    loadReaderImage(true);
    window.addEventListener('resize', onReaderResize);
  }
  function closeReader(){
    readerOpen = false;
    readerEl.classList.remove('open');
    document.body.style.overflow = '';
    window.removeEventListener('resize', onReaderResize);
  }
  function onReaderResize(){ applyReaderTransform(true); }

  function loadReaderImage(instant){
    const page = pages[readerPageIndex];
    readerImg.onload = () => applyReaderTransform(instant);
    readerImg.src = page.url;
    if(readerImg.complete) applyReaderTransform(instant);
  }

  function applyReaderTransform(instant){
    const page = pages[readerPageIndex];
    const iw = readerImg.naturalWidth || 1, ih = readerImg.naturalHeight || 1;
    const vw = window.innerWidth, vh = window.innerHeight;
    const containScale = Math.min(vw/iw, vh/ih);
    const baseW = iw*containScale, baseH = ih*containScale;
    readerImg.style.width = baseW+'px';
    readerImg.style.height = baseH+'px';
    const offsetX = (vw-baseW)/2, offsetY = (vh-baseH)/2;
    readerImg.style.left = offsetX+'px';
    readerImg.style.top = offsetY+'px';

    let fx=0, fy=0, fw=1, fh=1, pad=0.98;
    const frames = page.frames;
    if(readerFrameIndex >= 0 && frames[readerFrameIndex]){
      const f = frames[readerFrameIndex];
      fx=f.x; fy=f.y; fw=f.w; fh=f.h; pad=0.90;
    }
    const targetPxW = fw*baseW, targetPxH = fh*baseH;
    const scale = Math.min(vw/targetPxW, vh/targetPxH) * pad;
    const centerLocalX = (fx+fw/2)*baseW, centerLocalY = (fy+fh/2)*baseH;
    const tx = vw/2 - offsetX - scale*centerLocalX;
    const ty = vh/2 - offsetY - scale*centerLocalY;

    readerImg.style.transition = instant ? 'none' : 'transform 0.45s cubic-bezier(.22,.61,.36,1)';
    if(instant){
      readerImg.getBoundingClientRect();
      requestAnimationFrame(() => { readerImg.style.transition = 'transform 0.45s cubic-bezier(.22,.61,.36,1)'; });
    }
    readerImg.style.transform = 'translate('+tx+'px,'+ty+'px) scale('+scale+')';

    // Spotlight: darken everything outside the marked frame, leave the frame itself clear.
    // No spotlight when there's no marked frame (whole page is "in focus").
    const hasFrame = readerFrameIndex >= 0 && !!frames[readerFrameIndex];
    const spotTransition = 'left .45s cubic-bezier(.22,.61,.36,1), top .45s cubic-bezier(.22,.61,.36,1), width .45s cubic-bezier(.22,.61,.36,1), height .45s cubic-bezier(.22,.61,.36,1), opacity .3s';
    readerSpotlight.style.transition = instant ? 'none' : spotTransition;
    if(hasFrame){
      readerSpotlight.style.left = (offsetX + tx + fx*baseW*scale) + 'px';
      readerSpotlight.style.top = (offsetY + ty + fy*baseH*scale) + 'px';
      readerSpotlight.style.width = (fw*baseW*scale) + 'px';
      readerSpotlight.style.height = (fh*baseH*scale) + 'px';
      readerSpotlight.style.opacity = '1';
    } else {
      readerSpotlight.style.opacity = '0';
    }
    if(instant){
      readerSpotlight.getBoundingClientRect();
      requestAnimationFrame(() => { readerSpotlight.style.transition = spotTransition; });
    }

    updateCaption();
  }

  function updateCaption(){
    const page = pages[readerPageIndex];
    let txt = 'Página '+(readerPageIndex+1)+' de '+pages.length;
    if(page.frames.length){
      txt += readerFrameIndex === -1
        ? '  ·  Página completa'
        : '  ·  Quadro '+(readerFrameIndex+1)+' de '+page.frames.length;
    }
    readerCaption.textContent = txt;
  }

  function readerNext(){
    const frames = pages[readerPageIndex].frames;
    if(readerFrameIndex >= 0 && readerFrameIndex < frames.length-1){
      readerFrameIndex++;
      applyReaderTransform(false);
    } else if(readerFrameIndex >= 0 && readerFrameIndex === frames.length-1){
      // acabaram os quadros: mostra a página inteira antes de virar a página
      readerFrameIndex = -1;
      applyReaderTransform(false);
    } else if(readerPageIndex < pages.length-1){
      readerPageIndex++;
      readerFrameIndex = pages[readerPageIndex].frames.length ? 0 : -1;
      loadReaderImage(false);
    }
  }
  function readerPrev(){
    const frames = pages[readerPageIndex].frames;
    if(readerFrameIndex === -1 && frames.length > 0){
      // estava vendo a página inteira (pós-quadros): volta pro último quadro
      readerFrameIndex = frames.length-1;
      applyReaderTransform(false);
    } else if(readerFrameIndex > 0){
      readerFrameIndex--;
      applyReaderTransform(false);
    } else if(readerPageIndex > 0){
      readerPageIndex--;
      const f = pages[readerPageIndex].frames;
      readerFrameIndex = f.length ? f.length-1 : -1;
      loadReaderImage(false);
    }
  }

  el('reader-left').onclick = readerPrev;
  el('reader-right').onclick = readerNext;
  el('reader-close').onclick = closeReader;

  // ---------------- Blackout (leitura) ----------------
  const readerBlackoutBtn = el('reader-blackout-btn');
  let blackoutMode = false;
  function setBlackout(on){
    blackoutMode = on;
    readerEl.classList.toggle('blackout', blackoutMode);
    readerBlackoutBtn.classList.toggle('active', blackoutMode);
  }
  readerBlackoutBtn.onclick = () => setBlackout(!blackoutMode);

  // ---------------- Auto-detecção de quadros (Kumiko de verdade, via servidor local) ----------------
  // Agora o mesmo servidor (kumiko_server.py) serve o app E o Kumiko, então
  // a chamada é sempre pra própria origem da página — não precisa mais
  // apontar pra uma porta/host fixo.
  const KUMIKO_SERVER_URL = '';

  function loadPageBlob(url){
    return fetch(url).then(r => {
      if(!r.ok) throw new Error('Falha ao ler a imagem da página.');
      return r.blob();
    });
  }

  async function pingKumikoServer(){
    try{
      const r = await fetch(KUMIKO_SERVER_URL + '/ping', { method: 'GET' });
      return r.ok;
    }catch(e){
      return false;
    }
  }

  async function detectFramesViaServer(blob, opts){
    opts = opts || {};
    const params = new URLSearchParams({
      rtl: opts.rtl ? '1' : '0',
      min_panel_size_ratio: String(opts.minPanelSizeRatio != null ? opts.minPanelSizeRatio : 0.1),
    });
    if(opts.kumikoReview){
      params.set('kumiko_review', '1');
    }
    const res = await fetch(KUMIKO_SERVER_URL + '/detect?' + params.toString(), {
      method: 'POST',
      headers: { 'Content-Type': blob.type || 'image/png' },
      body: blob,
    });
    if(!res.ok){
      let msg = 'O servidor do Kumiko respondeu com erro (' + res.status + ').';
      try{ const data = await res.json(); if(data.error) msg = data.error; }catch(e){}
      throw new Error(msg);
    }
    const data = await res.json();
    return data;
  }

  autoDetectBtn.onclick = async () => {
    if(autoDetectRunning || !pages.length || currentPageIndex === -1) return;

    const scope = autoDetectScopeEl.value; // 'current' | 'all' | 'range'
    const rtl = autoDetectRtlEl.checked;
    const kumikoReview = autoDetectKumikoReviewEl.checked;

    let targets;
    if(scope === 'all'){
      targets = pages.map((_, i) => i);
    } else if(scope === 'range'){
      const { pages: parsedPages, errors } = parsePageRangeSpec(autoDetectRangeInputEl.value, pages.length);
      if(errors.length){
        alert('Não consegui entender as páginas informadas:\n' + errors.join('\n'));
        return;
      }
      if(!parsedPages.length){
        alert('Digite ao menos uma página válida (ex: 11-25 ou 11,13,16,19).');
        return;
      }
      targets = parsedPages;
    } else {
      targets = [currentPageIndex];
    }

    const hasExisting = targets.some(i => pages[i].frames.length > 0);
    if(hasExisting){
      const msg = targets.length > 1
        ? 'Isso substitui as marcações já existentes nas páginas selecionadas que já têm quadros marcados. Continuar?'
        : 'Isso substitui as marcações já existentes nesta página. Continuar?';
      if(!confirm(msg)) return;
    }

    autoDetectRunning = true;
    renderToolbar();

    try{
      setStatus('Verificando o servidor local do Kumiko…');
      const alive = await pingKumikoServer();
      if(!alive){
        throw new Error(
          'Não consegui falar com o servidor do Kumiko. ' +
          'Rode "python3 kumiko-tools/kumiko_server.py" num terminal e abra o Leitor de HQs ' +
          'pelo endereço que aparece lá (normalmente http://127.0.0.1:8990/), depois tente de novo.'
        );
      }

      let kumikoRescueCount = 0;
      for(let i = 0; i < targets.length; i++){
        const pageIndex = targets[i];
        const page = pages[pageIndex];
        setStatus('Detectando quadros — página ' + (i+1) + '/' + targets.length + '…');

        const blob = await loadPageBlob(page.url);
        const data = await detectFramesViaServer(blob, { rtl, kumikoReview });
        const detected = data.frames || [];
        page.frames = detected.map(f => ({ id: frameIdSeq++, x: f.x, y: f.y, w: f.w, h: f.h }));
        if(data.engine_used === 'kumiko') kumikoRescueCount++;
      }

      let finalMsg = targets.length > 1
        ? 'Quadros detectados em ' + targets.length + ' página(s). Confira e ajuste o que precisar.'
        : 'Quadros detectados nesta página. Confira e ajuste o que precisar.';
      if(kumikoReview && kumikoRescueCount > 0){
        finalMsg += ' (' + kumikoRescueCount + ' página(s) remarcada(s) com o Kumiko.)';
      }
      setStatus(finalMsg);
    }catch(err){
      console.error(err);
      setStatus('Não consegui detectar os quadros automaticamente.');
      alert('Não consegui rodar a detecção automática de quadros: ' + (err.message || err));
    }finally{
      autoDetectRunning = false;
      selectedFrameId = null;
      renderAll();
    }
  };

  // ---------------- Keyboard ----------------
  document.addEventListener('keydown', (e) => {
    if(readerOpen){
      if(e.key === 'ArrowRight'){ readerNext(); }
      else if(e.key === 'ArrowLeft'){ readerPrev(); }
      else if(e.key === 'Escape'){ closeReader(); }
      else if(e.key === 'b' || e.key === 'B'){ setBlackout(!blackoutMode); }
      return;
    }
    if(e.key === 'f' || e.key === 'F'){ addFrameMode = !addFrameMode; renderAll(); }
    else if((e.key === 'Delete' || e.key === 'Backspace') && selectedFrameId !== null){
      const page = currentPage();
      if(page){ page.frames = page.frames.filter(f => f.id !== selectedFrameId); selectedFrameId = null; renderAll(); }
    }
    else if(e.key === 'ArrowRight'){ el('next-page').click(); }
    else if(e.key === 'ArrowLeft'){ el('prev-page').click(); }
    else if(e.key === 'Enter' && pages.length){ openReader(currentPageIndex); }
    else if(e.key === 'Escape'){ selectedFrameId = null; renderAll(); }
  });

  // ---------------- Help popover ----------------
  const helpPop = el('help-pop');
  el('help-btn').onclick = () => helpPop.classList.toggle('open');
  document.addEventListener('click', (e) => {
    if(!helpPop.contains(e.target) && e.target.id !== 'help-btn') helpPop.classList.remove('open');
  });

  // ---------------- Recolher "Ordem de leitura" (útil em telas pequenas) ----------------
  const panelFramesToggle = el('panel-frames-toggle');
  if(panelFramesToggle){
    panelFramesToggle.onclick = () => panelFramesEl.classList.toggle('collapsed');
    // em celulares, começa recolhido pra sobrar mais espaço pra página;
    // em telas maiores, começa aberto como sempre foi.
    if(window.matchMedia('(max-width: 620px)').matches){
      panelFramesEl.classList.add('collapsed');
    }
  }

  renderAll();
})();