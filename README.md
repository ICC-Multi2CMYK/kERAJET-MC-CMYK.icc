# ICC Multi2CMYK · Etapa 11

Versión universal para perfiles de 5 a 9 canales: CMYK + 1…5 especiales.

**Corrección importante respecto a la etapa 10:** la A2B nueva ya no copia las curvas A/B del perfil fuente porque la evaluación de la subtabla ya incorpora esas curvas. Copiarlas provocaba una doble aplicación de curvas y podía desplazar las tonalidades. El nuevo perfil CMYK encapsula la transformación completa CMYK→PCS con curvas identidad.

Regla:
- canal 1 → C
- canal 2 → M
- canal 3 → Y
- canal 4 → K
- canal 5…N → especiales, excluidos de la nueva condición CMYK (fijado a 0 durante la reconstrucción)

La CLUT de origen se detecta automáticamente; ya no se exige 8 canales ni una CLUT fija.

## Ejecutar

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Abrir `http://127.0.0.1:5000`.
