# ICC Multi2CMYK · KERAjet

Versión preparada para subir directamente a un repositorio nuevo de GitHub y desplegar en Render.

## Contenido
- `app.py` — aplicación Flask local/web.
- `core/` — lector ICC y generador CMYK.
- `templates/` — interfaz web oscura.
- `static/` — CSS, JavaScript y logo KERAjet.
- `requirements.txt` — dependencias Python, incluido Gunicorn para Render.
- `render.yaml` — configuración de despliegue.
- `.python-version` — Python 3.12.

## Subida a GitHub
1. Crea un repositorio nuevo y vacío llamado `ICC-Multi2CMYK`.
2. Sube TODO el contenido de esta carpeta.
3. No subas `.venv`, `__pycache__`, `uploads` ni `output` si aparecen localmente.
4. Haz `Commit changes`.

## Despliegue en Render
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 300`

La aplicación genera el ICC en un directorio temporal y ofrece la descarga al navegador. No depende de archivos ICC guardados de forma permanente.
