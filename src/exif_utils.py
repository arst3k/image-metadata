from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from PIL import Image
import piexif
from piexif import ExifIFD, ImageIFD, GPSIFD

logger = logging.getLogger(__name__)

# Extensions and formats supported for EXIF manipulation
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
SUPPORTED_FORMATS = {"JPEG", "TIFF", "WEBP"}

# Windows XP tags (utf-16le encoded)
XP_TITLE = 40091
XP_COMMENT = 40092
XP_AUTHOR = 40093
XP_KEYWORDS = 40094
XP_SUBJECT = 40095
XP_TAGS = {XP_TITLE, XP_COMMENT, XP_AUTHOR, XP_KEYWORDS, XP_SUBJECT}


def normalize_extensions(exts: Optional[str]) -> set[str]:
    """
    Normalize a comma-separated list of extensions into a lowercase set with leading dots.
    """
    if not exts:
        return set(SUPPORTED_EXTENSIONS)
    parts = [e.strip().lower() for e in exts.split(",") if e.strip()]
    normalized = set()
    for p in parts:
        normalized.add(p if p.startswith(".") else f".{p}")
    return normalized


def open_image(path: Union[str, Path]) -> Image.Image:
    return Image.open(str(path))


def get_image_info(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Return basic information about an image regardless of EXIF presence.
    """
    try:
        with Image.open(str(path)) as im:
            info = {
                "format": im.format,
                "mode": im.mode,
                "size": im.size,  # (width, height)
            }
            return info
    except Exception as e:
        logger.warning("Failed to open image %s: %s", path, e)
        return {"format": None, "mode": None, "size": None, "error": str(e)}


def is_format_supported_for_exif(fmt: Optional[str]) -> bool:
    return fmt in SUPPORTED_FORMATS


def load_exif_dict(path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """
    Load EXIF dictionary using piexif. Returns None if not supported or no EXIF.
    piexif.load returns dict even if empty for supported formats; we unify behavior.
    """
    try:
        exif = piexif.load(str(path))
        # Ensure required keys exist
        for k in ("0th", "Exif", "GPS", "1st"):
            exif.setdefault(k, {})
        exif.setdefault("thumbnail", None)
        return exif
    except Exception as e:
        logger.debug("piexif.load failed for %s: %s", path, e)
        return None


def ensure_exif_structure(exif: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Ensure a valid EXIF dict structure exists for dumping.
    """
    if exif is None:
        exif = {}
    exif.setdefault("0th", {})
    exif.setdefault("Exif", {})
    exif.setdefault("GPS", {})
    exif.setdefault("1st", {})
    exif.setdefault("thumbnail", None)
    return exif


def _tag_name(ifd: str, tag: int) -> str:
    try:
        return piexif.TAGS[ifd][tag]["name"]
    except Exception:
        return f"Tag{tag}"


def _decode_bytes_value(tag: int, value: bytes) -> str:
    """
    Decode bytes safely for human-readable output. XP tags use UTF-16LE.
    """
    if tag in XP_TAGS:
        try:
            # XP tags are UTF-16LE and may be nul-terminated
            s = value.decode("utf-16le", errors="ignore")
            return s.rstrip("\x00")
        except Exception:
            pass
    # Try utf-8 then latin-1
    try:
        return value.decode("utf-8", errors="ignore")
    except Exception:
        try:
            return value.decode("latin-1", errors="ignore")
        except Exception:
            # Fallback to hex preview
            return value[:64].hex() + ("..." if len(value) > 64 else "")


def _format_rational(value: Any) -> Any:
    """
    Format rational(s) to a readable representation without losing information.
    """
    if isinstance(value, tuple) and len(value) == 2 and all(isinstance(x, int) for x in value):
        num, den = value
        return f"{num}/{den}" if den else str(num)
    if isinstance(value, list) and value and isinstance(value[0], tuple):
        return [_format_rational(v) for v in value]
    return value


def exif_to_readable_dict(exif: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Convert a piexif EXIF dict to a human-readable nested dict.
    """
    readable: Dict[str, Dict[str, Any]] = {}
    for ifd in ("0th", "Exif", "GPS", "1st"):
        ifd_dict = exif.get(ifd, {})
        out: Dict[str, Any] = {}
        for tag, val in ifd_dict.items():
            name = _tag_name(ifd, tag)
            if isinstance(val, bytes):
                out[name] = _decode_bytes_value(tag, val)
            else:
                out[name] = _format_rational(val)
        if exif.get("thumbnail"):
            readable["thumbnail"] = f"{len(exif['thumbnail'])} bytes"
        readable[ifd] = out
    return readable


def exif_to_pretty_text(exif: Dict[str, Any], limit_binary: bool = True) -> str:
    """
    Create a simple pretty-printed text of EXIF tags.
    """
    readable = exif_to_readable_dict(exif)
    lines: List[str] = []
    for ifd in ("0th", "Exif", "GPS", "1st"):
        lines.append(f"[{ifd}]")
        for k, v in sorted(readable.get(ifd, {}).items()):
            vs = str(v)
            if limit_binary and len(vs) > 500:
                vs = vs[:500] + "...(+truncated)"
            lines.append(f"  {k}: {vs}")
        lines.append("")
    if "thumbnail" in readable:
        lines.append(f"[thumbnail] {readable['thumbnail']}")
    return "\n".join(lines)


def exif_to_json_serializable(exif: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert EXIF to a JSON-serializable nested dict.
    """
    readable = exif_to_readable_dict(exif)
    # Already serializable as strings/ints/lists
    return readable


def remove_tags(exif: Dict[str, Any], ifd: str, tags: Iterable[int]) -> None:
    """
    Remove tags by id from a specific IFD if present.
    """
    target = exif.get(ifd, {})
    for t in tags:
        if t in target:
            target.pop(t, None)


def strip_identifying(
    exif: Dict[str, Any],
    *,
    preserve_dates: bool = True,
    anonymize_dates: bool = False,
    remove_orientation: bool = False,
) -> Dict[str, Any]:
    """
    Remove identifying metadata (author/tool/camera/GPS/etc.) while preserving technical data.
    Returns the modified EXIF dict (in-place).
    """
    exif = ensure_exif_structure(exif)

    # Remove entire GPS IFD
    exif["GPS"] = {}

    # Remove identifying tags from 0th IFD
    tags_0th_remove = {
        ImageIFD.Make,            # 271
        ImageIFD.Model,           # 272
        ImageIFD.Software,        # 305
        ImageIFD.Artist,          # 315
        ImageIFD.HostComputer,    # 316
        ImageIFD.ImageDescription,# 270
        ImageIFD.Copyright,       # 33432
    }
    # XP tags (Windows)
    tags_0th_remove |= XP_TAGS

    # Optionally remove orientation
    if remove_orientation:
        tags_0th_remove.add(ImageIFD.Orientation)

    remove_tags(exif, "0th", tags_0th_remove)

    # Remove identifying tags from Exif IFD
    tags_exif_remove = {
        ExifIFD.LensMake,         # 42035
        ExifIFD.LensModel,        # 42036
        ExifIFD.LensSerialNumber, # 42037
        ExifIFD.BodySerialNumber, # 42033
        ExifIFD.CameraOwnerName,  # 42032
        ExifIFD.MakerNote,        # 37500
        ExifIFD.UserComment,      # 37510
        ExifIFD.ImageUniqueID,    # 42016
    }
    remove_tags(exif, "Exif", tags_exif_remove)

    # Handle dates
    if anonymize_dates:
        # Replace with a generic fixed date
        generic = "2000:01:01 00:00:00"
        exif["0th"].pop(ImageIFD.DateTime, None)
        exif["Exif"].pop(ExifIFD.DateTimeOriginal, None)
        exif["Exif"].pop(ExifIFD.DateTimeDigitized, None)
        # If we want to set generic dates, uncomment below:
        # exif["0th"][ImageIFD.DateTime] = generic
        # exif["Exif"][ExifIFD.DateTimeOriginal] = generic
        # exif["Exif"][ExifIFD.DateTimeDigitized] = generic
    elif not preserve_dates:
        # Remove dates entirely
        exif["0th"].pop(ImageIFD.DateTime, None)
        exif["Exif"].pop(ExifIFD.DateTimeOriginal, None)
        exif["Exif"].pop(ExifIFD.DateTimeDigitized, None)
    # Else: preserve as-is

    # Remove thumbnail and its IFD for privacy
    exif["1st"] = {}
    exif["thumbnail"] = None

    return exif


def set_camera_make_model(
    exif: Dict[str, Any],
    *,
    make: str,
    model: str,
) -> Dict[str, Any]:
    """
    Set camera Make and Model in 0th IFD.
    """
    exif = ensure_exif_structure(exif)
    exif["0th"][ImageIFD.Make] = make
    exif["0th"][ImageIFD.Model] = model
    return exif


def apply_extended_camera_profile(
    exif: Dict[str, Any],
    *,
    profile: str,
    make: str,
    model: str,
) -> Dict[str, Any]:
    """
    Apply extended plausible camera settings.
    - FNumber: 2.8
    - ExposureTime: 1/125
    - FocalLength: 50mm
    - ISOSpeedRatings: 100
    - LensMake/LensModel per profile
    - Software: generic system (not editor)
    """
    exif = ensure_exif_structure(exif)
    # Set base camera identity
    set_camera_make_model(exif, make=make, model=model)

    # Rational values as tuples (num, den)
    exif["Exif"][ExifIFD.FNumber] = (28, 10)            # f/2.8
    exif["Exif"][ExifIFD.ExposureTime] = (1, 125)       # 1/125s
    exif["Exif"][ExifIFD.FocalLength] = (50, 1)         # 50mm
    # ISO: prefer PhotographicSensitivity if available, but piexif exposes ISOSpeedRatings
    exif["Exif"][ExifIFD.ISOSpeedRatings] = 100

    if profile.lower() == "canon":
        exif["Exif"][ExifIFD.LensMake] = "Canon"
        exif["Exif"][ExifIFD.LensModel] = "EF 50mm f/1.8"
        exif["0th"][ImageIFD.Software] = "Canon Firmware"
    elif profile.lower() == "iphone":
        exif["Exif"][ExifIFD.LensMake] = "Apple"
        exif["Exif"][ExifIFD.LensModel] = "iPhone 14 Pro back camera 24mm f/1.78"
        exif["0th"][ImageIFD.Software] = "Apple iOS"
    else:
        # Generic
        exif["0th"][ImageIFD.Software] = "Camera System"

    return exif


def get_default_camera_profile(name: Optional[str]) -> Tuple[str, str, str]:
    """
    Resolve a camera profile string into (profile_key, make, model).
    Accepts:
      - "canon"  -> ("canon", "Canon", "Canon EOS 5D Mark IV")
      - "iphone" -> ("iphone", "Apple", "iPhone 14 Pro")
      - "Brand|Model" literal -> ("custom", Brand, Model)
    Defaults to "canon" if None.
    """
    if not name or name.lower() == "canon":
        return ("canon", "Canon", "Canon EOS 5D Mark IV")
    if name.lower() == "iphone":
        return ("iphone", "Apple", "iPhone 14 Pro")
    # Custom format: "Brand|Model"
    if "|" in name:
        make, model = [p.strip() for p in name.split("|", 1)]
        return ("custom", make or "Camera", model or "Model")
    # Fallback treat as brand only
    return ("custom", name, f"{name} Camera")


def write_exif_to_image_bytes(source_path: Union[str, Path], exif: Dict[str, Any]) -> bytes:
    """
    Return bytes of the image with the given EXIF inserted. For supported formats only.
    """
    exif = ensure_exif_structure(exif)
    exif_bytes = piexif.dump(exif)
    # Read file bytes
    data = Path(source_path).read_bytes()
    # Insert using piexif
    return piexif.insert(exif_bytes, data)


def write_exif_to_file(source_path: Union[str, Path], dest_path: Union[str, Path], exif: Dict[str, Any]) -> None:
    """
    Write EXIF into a copy of source_path at dest_path using piexif.insert with output filename.
    This avoids relying on the memory-return variant and supports JPEG/TIFF/WebP reliably.
    """
    exif = ensure_exif_structure(exif)
    exif_bytes = piexif.dump(exif)
    piexif.insert(exif_bytes, str(source_path), str(dest_path))


def remove_all_exif_bytes(source_path: Union[str, Path]) -> Optional[bytes]:
    """
    Remove all EXIF from supported image and return the new bytes. None if not supported.
    """
    try:
        data = Path(source_path).read_bytes()
        return piexif.remove(data)
    except Exception as e:
        logger.debug("piexif.remove failed for %s: %s", source_path, e)
        return None


def safe_json_dumps(obj: Any) -> str:
    """
    JSON dumps with fallback conversion for non-serializable types.
    """
    def default(o: Any) -> Any:
        if isinstance(o, (bytes, bytearray)):
            try:
                return o.decode("utf-8", errors="ignore")
            except Exception:
                return f"<bytes:{len(o)}>"
        if isinstance(o, (Path,)):
            return str(o)
        return str(o)

    return json.dumps(obj, ensure_ascii=False, indent=2, default=default)
