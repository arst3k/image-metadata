from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import exif_utils, ai_detect, scanner, actions


def configure_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s - %(message)s",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="image-metadata",
        description="Herramienta CLI para leer, detectar y modificar metadatos EXIF.",
    )

    src_group = p.add_mutually_exclusive_group(required=True)
    src_group.add_argument("--file", type=str, help="Ruta a un fichero de imagen.")
    src_group.add_argument("--dir", type=str, help="Ruta a una carpeta con imágenes.")

    p.add_argument("-r", "--recursive", action="store_true", help="Búsqueda recursiva en subcarpetas (con --dir).")
    p.add_argument(
        "--report",
        type=str,
        help="Ruta de informe TXT a generar (con --dir). Si se omite, se generará uno por defecto en la carpeta de entrada.",
    )
    p.add_argument(
        "--extensions",
        type=str,
        default=",".join(sorted(exif_utils.SUPPORTED_EXTENSIONS)),
        help="Lista de extensiones a considerar, separadas por coma. Por defecto: %(default)s",
    )
    p.add_argument(
        "--format",
        choices=["txt", "json"],
        default="txt",
        help="Formato de salida por consola (solo modo --file). Por defecto: %(default)s",
    )

    # Detección IA
    p.add_argument("--detect-ai", action="store_true", help="Activar detección de posible origen IA.")
    p.add_argument("--deep-scan", action="store_true", help="Escanear bytes para detectar cadenas relacionadas con IA.")

    # Modificaciones EXIF
    p.add_argument(
        "--strip-identifying",
        action="store_true",
        help="Eliminar metadatos identificativos (autor, cámara, software de edición, GPS, etc.).",
    )
    p.add_argument(
        "--replace-camera",
        type=str,
        help='Reemplazar identidad de cámara. Valores: "canon", "iphone" o "Marca|Modelo".',
    )
    p.add_argument(
        "--replace-extended",
        action="store_true",
        help="Modo extendido: además fija FNumber, ExposureTime, FocalLength, ISO, Lens*, Software genérico.",
    )
    date_group = p.add_mutually_exclusive_group()
    date_group.add_argument(
        "--preserve-dates",
        action="store_true",
        default=True,
        help="Preservar fechas existentes (por defecto).",
    )
    date_group.add_argument(
        "--anonymize-dates",
        action="store_true",
        help="Anonimizar fechas (eliminarlas o fijarlas a un valor genérico).",
    )
    p.add_argument(
        "--remove-orientation",
        action="store_true",
        help="Eliminar la etiqueta de orientación (por defecto se preserva).",
    )

    # Salida/seguridad
    p.add_argument("--in-place", action="store_true", help="Modificar ficheros en sitio.")
    p.add_argument("--backup-ext", type=str, default=".bak", help="Extensión para copia de seguridad (con --in-place).")
    p.add_argument("--out-dir", type=str, help="Carpeta de salida para escribir resultados sin tocar originales.")
    p.add_argument("--dry-run", action="store_true", help="No escribir cambios, solo mostrar qué se haría.")

    # Logging
    p.add_argument("--log-level", default="INFO", help="Nivel de logging: INFO, DEBUG, WARNING, ERROR.")

    return p


def validate_args(args: argparse.Namespace) -> Optional[str]:
    # Si se solicitan modificaciones, validar opciones de salida
    modifications = args.strip_identifying or args.replace_camera or args.replace_extended
    if modifications:
        if args.in_place and args.out_dir:
            return "No se puede usar --in-place y --out-dir simultáneamente."
        if not args.in_place and not args.out_dir and not args.dry_run:
            # Permitimos ejecutar sin escribir (dry-run); si no, avisar.
            logging.getLogger(__name__).warning(
                "No se especificó --in-place ni --out-dir; no se escribirán resultados. Use --dry-run para simular."
            )
    if args.file and args.recursive:
        return "--recursive solo aplica con --dir."
    if args.file and args.report:
        return "--report solo aplica con --dir."
    return None


def build_modify_options(args: argparse.Namespace, base_input_dir: Optional[Path] = None) -> actions.ModifyOptions:
    return actions.ModifyOptions(
        strip_identifying=bool(args.strip_identifying or args.replace_camera or args.replace_extended),
        replace_camera=args.replace_camera,
        replace_extended=bool(args.replace_extended),
        preserve_dates=bool(args.preserve_dates and not args.anonymize_dates),
        anonymize_dates=bool(args.anonymize_dates),
        remove_orientation=bool(args.remove_orientation),
        in_place=bool(args.in_place),
        backup_ext=args.backup_ext if args.in_place else None,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        dry_run=bool(args.dry_run),
        base_input_dir=base_input_dir,
    )


def handle_file(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists() or not path.is_file():
        print(f"Fichero no encontrado: {path}", file=sys.stderr)
        return 2

    log = logging.getLogger("cli.file")
    exts = exif_utils.normalize_extensions(args.extensions)

    info = exif_utils.get_image_info(path)
    fmt = info.get("format")
    supported_for_write = exif_utils.is_format_supported_for_exif(fmt)

    exif_dict = exif_utils.load_exif_dict(path)
    readable: Dict[str, Dict[str, Any]] = exif_utils.exif_to_readable_dict(exif_dict) if exif_dict else {}
    exif_text = exif_utils.exif_to_pretty_text(exif_dict) if exif_dict else "(sin EXIF o no soportado)"

    # Detección IA
    ai_detected = False
    ai_reasons: List[str] = []
    if args.detect_ai:
        ai_detected, ai_reasons = ai_detect.detect_ai(path, readable, args.deep_scan)

    # Mostrar
    if args.format == "json":
        out = {
            "name": path.name,
            "path": str(path.resolve()),
            "image_info": info,
            "supported_for_write": supported_for_write,
            "ai_detected": ai_detected,
            "ai_reasons": ai_reasons,
            "exif": readable,
        }
        print(exif_utils.safe_json_dumps(out))
    else:
        print(f"File: {path.name}")
        print(f"Path: {str(path.resolve())}")
        print(f"Format: {fmt}, Mode: {info.get('mode')}, Size: {info.get('size')}")
        if args.detect_ai:
            print(f"AI suspected: {'YES' if ai_detected else 'NO'}")
            for r in ai_reasons:
                print(f"  * {r}")
        print("EXIF:")
        print(exif_text)

    # Modificaciones (si se pidieron)
    modifications = args.strip_identifying or args.replace_camera or args.replace_extended
    if modifications:
        opts = build_modify_options(args)
        print(f"Plan de modificación: {actions.describe_modification_plan(opts)}")
        if supported_for_write:
            ok, err, dest = actions.apply_strip_and_replace(path, opts)
            if ok:
                print(f"Modificado correctamente -> {str((dest or path).resolve())} {'(dry-run)' if args.dry_run else ''}")
            else:
                print(f"ERROR al modificar: {err}", file=sys.stderr)
                return 3
        else:
            print("Formato no soportado para escritura EXIF; no se aplican modificaciones.", file=sys.stderr)
            return 4

    return 0


def handle_dir(args: argparse.Namespace) -> int:
    dir_path = Path(args.dir)
    if not dir_path.exists() or not dir_path.is_dir():
        print(f"Carpeta no válida: {dir_path}", file=sys.stderr)
        return 2

    log = logging.getLogger("cli.dir")

    exts = exif_utils.normalize_extensions(args.extensions)
    items: List[Dict[str, Any]] = []
    totals = {
        "processed": 0,
        "ai_suspected": 0,
        "modified": 0,
        "errors": 0,
        "unsupported": 0,
    }

    # Opciones de modificación (si corresponden)
    opts = build_modify_options(args, base_input_dir=dir_path.resolve() if args.out_dir else None)

    for img_path in scanner.list_images(dir_path, exts, args.recursive) or []:
        totals["processed"] += 1
        item: Dict[str, Any] = {
            "name": img_path.name,
            "path": str(img_path.resolve()),
            "ai_detected": False,
            "ai_reasons": [],
            "exif_text": "",
            "errors": [],
        }

        info = exif_utils.get_image_info(img_path)
        fmt = info.get("format")
        exif_dict = exif_utils.load_exif_dict(img_path)
        readable = exif_utils.exif_to_readable_dict(exif_dict) if exif_dict else {}
        exif_text = exif_utils.exif_to_pretty_text(exif_dict) if exif_dict else "(sin EXIF o no soportado)"
        item["exif_text"] = exif_text

        if args.detect_ai:
            detected, reasons = ai_detect.detect_ai(img_path, readable, args.deep_scan)
            item["ai_detected"] = detected
            item["ai_reasons"] = reasons
            if detected:
                totals["ai_suspected"] += 1

        # Modificaciones (si se pidieron)
        modifications = args.strip_identifying or args.replace_camera or args.replace_extended
        if modifications:
            if not exif_utils.is_format_supported_for_exif(fmt):
                totals["unsupported"] += 1
                item_errors = item.get("errors")  # type: ignore
                item_errors.append("Formato no soportado para escritura EXIF.")
            else:
                ok, err, dest = actions.apply_strip_and_replace(img_path, opts)
                if ok:
                    totals["modified"] += 1
                else:
                    totals["errors"] += 1
                    item_errors = item.get("errors")  # type: ignore
                    item_errors.append(err or "Error desconocido")

        items.append(item)

    # Generar informe TXT (siempre, por requisitos)
    report_path = Path(args.report) if args.report else scanner.default_report_path(dir_path)
    report_params = {
        "dir": str(dir_path.resolve()),
        "recursive": args.recursive,
        "detect_ai": args.detect_ai,
        "deep_scan": args.deep_scan,
        "strip_identifying": args.strip_identifying,
        "replace_camera": args.replace_camera,
        "replace_extended": args.replace_extended,
        "preserve_dates": args.preserve_dates and not args.anonymize_dates,
        "anonymize_dates": args.anonymize_dates,
        "remove_orientation": args.remove_orientation,
        "in_place": args.in_place,
        "backup_ext": args.backup_ext if args.in_place else None,
        "out_dir": args.out_dir,
        "dry_run": args.dry_run,
        "extensions": args.extensions,
    }
    content = scanner.build_report_text(items, report_params, totals)
    scanner.write_text_file(report_path, content)
    print(f"Informe generado: {str(report_path.resolve())}")
    print(f"Totales: {totals}")

    # Mostrar plan de modificación si aplicaba
    if args.strip_identifying or args.replace_camera or args.replace_extended:
        print(f"Plan de modificación: {actions.describe_modification_plan(opts)}")

    return 0


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    configure_logging(args.log_level)

    err = validate_args(args)
    if err:
        print(err, file=sys.stderr)
        sys.exit(2)

    if args.file:
        code = handle_file(args)
        sys.exit(code)
    elif args.dir:
        code = handle_dir(args)
        sys.exit(code)
    else:
        parser.print_help()
        sys.exit(1)
