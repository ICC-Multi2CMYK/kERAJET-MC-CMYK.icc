let currentFile = null;
const $ = id => document.getElementById(id);
const dropzone = $('dropzone');
const fileInput = $('file');

function setFile(file){
  currentFile = file || null;
  $('file-name').textContent = currentFile ? currentFile.name : 'Ningún archivo seleccionado';
  $('analysis-status').textContent = currentFile ? 'Archivo listo para analizar.' : 'Esperando archivo…';
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
    $('analysis-status').textContent = 'Perfil analizado correctamente.';
  } catch(e) {
    $('analysis-status').textContent = 'Error al analizar.';
    $('info').textContent = e.message;
    $('info').classList.remove('hidden');
  } finally { $('analyze').disabled = false; }
};

$('build').onclick = async () => {
  if(!currentFile) return alert('Selecciona un ICC/ICM primero.');
  $('build').disabled = true; $('result').classList.remove('hidden'); $('result').textContent = 'Generando perfil CMYK…';
  const f = new FormData();
  f.append('file', currentFile);
  f.append('description', $('desc').value);
  f.append('filename', $('filename').value);
  try {
    const r = await fetch('/api/build',{method:'POST',body:f});
    const j = await r.json();
    if(j.error) throw new Error(j.error);
    $('result').textContent = `✓ Perfil generado correctamente\n${j.download_filename || j.download || ''}\n\nLa descarga comenzará automáticamente.`;
    if(j.download){
      const a = document.createElement('a'); a.href=j.download; a.download=j.download_filename || 'ICC_Multi2CMYK.icc';
      document.body.appendChild(a); a.click(); a.remove();
    }
  } catch(e) { $('result').textContent = 'ERROR: ' + e.message; }
  finally { $('build').disabled = false; }
};
