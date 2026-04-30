"""One-shot seed script: wipe players_master, re-import from the CSV,
download photos from Google Drive links, resize via logos.process_uploaded_logo,
and store inline in BYTEA.

Run once with `python seed_players.py`.
"""
from __future__ import annotations

import re
import sys
import time
import urllib.request
from io import BytesIO

import pandas as pd

from db import create_player, get_cursor, init_schema, update_player_photo
from logos import process_uploaded_logo


CSV_PATH = "Player Registration- Auction - Form Responses 1.csv"


def gdrive_id(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/file/d/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def download_drive_image(url: str) -> bytes | None:
    gid = gdrive_id(url)
    if not gid:
        return None
    direct = f"https://drive.google.com/thumbnail?id={gid}&sz=w800"
    try:
        req = urllib.request.Request(direct, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "html" in ctype.lower() or len(data) < 1024:
                return None
            return data
    except Exception as e:
        print(f"  download failed for {gid}: {e}")
        return None


def main():
    init_schema()

    # Wipe existing
    with get_cursor() as cur:
        cur.execute("DELETE FROM players_master")
    print("cleared players_master")

    df = pd.read_csv(CSV_PATH)
    df.columns = [c.strip() for c in df.columns]

    NAME = "Name"
    EMAIL = "Email Address"
    MOBILE = "Whatsapp Number (That's added to the group)"
    IMG = "Player image (Where the face is clearly visible and it is easy for us to identify you)"
    ROLE = "Player Profile"
    STYLE = "Playing style"
    CRIC = "Cricheroes Profile Link (optional)"
    NOTE = "Want to tell captains something about your cricketing skills or experience?"

    created = 0
    with_photo = 0
    failed_photo = 0
    errors = []

    for _, r in df.iterrows():
        name = str(r.get(NAME) or "").strip()
        if not name:
            continue
        email = str(r.get(EMAIL) or "").strip() or None
        mobile = str(r.get(MOBILE) or "").strip() or None
        role = str(r.get(ROLE) or "").strip() or None

        # Collect extras into notes
        bits = []
        for label, col in [("Playing style", STYLE), ("Cricheroes", CRIC), ("Notes", NOTE)]:
            v = r.get(col)
            if pd.notna(v) and str(v).strip():
                bits.append(f"{label}: {str(v).strip()}")
        notes = "\n".join(bits) or None

        try:
            pid = create_player(
                name=name,
                mobile=mobile,
                email=email,
                role=role,
                dob=None,
                notes=notes,
            )
            created += 1
        except ValueError as ve:
            errors.append(f"{name}: {ve}")
            continue
        except Exception as ex:
            errors.append(f"{name}: {ex}")
            continue

        # Photo
        img_url = str(r.get(IMG) or "").strip()
        if img_url and "drive.google.com" in img_url:
            raw = download_drive_image(img_url)
            if raw:
                try:
                    processed, mime = process_uploaded_logo(BytesIO(raw))
                    update_player_photo(pid, processed, mime)
                    with_photo += 1
                    print(f"  ✓ {name} — {len(processed)} bytes ({mime})")
                except Exception as e:
                    failed_photo += 1
                    print(f"  × {name} — image process failed: {e}")
            else:
                failed_photo += 1
                print(f"  × {name} — download failed")
            # Be kind to Google
            time.sleep(0.2)
        elif img_url:
            print(f"  — {name} — non-Drive image ref: {img_url[:60]}")

    print(
        f"\ncreated={created}  with_photo={with_photo}  "
        f"photo_failures={failed_photo}  other_errors={len(errors)}"
    )
    for e in errors[:10]:
        print(" ", e)


if __name__ == "__main__":
    sys.exit(main())
