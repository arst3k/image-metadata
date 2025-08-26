# image-metadata
Herramienta de línea de comandos (CLI) para leer, detectar y modificar metadatos EXIF en imágenes. Funciona en Windows y Linux, con gestión de dependencias mediante UV.

## Características principales
- Mostrar EXIF de un único fichero (con salida en texto o JSON).
- Recorrer una carpeta (opcionalmente recursiva) y generar un informe TXT con:
  - Nombre y ruta completa de cada imagen.
  - Detección heurística de posible origen IA.
  - Metadatos EXIF legibles (omitidos binarios largos).
- Detección de IA:
  - Heurística sobre campos EXIF (`Software`, `ImageDescription`, `Artist`, `Make`, `Model`, `UserComment`, `MakerNote`, `LensModel`, `HostComputer`).
  - Escaneo profundo opcional de bytes para localizar cadenas típicas de herramientas de IA (p. ej., “stable diffusion”, “midjourney”, “dall-e”, etc.).
- Limpieza de metadatos identificativos (`--strip-identifying`):
  - Elimina GPS, autoría, marca/modelo, serie, owner, lens, software de edición, comentarios de usuario, maker note, identificadores únicos, miniaturas, etc.
  - Preserva dimensiones, color, y por defecto la orientación (para evitar rotaciones inesperadas).
  - Gestión de fechas configurable: preservar por defecto, o anonimizar con `--anonymize-dates`.
- Reemplazo de cámara:
  - `--replace-camera` “canon”, “iphone” o personalizado “Marca|Modelo”.
  - Modo extendido `--replace-extended` que también fija valores plausibles de captura (FNumber, ExposureTime, FocalLength, ISO, Lens*, Software genérico).
- Escritura segura:
  - Modificación in-place con copia de seguridad (`--backup-ext`).
  - Escritura a carpeta de salida (`--out-dir`) manteniendo estructura de subcarpetas.
  - `--dry-run` para simular cambios sin escribir.
- Filtros y salidas:
  - Filtrar por extensiones soportadas.
  - Informe TXT para modo carpeta. En modo fichero, salida por consola en TXT/JSON.

## Requisitos
- Python 3.11+
- [UV](https://github.com/astral-sh/uv) para gestionar dependencias y ejecutar.

## Instalación y ejecución
No es necesario instalar globalmente. Desde la raíz del proyecto:
- Mostrar ayuda:
  ```bash
  uv run python main.py --help
  ```
- Ejecutar el entry-point definido (alternativa):
  ```bash
  uv run image-metadata --help
  ```

En Windows, si las rutas contienen espacios, envuélvelas entre comillas.

## Formatos soportados
- Con EXIF (lectura/escritura): JPEG/JPG, TIFF/TIF, WebP.
- PNG: normalmente no tiene EXIF estándar. Se informará “sin EXIF”; se mostrarán dimensiones vía Pillow (si aplica). Limpieza/reemplazo EXIF no aplica.
- HEIC/HEIF: fuera de alcance en v1 (requiere librerías nativas adicionales).

## Uso rápido

### Ver EXIF de un fichero
TXT por consola:
```bash
uv run python main.py --file tests/exif_test.jpg
```

JSON por consola:
```bash
uv run python main.py --file tests/exif_test.jpg --format json
```

Con detección de IA (heurística + deep-scan opcional):
```bash
uv run python main.py --file tests/exif_test.jpg --detect-ai --deep-scan
```

### Procesar una carpeta y generar informe TXT
Sin recursividad:
```bash
uv run python main.py --dir tests --report tests/output/report.txt --detect-ai
```

Recursivo y deep-scan:
```bash
uv run python main.py --dir tests -r --report tests/output/report.txt --detect-ai --deep-scan
```

Si no se indica `--report`, se generará un TXT con nombre por defecto en la carpeta de entrada.

### Limpiar metadatos identificativos
Escribir a una carpeta de salida (no modifica originales):
```bash
uv run python main.py --dir tests --strip-identifying --out-dir tests/out
```

In-place con copia de seguridad:
```bash
uv run python main.py --dir tests --strip-identifying --in-place --backup-ext ".bak"
```

Simulación (no escribir, solo mostrar plan):
```bash
uv run python main.py --dir tests --strip-identifying --dry-run
```

### Reemplazar metadatos de cámara
Canon por defecto (aplica strip + set Make/Model), in-place con backup:
```bash
uv run python main.py --dir tests --replace-camera canon --in-place --backup-ext ".bak"
```

iPhone con modo extendido + salida a carpeta:
```bash
uv run python main.py --file tests/exif_test.jpg --replace-camera iphone --replace-extended --out-dir tests/out
```

Personalizado (“Marca|Modelo”):
```bash
uv run python main.py --file tests/exif_test.jpg --replace-camera "Nikon|Nikon D850" --out-dir tests/out
```

### Fechas y orientación
- Preservar fechas (por defecto):
  ```bash
  --preserve-dates
  ```
- Anonimizar fechas:
  ```bash
  --anonymize-dates
  ```
- Eliminar orientación:
  ```bash
  --remove-orientation
  ```

### Otros parámetros útiles
- Extensiones a considerar (por defecto: .jpg,.jpeg,.tif,.tiff,.webp):
  ```bash
  --extensions ".jpg,.jpeg,.tiff"
  ```
- Nivel de registro:
  ```bash
  --log-level DEBUG
  ```

## Cómo funciona
- Lectura/edición EXIF con `piexif`.
- Detección de IA:
  - Heurística sobre EXIF legible (p. ej., buscar “stable diffusion”, “midjourney”, “dall-e”, “comfyui”, “invokeai”, “firefly”, etc. en `Software`, `ImageDescription`, `MakerNote`, etc.).
  - Deep scan opcional: busca cadenas en los bytes del fichero para detectar XMP u otros bloques de texto incrustados.
- Limpieza (`--strip-identifying`) elimina IFD GPS, autoría, software de edición, marca/modelo, lens/series/owner, comentarios de usuario, maker note, image unique id, miniatura, etc. Preserva datos técnicos (dimensiones, color) y orientación por defecto.

## Limitaciones y notas
- PNG no tiene EXIF estándar: no se puede “limpiar EXIF” ni “reemplazar EXIF” en PNG (se informará).
- HEIC/HEIF no soportado en v1.
- La detección de IA es heurística y puede producir falsos positivos/negativos.
- El modo deep-scan es más lento (lee el fichero por bloques); úsalo solo cuando sea necesario.

## Desarrollo
Estructura del proyecto:
```
.
├─ main.py                  # Punto de entrada, delega en src/cli.py
├─ src/
│  ├─ cli.py                # CLI (argparse), modos --file/--dir, informe TXT
│  ├─ exif_utils.py         # Utilidades EXIF: load/dump, render texto/JSON, strip y helpers
│  ├─ ai_detect.py          # Heurística IA y deep-scan por bytes
│  ├─ scanner.py            # Recorrido de carpetas, construcción de informes
│  └─ actions.py            # Escritura segura, backup, out-dir, replace-camera/extended
└─ pyproject.toml           # Dependencias y entry-point
```

Ejecutar tests manuales:
- Mostrar EXIF: `uv run python main.py --file tests/exif_test.jpg --detect-ai`
- Informe: `uv run python main.py --dir tests -r --report tests/output/report.txt --detect-ai --deep-scan`
- Limpieza (simulada): `uv run python main.py --dir tests --strip-identifying --dry-run`
- Reemplazo Canon/iPhone: ver ejemplos anteriores.

## Licencia
Este proyecto se distribuye bajo la licencia incluida en `LICENSE`.
