from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory, after_this_request
from werkzeug.utils import secure_filename
import os, uuid, shutil
from core.icc_reader import analyze_icc
from core.cmyk_builder import build_from_source

BASE = Path(__file__).resolve().parent
UPLOADS = BASE / 'uploads'
OUTPUT = BASE / 'output'
UPLOADS.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

@app.get('/')
def index():
    return render_template('index.html')

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
def build():
    f = request.files.get('file')
    if not f:
        return jsonify(error='No se recibió archivo'), 400
    job = UPLOADS / uuid.uuid4().hex
    job.mkdir(parents=True, exist_ok=True)
    src = job / secure_filename(f.filename or 'profile.icm')
    f.save(src)
    token = uuid.uuid4().hex
    out_dir = OUTPUT / token
    out_dir.mkdir(parents=True, exist_ok=True)
    desc = (request.form.get('description') or 'ICC Multi2CMYK').strip()
    fn = secure_filename(desc)
    if not fn.lower().endswith('.icc'):
        fn += '.icc'
    out = out_dir / fn
    try:
        res = build_from_source(src, out, desc, request.form.get('copyright', ''), int(request.form.get('intent', '1')), 17, 33)
        v = analyze_icc(out)
        res['validation'] = {
            'color_space': v['color_space'],
            'channels': v['channels'],
            'pcs': v['pcs'],
            'size': out.stat().st_size,
            'A2B_grid': v['luts']['A2B0']['clut']['grid'][:4],
            'B2A_grid': v['luts']['B2A0']['clut']['grid'][:3],
        }
        res['download'] = f'/api/download/{token}/{fn}'
        res['download_filename'] = fn
        return jsonify(res)
    except Exception as e:
        shutil.rmtree(out_dir, ignore_errors=True)
        return jsonify(error=str(e)), 500
    finally:
        shutil.rmtree(job, ignore_errors=True)

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
        return response
    return send_from_directory(directory, filename, as_attachment=True, download_name=filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    app.run(host='0.0.0.0', port=port, debug=False)
