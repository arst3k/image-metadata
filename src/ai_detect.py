from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)

# Core AI-related keywords typically found in EXIF or embedded XMP/strings.
AI_KEYWORDS = [
    "stable diffusion",
    "sdxl",
    "comfyui",
    "invokeai",
    "automatic1111",
    "novelai",
    "midjourney",
    "dall-e",
    "dalle",
    "firefly",
    "adobe firefly",
    "generative fill",
    "leonardo",
    "ideogram",
    "runway",
    "mage.space",
    "controlnet",
    # generic fallbacks (can trigger FPs; used as secondary signals)
    "ai",  # keep as last resort
    "ia",
]

# Tags we will examine in the human-readable EXIF dict
CANDIDATE_TAGS = {
    "Software",
    "ImageDescription",
    "Artist",
    "Make",
    "Model",
    "UserComment",
    "MakerNote",
    "LensModel",
    "HostComputer",
}


def _find_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    text_l = text.lower()
    found = []
    for kw in keywords:
        if kw in text_l:
            found.append(kw)
    return found


def detect_ai_from_exif_readable(readable_exif: Dict[str, Dict[str, object]]) -> Tuple[bool, List[str]]:
    """
    Heuristic over the pretty/human-readable EXIF structure.
    Returns (detected, reasons)
    """
    reasons: List[str] = []

    for ifd_name in ("0th", "Exif", "1st"):
        ifd = readable_exif.get(ifd_name, {})
        for tag_name, val in ifd.items():
            if tag_name not in CANDIDATE_TAGS:
                continue
            try:
                sval = str(val)
            except Exception:
                continue
            hits = _find_keywords(sval, AI_KEYWORDS)
            if hits:
                reasons.append(f"{ifd_name}.{tag_name} contains: {', '.join(sorted(set(hits)))}")

    # GPS tags don't indicate AI origin; skipping GPS IFD.

    return (len(reasons) > 0, reasons)


def deep_scan_bytes(path: Path, extra_keywords: Iterable[str] | None = None, max_matches: int = 20) -> List[str]:
    """
    Optional deep byte scan to catch XMP or arbitrary text blocks.
    Returns list of match reasons like: "bytes: found 'stable diffusion'".
    """
    keywords = list(AI_KEYWORDS)
    if extra_keywords:
        keywords.extend([k for k in extra_keywords if isinstance(k, str) and k])

    # Deduplicate but preserve order
    seen = set()
    keys: List[str] = []
    for k in keywords:
        kl = k.lower()
        if kl not in seen:
            seen.add(kl)
            keys.append(kl)

    matches: List[str] = []
    try:
        with path.open("rb") as f:
            # Read by chunks to avoid loading entire file
            chunk_size = 1024 * 1024  # 1MB
            leftover = b""
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                window = leftover + chunk
                low = window.lower()
                for kw in keys:
                    if kw.encode("utf-8") in low:
                        msg = f"bytes: found '{kw}'"
                        if msg not in matches:
                            matches.append(msg)
                            if len(matches) >= max_matches:
                                return matches
                # keep overlap to catch keywords split across boundaries
                leftover = window[-64:]
    except Exception as e:
        logger.debug("Deep scan failed for %s: %s", path, e)

    return matches


def detect_ai(path: Path, readable_exif: Dict[str, Dict[str, object]], do_deep_scan: bool) -> Tuple[bool, List[str]]:
    """
    Combine EXIF heuristics and optional deep byte scan.
    """
    exif_detected, reasons = detect_ai_from_exif_readable(readable_exif)
    if do_deep_scan:
        deep_reasons = deep_scan_bytes(path)
        reasons.extend(deep_reasons)
        exif_detected = exif_detected or bool(deep_reasons)
    return exif_detected, reasons
