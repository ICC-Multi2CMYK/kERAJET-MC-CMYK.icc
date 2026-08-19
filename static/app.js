let currentFile = null;
const $ = id => document.getElementById(id);
const dropzone = $('dropzone');
const fileInput = $('file');

function setFile(file){
  currentFile = file || null;
  $('file-name').textContent = currentFile ? `✓ ${currentFile.name}` : 'Ningún archivo seleccionado';
  $('analysis-status').textContent = currentFile ? '✓ Perfil cargado correctamente.' : 'Esperando archivo…';
  dropzone.classList.toggle('file-ready', !!currentFile);
}

function setProgress(percent, label){
  $('progress-wrap').classList.remove('hidden');
  $('progress-bar').style.width = `${Math.max(0, Math.min(100, percent))}%`;
  $('progress-percent').textContent = `${Math.round(percent)}%`;
  $('progress-label').textContent = label;
}

function hideProgress(){
  $('progress-wrap').classList.add('hidden');
}

fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
['dragenter','dragover'].forEach(evt => dropzone.addEventListener(evt, e => {e.preventDefault(); dropzone.classList.add('dragover')}));
['dragleave','drop'].forEach(evt => dropzone.addEventListener(evt, e => {e.preventDefault(); dropzone.classList.remove('dragover')}));
dropzone.addEventListener('drop', e => setFile(e.dataTransfer.files[0]));

$('analyze').onclick = async () => {
  if(!currentFile) return alert('Selecciona un ICC/ICM primero.');
  const f = new FormData(); f.append('file', currentFile);
  $('analyze').disabled = true; $('analysis-status').textContent = 'Analizando…';
  try {
    const r = await fetch('/api/analyze',{method:'POST',body:f});
    const j = await r.json();
    if(j.error) throw new Error(j.error);
    const mapping = ['C','M','Y','K'];
    const channels = j.channels.map((name,i) => `<div>Canal ${i+1}: <b>${name || '(sin nombre)'}</b> → <b>${mapping[i] || 'Especial '+(i-3)}</b></div>`).join('');
    const grids = ['A2B0','A2B1','A2B2'].map(k => j.luts[k]?.grid?.join('×') || '—').join(' · ');
    $('info').innerHTML = `<div><b>${j.description}</b><br>${j.color_space} · ${j.total_channels} canales · PCS ${j.pcs}</div><div style="margin-top:10px">${channels}</div><div style="margin-top:10px;color:#82a8ca">CLUT A2B: ${grids}</div>`;
    $('info').classList.remove('hidden');
    $('analysis-status').textContent = '✓ Perfil analizado correctamente.';
  } catch(e) {
    $('analysis-status').textContent = 'Error al analizar.';
    $('info').textContent = e.message;
    $('info').classList.remove('hidden');
  } finally { $('analyze').disabled = false; }
};

async function downloadWithProgress(url, filename){
  const r = await fetch(url, {cache:'no-store'});
  if(!r.ok) throw new Error(`No se pudo descargar el ICC (${r.status}).`);
  const total = Number(r.headers.get('Content-Length') || 0);
  if(!r.body){
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = filename; document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(a.href);
    setProgress(100, 'Descarga completada');
    return;
  }
  const reader = r.body.getReader();
  const chunks = [];
  let received = 0;
  while(true){
    const {done, value} = await reader.read();
    if(done) break;
    chunks.push(value);
    received += value.byteLength;
    if(total > 0) setProgress((received/total)*100, 'Descargando perfil CMYK…');
    else setProgress(Math.min(95, 10 + received/100000), 'Descargando perfil CMYK…');
  }
  const blob = new Blob(chunks, {type:'application/vnd.iccprofile'});
  const objectUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = objectUrl; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setProgress(100, 'Descarga completada ✓');
  setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
}

$('build').onclick = async () => {
  if(!currentFile) return alert('Selecciona un ICC/ICM primero.');
  $('build').disabled = true;
  $('analyze').disabled = true;
  $('result').classList.remove('hidden');
  $('result').textContent = '';
  setProgress(5, 'Subiendo perfil…');
  const f = new FormData();
  f.append('file', currentFile);
  f.append('description', $('desc').value.trim() || 'ICC Multi2CMYK');
  try {
    setProgress(12, 'Procesando ICC…');
    const r = await fetch('/api/build',{method:'POST',body:f});
    const j = await r.json();
    if(j.error) throw new Error(j.error);
    setProgress(78, 'Perfil generado. Preparando descarga…');
    $('result').textContent = `✓ Perfil generado correctamente\n${j.download_filename}\n\nDescargando automáticamente…`;
    if(j.download){
      await downloadWithProgress(j.download, j.download_filename || 'ICC_Multi2CMYK.icc');
      $('result').textContent = `✓ Perfil generado correctamente\n${j.download_filename}\n\n✓ Descarga completada.`;
    }
  } catch(e) {
    $('result').textContent = 'ERROR: ' + e.message;
    setProgress(0, 'Error');
  } finally {
    $('build').disabled = false;
    $('analyze').disabled = false;
  }
};
