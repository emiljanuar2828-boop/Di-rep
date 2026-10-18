(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const config = JSON.parse($('#app-config').textContent);
  const state = { step: 1, files: [], glyphs: [], id: null, pageCount: 0, fontURL: null, installed: false };
  const zone = $('#drop-zone'), fileInput = $('#file-input'), uploadList = $('#upload-list'), errorBox = $('#upload-error'), scanButton = $('#scan-button'), scanProgress = $('#scan-progress');

  function showError(element, text) { element.textContent = text; element.hidden = false; }
  function hideError(element) { element.hidden = true; element.textContent = ''; }
  
  function setStep(number) {
    if (number < 1 || number > 4) return;
    state.step = number;
    $$('.step-panel').forEach(panel => {
      const active = Number(panel.dataset.step) === number;
      panel.classList.toggle('is-active', active); panel.hidden = !active;
    });
    $$('.stepper-step').forEach(button => {
      const step = Number(button.dataset.stepTarget);
      button.classList.toggle('active', step === number); button.classList.toggle('completed', step < number);
      if (step === number) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
    });
    $('#step-count').textContent = String(number).padStart(2, '0');
    if (number === 3 && state.glyphs.length) updateRedrawChoices();
    if (number === 4) $('#preview-text').dispatchEvent(new Event('input'));
    $('#workflow').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  document.addEventListener('click', event => {
    const go = event.target.closest('[data-go]'); if (go) setStep(Number(go.dataset.go));
  });
  $$('.stepper-step').forEach(button => button.addEventListener('click', () => {
    const target = Number(button.dataset.stepTarget);
    if (target <= state.step || target === state.step + 1 && (target !== 3 || state.glyphs.length)) setStep(target);
  }));

  function renderFiles() {
    uploadList.replaceChildren(); uploadList.hidden = !state.files.length;
    state.files.forEach((file, index) => {
      const row = document.createElement('div'); row.className = 'upload-file';
      const name = document.createElement('span'); name.className = 'upload-file-name';
      const icon = document.createElement('span'); icon.className = 'file-icon'; icon.textContent = 'IMG';
      const filename = document.createElement('span'); filename.textContent = file.name;
      name.append(icon, filename);
      const controls = document.createElement('span'); controls.className = 'upload-select-control';
      const label = document.createElement('label'); label.className = 'page-label'; label.htmlFor = `page-${index}`; label.textContent = 'Seite';
      const select = document.createElement('select'); select.className = 'page-select'; select.id = `page-${index}`; select.setAttribute('aria-label', `Vorlagenseite für ${file.name}`);
      for (let page = 1; page <= config.pageCount; page++) { const option = document.createElement('option'); option.value = String(page - 1); option.textContent = `Seite ${page} · ${config.pageGroups[page - 1].length} Zeichen`; select.append(option); }
      const usedPages = new Set(state.files.filter((_, i) => i !== index).map(item => item.page));
      for (const option of select.options) if (usedPages.has(Number(option.value))) option.disabled = true;
      select.value = String(file.page ?? index);
      select.addEventListener('change', () => { state.files[index].page = Number(select.value); renderFiles(); });
      const remove = document.createElement('button'); remove.type = 'button'; remove.setAttribute('aria-label', `Entfernen ${file.name}`); remove.textContent = '×';
      remove.addEventListener('click', () => { state.files.splice(index, 1); renderFiles(); });
      controls.append(label, select, remove); row.append(name, controls); uploadList.append(row);
    });
    scanButton.disabled = !state.files.length;
  }
  function addFiles(fileList) {
    hideError(errorBox);
    for (const file of fileList) {
      if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { showError(errorBox, `${file.name}: Bitte nur PNG-, JPG- oder WebP-Bilder auswählen.`); continue; }
      if (file.size > 18 * 1024 * 1024) { showError(errorBox, `${file.name}: Die Datei ist größer als 18 MB.`); continue; }
      if (state.files.length >= config.pageCount) { showError(errorBox, `Die Vorlage hat ${config.pageCount} Seiten. Entferne zuerst ein Bild, bevor du weitere Seiten hinzufügst.`); break; }
      if (state.files.some(item => item.name === file.name && item.size === file.size)) continue;
      const usedPages = new Set(state.files.map(item => item.page));
      const page = Array.from({ length: config.pageCount }, (_, index) => index).find(index => !usedPages.has(index));
      state.files.push(Object.assign(file, { page }));
    }
    renderFiles();
  }
  fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });
  zone.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); fileInput.click(); } });
  for (const eventName of ['dragenter', 'dragover']) zone.addEventListener(eventName, event => { event.preventDefault(); zone.classList.add('dragover'); });
  for (const eventName of ['dragleave', 'drop']) zone.addEventListener(eventName, event => { event.preventDefault(); zone.classList.remove('dragover'); });
  zone.addEventListener('drop', event => addFiles(event.dataTransfer.files));

  function svgDataURL(glyph) {
    if (!glyph?.contours?.length) return '';
    const all = glyph.contours.flat();
    const minX = Math.min(...all.map(point => point[0])), maxX = Math.max(...all.map(point => point[0]));
    const minY = Math.min(...all.map(point => point[1])), maxY = Math.max(...all.map(point => point[1]));
    const pad = 15, width = Math.max(1, maxX - minX), height = Math.max(1, maxY - minY);
    const paths = glyph.contours.map(contour => `M${contour.map(([x,y]) => `${x-minX+pad},${maxY-y+pad}`).join('L')}Z`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="280" height="90" viewBox="0 0 ${width+pad*2} ${height+pad*2}" preserveAspectRatio="xMidYMid meet"><path fill="#354a39" d="${paths}"/></svg>`;
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }
  function variantsFor(char) { return state.glyphs.find(glyph => glyph.char === char)?.variants ?? []; }
  function renderGlyphs(filter = '') {
    const grid = $('#glyph-grid'), fragment = document.createDocumentFragment(), query = filter.toLocaleLowerCase('de');
    const filtered = state.glyphs.filter(glyph => !query || glyph.char.toLocaleLowerCase('de') === query || glyph.char.toLocaleUpperCase('de') === query || glyph.sourceChar.toLocaleLowerCase('de') === query);
    for (const glyph of filtered) {
      const variants = variantsFor(glyph.char), card = document.createElement('article');
      card.className = `glyph-card${variants.length ? '' : ' missing'}`; card.dataset.glyph = glyph.char;
      const head = document.createElement('div'); head.className = 'glyph-card-top';
      const original = document.createElement('span'); original.className = 'glyph-source'; original.textContent = `Original: ${glyph.sourceChar === ' ' ? 'Leerzeichen' : glyph.sourceChar}`;
      const count = document.createElement('span'); count.className = `variant-count${variants.length ? '' : ' zero'}`; count.textContent = `${variants.length} ${variants.length === 1 ? 'Probe' : 'Proben'}`; head.append(original, count);
      const image = document.createElement('img'); image.className = 'glyph-canvas'; image.alt = variants.length ? `${variants.length} erkannte Handschriftprobe für ${glyph.char}` : `Keine lesbare Probe für ${glyph.char}`; image.src = svgDataURL(variants[0]) || 'data:image/gif;base64,R0lGODlhAQABAAAAACw=';
      const controls = document.createElement('div'); controls.className = 'glyph-control';
      const input = document.createElement('input'); input.className = 'glyph-char'; input.maxLength = 1; input.value = glyph.char; input.setAttribute('aria-label', `Korrekte Zeichenzuordnung für ${glyph.char}`); input.autocomplete = 'off';
      const select = document.createElement('select'); select.className = 'variant-select'; select.setAttribute('aria-label', `Aktive Handschriftprobe für ${glyph.char}`);
      if (!variants.length) { const option = document.createElement('option'); option.value = ''; option.textContent = 'Fehlt'; select.append(option); }
      variants.forEach((_, index) => { const option = document.createElement('option'); option.value = String(index); option.textContent = `Variante ${index + 1}`; select.append(option); });
      controls.append(input, select); card.append(head, image, controls);
      input.addEventListener('input', () => {
        const value = [...input.value][0]; if (!value) return;
        const current = state.glyphs.indexOf(glyph), other = state.glyphs.findIndex(item => item.char === value && item !== glyph);
        input.setCustomValidity('');
        if (other !== -1) state.glyphs[other].char = glyph.char;
        state.glyphs[current].char = value;
        renderGlyphs($('#glyph-search').value);
      });
      select.addEventListener('change', () => { if (variants[select.value]) image.src = svgDataURL(variants[select.value]); });
      fragment.append(card);
    }
    grid.replaceChildren(fragment);
    const complete = state.glyphs.filter(glyph => variantsFor(glyph.char).length > 0 && config.characters.includes(glyph.char)).length;
    const sampleCount = state.glyphs.reduce((total, glyph) => total + variantsFor(glyph.char).length, 0);
    $('#assignment-count').textContent = `${complete} / ${state.glyphs.length} Zeichen mit Probe · max. 3 Varianten je Zeichen`;
    $('#recognized-count').textContent = String(sampleCount).padStart(2, '0');
    const warning = $('#review-warning'), missing = state.glyphs.length - complete;
    warning.textContent = missing ? `${missing} Zeichen ohne lesbare Probe. Markiere sie rot und ergänze die Handschriftprobe direkt mit „Zeichen ergänzen“ auf deinem Bildschirm. Eine lesbare Probe je Zeichen ist nötig.` : `${sampleCount} Formen erkannt. Verschiedene Proben desselben Zeichens werden als echte, kontextabhängige Alternativen in den fertigen Font eingebettet.`;
    warning.classList.toggle('has-missing', missing > 0);
    updateRedrawChoices();
  }
  $('#glyph-search').addEventListener('input', event => renderGlyphs(event.target.value));

  const dialog = $('#redraw-dialog'), drawCanvas = $('#redraw-canvas'), drawContext = drawCanvas.getContext('2d');
  let drawing = false, hasDrawn = false, previousPoint = null;
  drawContext.lineWidth = 11; drawContext.lineCap = 'round'; drawContext.lineJoin = 'round'; drawContext.strokeStyle = '#354a39';
  drawContext.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
  drawContext.beginPath(); drawContext.moveTo(0, 239); drawContext.lineTo(drawCanvas.width, 239); drawContext.strokeStyle = '#e9ece6'; drawContext.lineWidth = 2; drawContext.stroke(); drawContext.strokeStyle = '#354a39'; drawContext.lineWidth = 11;
  function updateRedrawChoices() {
    const select = $('#redraw-char'); if (!select || !state.glyphs.length) return;
    const previous = select.value;
    select.replaceChildren();
    for (const glyph of state.glyphs) if (glyph.variants.length < 3) {
      const option = document.createElement('option'); option.value = glyph.char; option.textContent = `${glyph.char} · ${glyph.variants.length} von 3 Proben`; select.append(option);
    }
    if (state.glyphs.some(glyph => glyph.char === previous && glyph.variants.length < 3)) select.value = previous;
    $('#open-redraw').disabled = select.options.length === 0;
    if (!select.options.length) $('#open-redraw').textContent = 'Alle Proben ausgefüllt';
    else $('#open-redraw').textContent = '＋ Zeichen ergänzen';
  }
  function clearRedraw() {
    drawContext.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
    drawContext.beginPath(); drawContext.moveTo(0, 239); drawContext.lineTo(drawCanvas.width, 239); drawContext.strokeStyle = '#e9ece6'; drawContext.lineWidth = 2; drawContext.stroke(); drawContext.strokeStyle = '#354a39'; drawContext.lineWidth = 11;
    hasDrawn = false; hideError($('#redraw-error'));
  }
  $('#open-redraw').addEventListener('click', () => {
    updateRedrawChoices(); hideError($('#redraw-error')); clearRedraw();
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
  });
  $('#redraw-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  $('#clear-redraw').addEventListener('click', clearRedraw);
  function getDrawPoint(event) {
    const bounds = drawCanvas.getBoundingClientRect(); return { x: (event.clientX - bounds.left) * drawCanvas.width / bounds.width, y: (event.clientY - bounds.top) * drawCanvas.height / bounds.height };
  }
  drawCanvas.addEventListener('pointerdown', event => { event.preventDefault(); drawing = true; hasDrawn = true; previousPoint = getDrawPoint(event); drawCanvas.setPointerCapture(event.pointerId); drawContext.beginPath(); drawContext.moveTo(previousPoint.x, previousPoint.y); });
  drawCanvas.addEventListener('pointermove', event => {
    if (!drawing) return; event.preventDefault(); const point = getDrawPoint(event);
    drawContext.beginPath(); drawContext.moveTo(previousPoint.x, previousPoint.y); drawContext.lineTo(point.x, point.y); drawContext.stroke(); previousPoint = point;
  });
  for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) drawCanvas.addEventListener(name, () => { drawing = false; previousPoint = null; });
  $('#save-redraw').addEventListener('click', async () => {
    if (!hasDrawn) { showError($('#redraw-error'), 'Zeichne zuerst den ausgewählten Buchstaben in das Feld.'); return; }
    const char = $('#redraw-char').value, glyph = state.glyphs.find(item => item.char === char);
    if (!glyph || glyph.variants.length >= 3) { showError($('#redraw-error'), 'Für dieses Zeichen ist kein weiteres Variantenfeld verfügbar.'); return; }
    hideError($('#redraw-error')); $('#save-redraw').disabled = true;
    try {
      const blob = await new Promise(resolve => drawCanvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('Die Zeichnung konnte nicht gespeichert werden.');
      const form = new FormData(); form.append('image', blob, 'handschrift.png');
      form.append('id', state.id);
      form.append('char', char);
      const response = await fetch('/api/glyph/trace', { method: 'POST', body: form }), result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Die Zeichnung konnte nicht erkannt werden.');
      glyph.variants = result.variants;
      renderGlyphs($('#glyph-search').value); clearRedraw(); dialog.close();
    } catch (error) { showError($('#redraw-error'), error.message || 'Zeichnung fehlgeschlagen. Bitte versuche es erneut.'); }
    finally { $('#save-redraw').disabled = false; }
  });

  scanButton.addEventListener('click', async () => {
    if (!state.files.length) return;
    hideError(errorBox); scanButton.disabled = true; scanProgress.hidden = false; $('#scan-message').textContent = 'Dein Foto wird entzerrt und gelesen …';
    const form = new FormData(); state.files.forEach(file => { form.append('files', file, file.name); form.append('page_numbers', String(file.page)); });
    try {
      const response = await fetch('/api/scan', { method: 'POST', body: form });
      const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Das Foto konnte nicht gelesen werden.');
      state.id = result.id; state.glyphs = result.glyphs; state.pageCount = result.chars;
      const noMarks = result.detected === 0;
      if (noMarks) { setStep(2); showError(errorBox, 'In den Vorlagenfeldern wurden keine Schriftzüge erkannt. Prüfe die gewählte Vorlagenseite und fotografiere das Blatt mit dunklem Stift bei gutem Licht erneut.'); return; }
      renderGlyphs(); setStep(3);
    } catch (error) { showError(errorBox, error.message || 'Verbindung fehlgeschlagen. Bitte überprüfe deine Bilder und versuche es erneut.'); }
    finally { scanProgress.hidden = true; scanButton.disabled = !state.files.length; }
  });

  function validateGlyphs() {
    const used = new Set();
    for (const glyph of state.glyphs) {
      if ([...glyph.char].length !== 1 || !config.characters.includes(glyph.char)) return 'Jede Zuordnung muss ein einzelnes Zeichen aus der Vorlage sein – einschließlich Ä, Ö, Ü, ä, ö, ü und ß.';
      if (used.has(glyph.char)) return `Das Zeichen „${glyph.char}“ ist mehrfach zugeordnet. Wähle für jedes Zeichen eine eindeutige Zuordnung.`;
      used.add(glyph.char);
      if (!glyph.variants.length) return `Für „${glyph.char}“ wurde keine Handschriftprobe erkannt. Lade die entsprechende Seite noch einmal hoch.`;
      glyph.variants = glyph.variants.slice(0, 3);
    }
    if (state.glyphs.length !== state.pageCount) return 'Die Vorlage ist unvollständig. Bitte scanne sie erneut.';
    return '';
  }
  async function refreshPreview() {
    const error = validateGlyphs();
    if (error) { showError($('#mapping-error'), error); setStep(3); return; }
    hideError($('#mapping-error')); hideError($('#export-error'));
    $('#preview-button').disabled = true; $('#rebuild-button').disabled = true;
    $('#font-build-status').textContent = 'Erstelle deinen echten TrueType-Font …';
    try {
      const response = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: state.id, format: 'ttf', glyphs: state.glyphs }) });
      if (!response.ok) { let data = {}; try { data = await response.json(); } catch (_) { data.error = await response.text(); } throw new Error(data.error || 'Die Vorschau konnte nicht erzeugt werden.'); }
      const blob = await response.blob();
      if (state.fontURL) URL.revokeObjectURL(state.fontURL);
      state.fontURL = URL.createObjectURL(blob);
      if (state.installed) document.fonts.delete('FederwerkHandschrift');
      const style = document.getElementById('generated-font-style') || document.createElement('style'); style.id = 'generated-font-style'; style.textContent = `@font-face { font-family: "FederwerkHandschrift"; src: url("${state.fontURL}") format("truetype"); font-display: swap; }`; document.head.append(style);
      await document.fonts.load('24px FederwerkHandschrift'); state.installed = true;
      $('#preview-text').style.fontFamily = '"FederwerkHandschrift", "Playfair Display", Georgia, serif';
      $('#preview-text').style.fontFeatureSettings = '"calt" 1';
      $('#font-build-status').textContent = 'Dein echter TrueType-Font ist live. Die Vorschau verwendet deine Handschrift und die korrigierten Zuordnungen.';
      setStep(4);
    } catch (error) { $('#font-build-status').textContent = ''; showError($('#mapping-error'), error.message || 'Der Font konnte nicht erzeugt werden.'); }
    finally { $('#preview-button').disabled = false; $('#rebuild-button').disabled = false; }
  }
  $('#preview-button').addEventListener('click', refreshPreview); $('#rebuild-button').addEventListener('click', refreshPreview);

  async function downloadFont(format, button) {
    const error = validateGlyphs(); if (error) { showError($('#export-error'), error); return; }
    hideError($('#export-error')); const label = button.innerHTML; button.disabled = true; button.textContent = 'Wird erstellt …';
    try {
      const response = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: state.id, format, glyphs: state.glyphs }) });
      if (!response.ok) { let data = {}; try { data = await response.json(); } catch (_) { data.error = await response.text(); } throw new Error(data.error || `${format.toUpperCase()} konnte nicht erstellt werden.`); }
      const blob = await response.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = `federwerk-handschrift.${format}`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
      $('#font-build-status').textContent = `${format.toUpperCase()} wurde sicher erstellt und heruntergeladen.`;
    } catch (err) { showError($('#export-error'), err.message || 'Download fehlgeschlagen. Bitte versuche es erneut.'); }
    finally { button.disabled = false; button.innerHTML = label; }
  }
  $$('.download-button').forEach(button => button.addEventListener('click', () => downloadFont(button.dataset.export, button)));
  $('#preview-text').addEventListener('input', event => { $('#preview-character-count').textContent = `${[...event.target.value].length} / 280`; });

  const styles = document.createElement('style'); styles.textContent = '.upload-select-control{display:flex;align-items:center;gap:5px;flex:none}.page-label{color:#82867d;font-size:9px}.page-select{height:23px;padding:2px 5px;border:1px solid #e7e9e3;border-radius:4px;background:#fff;color:#50584d;font-size:10px}.upload-select-control>button{width:24px;height:24px;font-size:17px}'; document.head.append(styles);
  renderFiles(); $('#preview-character-count').textContent = `${[...$('#preview-text').value].length} / 280`;
})();
