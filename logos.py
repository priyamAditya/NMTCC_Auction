"""Logo processing + rendering helpers.

Uploaded logos are resized to a sensible max and stored as bytea in Postgres.
Rendering in the UI uses data URIs so we don't need a separate image endpoint.
"""
from __future__ import annotations

import base64
from io import BytesIO
from typing import Optional

from PIL import Image

MAX_DIM = 256


def process_uploaded_logo(uploaded_file) -> tuple[bytes, str]:
    """Resize to fit within MAX_DIM x MAX_DIM and return (bytes, mime)."""
    img = Image.open(uploaded_file)
    img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
    out = BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        img.save(out, format="PNG", optimize=True)
        return out.getvalue(), "image/png"
    img = img.convert("RGB")
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue(), "image/jpeg"


def logo_data_uri(logo_bytes, logo_mime: Optional[str]) -> Optional[str]:
    if not logo_bytes:
        return None
    if isinstance(logo_bytes, memoryview):
        logo_bytes = bytes(logo_bytes)
    mime = logo_mime or "image/png"
    return f"data:{mime};base64,{base64.b64encode(logo_bytes).decode('ascii')}"


def avatar_html(
    team_name: str,
    logo_bytes,
    logo_mime: Optional[str],
    bg: str,
    fg: str,
    size_px: int = 44,
) -> str:
    """Inline HTML for a team avatar — logo image if present, initials fallback."""
    uri = logo_data_uri(logo_bytes, logo_mime)
    if uri:
        return (
            f"<img src='{uri}' "
            f"style='width:{size_px}px; height:{size_px}px; border-radius:10px; "
            f"object-fit:cover; background:{bg};' alt='' />"
        )
    initial = (team_name[:1] or "?").upper()
    return (
        f"<div style='width:{size_px}px; height:{size_px}px; border-radius:10px; "
        f"background:{bg}; color:{fg}; display:flex; align-items:center; "
        f"justify-content:center; font-weight:800; font-size:{max(12, size_px // 2)}px;'>"
        f"{initial}</div>"
    )
