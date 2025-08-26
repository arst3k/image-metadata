from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import exif_utils

logger = logging.getLogger(__name__)


@dataclass
class ModifyOptions:
    strip_identifying: bool = False
    replace_camera: Optional[str] = None  # "canon" | "iphone" | "Brand|Model" | None
    replace_extended: bool = False
    preserve_dates: bool = True
    anonymize_dates: bool = False
    remove_orientation: bool = False

    in_place: bool = False
    backup_ext: Optional[str] = ".bak"
    out_dir: Optional[Path] = None
    dry_run: bool = False

    # For computing out paths when --dir was used (to mirror structure)
    base_input_dir: Optional[Path] = None


def is_supported_for_write(path: Path) -> bool:
    """
    Check if the image format is supported for EXIF writes.
    """
    info = exif_utils.get_image_info(path)
    fmt = info.get("format")
    return exif_utils.is_format_supported_for_exif(fmt)


def make_output_path(src: Path, opts: ModifyOptions) -> Path:
    """
    Decide destination path for writing modified file.
    - If in_place: same as src
    - Else if out_dir: mirror relative path from base_input_dir to out_dir (if provided),
      otherwise out_dir / src.name
    """
    if opts.in_place or not opts.out_dir:
        return src

    out_dir = opts.out_dir
    assert out_dir is not None
    out_dir.mkdir(parents=True, exist_ok=True)

    if opts.base_input_dir and src.is_absolute():
        try:
            rel = src.relative_to(opts.base_input_dir)
        except Exception:
            rel = src.name
    else:
        # If base_input_dir is not set or src isn't under it, fallback to just basename
        rel = src.name

    dest = out_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def write_bytes(dest: Path, data: bytes, opts: ModifyOptions) -> None:
    """
    Write bytes to destination, handling in-place backup if requested.
    """
    if opts.in_place:
        if opts.backup_ext:
            backup = dest.with_name(dest.name + (opts.backup_ext or ""))
            try:
                if dest.exists():
                    shutil.copy2(dest, backup)
                    logger.debug("Backup created at %s", backup)
            except Exception as e:
                logger.warning("Failed to create backup for %s: %s", dest, e)
        if not opts.dry_run:
            dest.write_bytes(data)
            logger.info("Wrote modified file (in-place): %s", dest)
        else:
            logger.info("Dry-run: would write (in-place) %s", dest)
    else:
        if not opts.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            logger.info("Wrote modified file: %s", dest)
        else:
            logger.info("Dry-run: would write %s", dest)


def apply_strip_and_replace(src: Path, opts: ModifyOptions) -> Tuple[bool, Optional[str], Optional[Path]]:
    """
    Apply strip-identifying and optional camera replacement to a single file.
    Returns (success, error_msg, dest_path)
    """
    if not is_supported_for_write(src):
        return (False, f"Format not supported for EXIF write: {src}", None)

    # Load existing exif (may be None)
    exif = exif_utils.load_exif_dict(src) or exif_utils.ensure_exif_structure({})

    # Strip identification metadata if requested
    if opts.strip_identifying or opts.replace_camera or opts.replace_extended:
        exif = exif_utils.strip_identifying(
            exif,
            preserve_dates=opts.preserve_dates,
            anonymize_dates=opts.anonymize_dates,
            remove_orientation=opts.remove_orientation,
        )

    # Replace camera if requested
    if opts.replace_camera:
        profile, make, model = exif_utils.get_default_camera_profile(opts.replace_camera)
        if opts.replace_extended:
            exif = exif_utils.apply_extended_camera_profile(
                exif, profile=profile, make=make, model=model
            )
        else:
            exif = exif_utils.set_camera_make_model(exif, make=make, model=model)

    # If only --strip-identifying was requested, we still write the resulting EXIF
    if opts.dry_run:
        dest = make_output_path(src, opts)
        logger.info("Dry-run: would write modified EXIF to %s", dest)
        return (True, None, dest)

    dest = make_output_path(src, opts)

    # If writing to a different output directory, use filename-based insert to avoid in-memory path issues
    if not opts.dry_run and (opts.out_dir and dest != src):
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            exif_utils.write_exif_to_file(src, dest, exif)
            logger.info("Wrote modified file: %s", dest)
            return (True, None, dest)
        except Exception as e:
            return (False, f"Failed to write modified file {dest}: {e}", dest)

    # Otherwise, use the bytes-based insert and our write_bytes helper (covers in-place + backup)
    try:
        data_out = exif_utils.write_exif_to_image_bytes(src, exif)
    except Exception as e:
        return (False, f"Failed to dump/insert EXIF for {src}: {e}", None)

    try:
        write_bytes(dest, data_out, opts)
        return (True, None, dest)
    except Exception as e:
        return (False, f"Failed to write modified file {dest}: {e}", dest)


def describe_modification_plan(opts: ModifyOptions) -> str:
    """
    Human-readable summary of what actions will be performed.
    """
    parts = []
    if opts.strip_identifying:
        parts.append("strip-identifying")
    if opts.replace_camera:
        parts.append(f"replace-camera={opts.replace_camera} ({'extended' if opts.replace_extended else 'basic'})")
    if not parts:
        return "no modifications"
    extras = []
    extras.append("preserve-dates" if opts.preserve_dates and not opts.anonymize_dates else "anonymize-dates")
    if opts.remove_orientation:
        extras.append("remove-orientation")
    if opts.in_place:
        extras.append("in-place")
        if opts.backup_ext:
            extras.append(f"backup={opts.backup_ext}")
    else:
        if opts.out_dir:
            extras.append(f"out-dir={opts.out_dir}")
    if opts.dry_run:
        extras.append("dry-run")
    return ", ".join(parts + extras)
