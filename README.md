# audita 1.0 — Segment validation tool

Aplicación de escritorio en Python y CustomTkinter para **revisar y validar segmentos acústicos** (WAV, WAVE, FLAC y OGG). Interfaz en inglés, tema oscuro, espectrograma con paleta magma y reproducción opcional.

## Contenido del paquete

| Archivo | Uso |
| --- | --- |
| `audita.py` | Aplicación principal |
| `logo_audita.png` | Logotipo horizontal dentro de la ventana |
| `audita_icon.png` | Icono cuadrado para la ventana |
| `audita_icon.ico` | Icono multirresolución para Windows |
| `requirements.txt` | Dependencias de Python |
| `README.md` | Estas instrucciones |

**Importante:** deja los seis archivos en **la misma carpeta**. Todavía no hace falta crear un `.exe`.

## Instalar y abrir en Windows

Se recomienda Python **3.10 o posterior**, con `pip` y Tkinter disponibles. En PowerShell, desde la carpeta que contiene los archivos:

```powershell
python -m pip install -r requirements.txt
python audita.py
```

Si tienes varias versiones de Python, puedes usar `py -3 -m pip install -r requirements.txt` y `py -3 audita.py`.

## Flujo de trabajo

1. Escribe el nombre del validador en **Validator**. Los controles se habilitan al introducirlo.
2. Pulsa **Open folder** y elige la carpeta de segmentos. audita busca los archivos compatibles también en subcarpetas.
3. Los segmentos se ordenan por su **confianza numérica inicial de mayor a menor** (por ejemplo, `0.99`, `0.98` y `0.75`). Los que no tienen un prefijo numérico reconocible aparecen después.
4. Filtra por **Proposed species** o utiliza **All species**. La especie propuesta, `mediaID` e intervalo se muestran bajo la barra de selección.
5. Escucha el audio con **Play** (o la barra espaciadora) y revisa el espectrograma; el cursor de reproducción es **cian**. La estrella permite marcar favoritos.
6. Clasifica el segmento como **Positive**, **Negative**, **Uncertain**, **Reassigned** o **Multitaxa**. Para Reassigned y Multitaxa, introduce el nombre científico validado y confirma con **Enter**. Para Multitaxa, separa los nombres con `;`.
7. Añade, si hace falta, un **Validation comment**. Al clasificar, audita guarda automáticamente y pasa al siguiente segmento pendiente dentro del filtro activo.
8. Bajo el espectrograma, el texto **Status** indica si el segmento está pendiente o ya fue validado, y con qué categoría. **Pending →** salta al siguiente sin clasificar. **Undo** revierte la última clasificación.
9. Cuando no quedan segmentos pendientes en toda la carpeta, aparece **Validation completed**. Un filtro de especie también puede quedar completo sin que termine toda la carpeta.
10. **Save CSV** exporta manualmente una copia a la ubicación que elijas.

## Guardado y archivos generados

audita guarda automáticamente las validaciones en **`validaciones.csv`**, dentro de la carpeta seleccionada. Al volver a abrirla recupera el trabajo anterior. Los favoritos se sincronizan además con `.audita_favorites.txt`. Si encuentra un CSV con cabecera antigua, puede guardar una copia `validaciones_formato_anterior.csv` antes de actualizarlo.

Se exportan los segmentos clasificados y también los favoritos todavía no clasificados. El CSV tiene exactamente estas **nueve columnas, en este orden**:

```csv
observationID,mediaID,scientificNameProposed,validationCategory,scientificNameValidated,classifiedBy,favorite,fileName,validationComment
```

- `mediaID` conserva la extensión y las mayúsculas/minúsculas de la grabación original cuando se extrae de su nombre.
- `favorite` se escribe como `true` o `false`.
- `validationComment` es la última columna.
- Los archivos de audio originales no se modifican ni se mueven.

## Atajos

| Tecla | Acción |
| --- | --- |
| P / N / U / R / M | Positive / Negative / Uncertain / Reassigned / Multitaxa |
| Espacio | Reproducir o detener |
| ← / → | Segmento anterior o siguiente |
| Ctrl+Z | Deshacer clasificación |
| Ctrl+S | Guardar |
| Ctrl+O | Abrir carpeta |
| Ctrl+Shift+S | Exportar CSV |
| Enter | Confirmar nombre científico validado |
| F1 | Mostrar ayuda de atajos |

Los atajos de clasificación no deben interferir mientras escribes en los campos de texto.

## Iconos e identidad visual

- **Logotipo principal**: `logo_audita.png` (horizontal, dentro de la app).
- **Icono de la app**: `audita_icon.png` y `audita_icon.ico` (la `a` rosa con la marca verde, proporcionada por el usuario).
- En Windows, el script fija un identificador propio de aplicación antes de iniciar Tkinter e intenta configurar el icono de ventana y de barra de tareas.
- La nitidez y la representación en la barra de tareas pueden depender de Windows, de su caché de iconos y de cómo se arranque el script con Python. **No se garantiza la misma apariencia que un `.exe`**.

## Dependencias

`requirements.txt` conserva las dependencias del proyecto: `customtkinter`, `numpy`, `scipy`, `soundfile`, `sounddevice` y `Pillow`. El paquete no incluye Python ni una instalación de esas bibliotecas. La reproducción requiere un dispositivo de salida de audio compatible.

## Notas de versión

Esta distribución **audita 1.0** unifica nombres de archivos, logo e icono, corrige la coincidencia de posición del cursor cian con el espectrograma y documenta la interfaz y el CSV. No cambia las categorías ni el formato de salida.
