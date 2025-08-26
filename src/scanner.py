from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Set

from . import exif_utils

logger = logging.getLogger(__name__)


def list_images(dir_path: Path, exts: Set[str], recursive: bool) -> Iterator[Path]:
    """
    Yield image files in dir_path filtered by allowed extensions.
    """
    if not dir_path.exists() or not dir_path.is_dir():
        return
    if recursive:
        for p in dir_path.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                yield p
    else:
        for p in dir_path.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                yield p


def format_header(params: Dict[str, str | bool | int | float | None]) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append("EXIF Report")
    lines.append(f"Generated at: {now}")
    lines.append("Parameters:")
    for k, v in params.items():
        lines.append(f"  - {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def build_item_section(item: Dict[str, object]) -> str:
    """
    Build the per-image section as text.
    """
    name = item.get("name")
    path = item.get("path")
    ai = item.get("ai_detected")
    reasons: List[str] = item.get("ai_reasons") or []  # type: ignore
    exif_text: str = item.get("exif_text") or ""  # type: ignore
    errors: List[str] = item.get("errors") or []  # type: ignore

    lines: List[str] = []
    lines.append(f"File: {name}")
    lines.append(f"Path: {path}")
    lines.append(f"AI suspected: {'YES' if ai else 'NO'}")
    if reasons:
        for r in reasons:
            lines.append(f"  * {r}")
    if errors:
        lines.append("Errors:")
        for e in errors:
            lines.append(f"  ! {e}")
    lines.append("EXIF:")
    lines.append(exif_text if exif_text else "(no EXIF or not supported)")
    lines.append("-" * 60)
    lines.append("")
    return "\n".join(lines)


def build_report_text(
    items: Sequence[Dict[str, object]],
    params: Dict[str, str | bool | int | float | None],
    totals: Optional[Dict[str, int]] = None,
) -> str:
    """
    Assemble the full TXT report content.
    """
    parts: List[str] = [format_header(params)]
    for it in items:
        parts.append(build_item_section(it))
    if totals:
        parts.append("Summary:")
        for k, v in totals.items():
            parts.append(f"  - {k}: {v}")
        parts.append("")
    return "\n".join(parts)


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def default_report_path(base_dir: Path) -> Path:
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return base_dir / f"exif_report_{ts}.txt"
