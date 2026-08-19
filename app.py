from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, after_this_request
from werkzeug.utils import secure_filename
import os, uuid, shutil, threading
from concurrent.futures import ThreadPoolExecutor
from core.icc_reader import analyze_icc
from core.cmyk_builder import build_from_source

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / 'uploads'
OUTPUT = BASE / 'output'
UPLOADS.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

# Background worker keeps long ICC builds out of the HTTP request itself.
# This is more robust on hosted environments where a proxy may return an HTML
# timeout page before the CPU-heavy ICC conversion finishes.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='icc-worker')
_jobs = {}
_jobs_lock = threading.Lock()


def _set_job(job_id, **updates):
    with _jobs_lock:
        _jobs.setdefault(job_id, {}).update(updates)


def _run_build_job(job_id, src, out_dir, out, description, copyright_text, intent):
    try:
        _set_job(job_id, status='running', progress=20, label='Analizando perfil…')
        # Build the profile. The builder itself performs the heavy numerical work.
        _set_job(job_id, progress=35, label='Construyendo perfil CMYK…')
        res = build_from_source(src, out, description, copyright_text, intent, 17, 33)

        _set_job(job_id, progress=88, label='Validando perfil ICC…')
        v = analyze_icc(out)
        res['validation'] = {
            'color_space': v['color_space'],
            'channels': v['channels'],
            'pcs': v['pcs'],
            'size': out.stat().st_size,
            'A2B_grid': v['luts']['A2B0']['clut']['grid'][:4],
            'B2A_grid': v['luts']['B2A0']['clut']['grid'][:3],
        }
        res['download'] = f'/api/download/{job_id}/{out.name}'
        res['download_filename'] = out.name
        _set_job(job_id, status='ready', progress=95, label='Perfil generado. Preparando descarga…', result=res)
    except Exception as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        _set_job(job_id, status='error', progress=0, label='Error', error=str(exc))
    finally:
        shutil.rmtree(src.parent, ignore_errors=True)


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/healthz')
def healthz():
    return jsonify(status='ok')


@app.post('/api/analyze')
def analyze():
    f = request.files.get('file')
    if not f:
        return jsonify(error='No se recibió archivo'), 400
    job = UPLOADS / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=True)
    p = job / secure_filename(f.filename or 'profile.icm')
    f.save(p)
    try:
        a = analyze_icc(p)
        luts = {}
        for k, v in a['luts'].items():
            grid = v['clut']['grid'] if v.get('clut') else []
            luts[k] = {'in': v['input_channels'], 'out': v['output_channels'], 'grid': grid}
        return jsonify(file=a['file'], description=a['description'], color_space=a['color_space'], pcs=a['pcs'], channels=a['channel_names'], total_channels=a['channels'], luts=luts)
    except Exception as e:
        return jsonify(error=str(e)), 400
    finally:
        shutil.rmtree(job, ignore_errors=True)


@app.post('/api/build')
def build_start():
    f = request.files.get('file')
    if not f:
        return jsonify(error='No se recibió archivo'), 400

    job_id = uuid.uuid4().hex
    job_dir = UPLOADS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    src = job_dir / secure_filename(f.filename or 'profile.icm')
    f.save(src)

    out_dir = OUTPUT / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    description = (request.form.get('description') or 'ICC Multi2CMYK').strip()
    safe = secure_filename(description) or 'ICC_Multi2CMYK'
    if safe.lower().endswith('.icc'):
        filename = safe
    else:
        filename = safe + '.icc'
    out = out_dir / filename

    intent_text = request.form.get('intent', '1')
    try:
        intent = int(intent_text)
    except ValueError:
        intent = 1

    _set_job(job_id, status='queued', progress=8, label='Perfil recibido. En cola…')
    _executor.submit(_run_build_job, job_id, src, out_dir, out, description, request.form.get('copyright', ''), intent)
    return jsonify(job_id=job_id, status='queued', progress=8, label='Perfil recibido. En cola…')


@app.get('/api/status/<job_id>')
def build_status(job_id):
    with _jobs_lock:
        state = _jobs.get(job_id)
    if not state:
        return jsonify(error='Trabajo no encontrado o expirado'), 404
    payload = {k: v for k, v in state.items() if k != 'result'}
    if state.get('status') == 'ready':
        payload.update(state['result'])
    return jsonify(payload)


@app.get('/api/download/<token>/<filename>')
def download(token, filename):
    filename = secure_filename(filename)
    directory = OUTPUT / token
    path = directory / filename
    if not path.is_file():
        return jsonify(error='Archivo no encontrado o ya descargado'), 404

    @after_this_request
    def cleanup(response):
        shutil.rmtree(directory, ignore_errors=True)
        with _jobs_lock:
            _jobs.pop(token, None)
        return response

    return send_from_directory(directory, filename, as_attachment=True, download_name=filename, mimetype='application/vnd.iccprofile')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
