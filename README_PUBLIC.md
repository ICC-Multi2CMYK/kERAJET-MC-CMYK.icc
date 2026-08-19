# ICC Multi2CMYK · KERAjet

Web local/pública para convertir perfiles ICC multicanal (5–9 canales) a un nuevo perfil CMYK.

## Estilo
Interfaz oscura con branding KERAjet y descarga automática del ICC generado.

## Deploy Render
Build: `pip install -r requirements.txt`
Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 300`
