#!/usr/bin/env python3
"""
QRZ Ham Radio Lookup by Zip Code

Fetches the FCC amateur radio licensee database (EN.dat only, via HTTP range
requests to avoid downloading the full 173 MB ZIP), filters by zip code, then
looks up each callsign on QRZ.com to get profile view counts.

Usage:
    python3 qrz_lookup.py <zipcode>

Credentials are read from ~/.qrz  (JSON with "login" and "api" keys).
EN.dat is cached at ~/.cache/qrz/en_dat.gz for CACHE_AGE_DAYS days.
"""

import csv
import gzip
import io
import json
import struct
import sys
import time
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QRZ_XML_URL   = "https://xmldata.qrz.com/xml/current/"
FCC_AMAT_ZIP  = "https://data.fcc.gov/download/pub/uls/complete/l_amat.zip"
AGENT_NAME    = "qrz_zip_lookup_v1.0"
CACHE_DIR     = Path.home() / ".cache" / "qrz"
EN_DAT_CACHE  = CACHE_DIR / "en_dat.gz"
CACHE_AGE_DAYS = 7
QRZ_DELAY     = 0.1   # seconds between QRZ lookups


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def load_credentials() -> tuple[str, str]:
    """
    Return (username, password) from ~/.qrz.

    Accepts "login", "username", or "email" as the QRZ login name.
    The password is read from the "api" key.

    Example ~/.qrz:
        { "login": "N1JFU", "api": "your_qrz_password" }
    """
    cred_path = Path.home() / ".qrz"
    if not cred_path.exists():
        sys.exit(f"Error: credentials file not found at {cred_path}")
    with open(cred_path) as f:
        creds = json.load(f)
    username = creds.get("login") or creds.get("username") or creds.get("email", "")
    password = creds.get("api", "")
    if not username or not password:
        sys.exit(
            "Error: ~/.qrz must contain 'login' (or 'username'/'email') and 'api'.\n"
            "The QRZ XML API uses your callsign/login and requires a subscription."
        )
    return username, password


# ---------------------------------------------------------------------------
# QRZ XML helpers
# ---------------------------------------------------------------------------

def _strip_ns(xml_text: str) -> ET.Element:
    """Parse XML, stripping default namespace so .find() works without prefixes."""
    import re
    clean = re.sub(r' xmlns[^"]*"[^"]*"', "", xml_text)
    return ET.fromstring(clean)


def get_qrz_session(username: str, password: str) -> str:
    """Authenticate with QRZ XML API and return the session key."""
    query = f"username={username};password={password};agent={AGENT_NAME}"
    resp = requests.get(f"{QRZ_XML_URL}?{query}", timeout=30)
    resp.raise_for_status()

    root = _strip_ns(resp.text)
    key_elem = root.find(".//Key")
    if key_elem is not None:
        return key_elem.text.strip()

    error_elem = root.find(".//Error")
    if error_elem is not None:
        sys.exit(f"QRZ authentication failed: {error_elem.text.strip()}")

    sys.exit(f"QRZ authentication failed: unexpected response\n{resp.text[:500]}")


def lookup_qrz(session_key: str, callsign: str) -> dict | None:
    """
    Fetch a callsign record from QRZ.  Returns a dict with keys
    'callsign', 'zip', 'views', or None if not found.
    """
    query = f"s={session_key};callsign={callsign}"
    try:
        resp = requests.get(f"{QRZ_XML_URL}?{query}", timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    root = _strip_ns(resp.text)
    if root.find(".//Error") is not None:
        return None

    def text(tag: str) -> str:
        elem = root.find(f".//{tag}")
        return elem.text.strip() if elem is not None and elem.text else ""

    return {
        "callsign": text("call") or callsign,
        "zip":      text("zip"),
        "views":    text("u_views") or "0",
    }


# ---------------------------------------------------------------------------
# FCC bulk-ZIP range-request reader
# ---------------------------------------------------------------------------

def _range_get(session: requests.Session, url: str, start: int, end: int) -> bytes:
    """HTTP range request returning bytes start..end inclusive."""
    resp = session.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=120)
    resp.raise_for_status()
    return resp.content


def _get_zip_entry_map(session: requests.Session, url: str) -> dict[str, tuple]:
    """
    Read the ZIP central directory via two range requests.
    Returns {filename: (local_offset, comp_size, uncomp_size, method)}.
    """
    # Get file size from HEAD
    head = session.head(url, timeout=30)
    head.raise_for_status()
    file_size = int(head.headers["Content-Length"])

    # Download the last 65 557 bytes to find EOCD
    fetch_size = min(65557, file_size)
    tail = _range_get(session, url, file_size - fetch_size, file_size - 1)

    eocd_sig = b"PK\x05\x06"
    pos = len(tail) - 22
    while pos >= 0:
        if tail[pos : pos + 4] == eocd_sig:
            break
        pos -= 1
    if pos < 0:
        raise ValueError("ZIP EOCD signature not found")

    _, _, _, _, _, cd_size, cd_offset, _ = struct.unpack_from("<4sHHHHIIH", tail, pos)

    # Download central directory
    cd = _range_get(session, url, cd_offset, cd_offset + cd_size - 1)

    entries: dict[str, tuple] = {}
    cpos = 0
    cd_sig = b"PK\x01\x02"

    while cpos + 46 <= len(cd):
        if cd[cpos : cpos + 4] != cd_sig:
            break
        (_, _, _, _, method, _, _, _, comp_size, uncomp_size,
         fname_len, extra_len, comment_len, _, _, _, local_offset) = struct.unpack_from(
            "<4sHHHHHHIIIHHHHHII", cd, cpos
        )
        fname = cd[cpos + 46 : cpos + 46 + fname_len].decode("utf-8", errors="replace")
        entries[fname] = (local_offset, comp_size, uncomp_size, method)
        cpos += 46 + fname_len + extra_len + comment_len

    return entries


def _download_zip_entry(
    session: requests.Session,
    url: str,
    local_offset: int,
    comp_size: int,
    method: int,
) -> bytes:
    """Download and decompress one entry from the remote ZIP."""
    # Read local file header (30 bytes) to find actual data offset
    lh = _range_get(session, url, local_offset, local_offset + 29)
    fname_len  = struct.unpack_from("<H", lh, 26)[0]
    extra_len  = struct.unpack_from("<H", lh, 28)[0]
    data_start = local_offset + 30 + fname_len + extra_len

    comp_data = _range_get(session, url, data_start, data_start + comp_size - 1)

    if method == 0:    # Stored
        return comp_data
    if method == 8:    # Deflate
        return zlib.decompress(comp_data, -15)
    raise ValueError(f"Unsupported ZIP compression method: {method}")


# ---------------------------------------------------------------------------
# EN.dat caching and parsing
# ---------------------------------------------------------------------------

def get_en_dat(session: requests.Session) -> bytes:
    """
    Return the decompressed content of EN.dat from the FCC amateur radio ZIP.
    Uses a local gzip cache (CACHE_AGE_DAYS); only EN.dat is downloaded
    (not the entire 173 MB ZIP file).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if EN_DAT_CACHE.exists():
        age_days = (time.time() - EN_DAT_CACHE.stat().st_mtime) / 86400
        if age_days < CACHE_AGE_DAYS:
            with gzip.open(EN_DAT_CACHE, "rb") as f:
                return f.read()
        print(f"Cache is {age_days:.0f} days old — refreshing FCC data…")

    print("Reading FCC ZIP central directory…")
    entries = _get_zip_entry_map(session, FCC_AMAT_ZIP)

    en_key = next(
        (k for k in entries if k.upper().endswith("EN.DAT")), None
    )
    if not en_key:
        sys.exit("Error: EN.dat not found inside FCC ZIP")

    local_offset, comp_size, uncomp_size, method = entries[en_key]
    print(
        f"Downloading EN.dat "
        f"({comp_size / 1_048_576:.1f} MB compressed → "
        f"{uncomp_size / 1_048_576:.1f} MB uncompressed)…"
    )

    data = _download_zip_entry(session, FCC_AMAT_ZIP, local_offset, comp_size, method)

    with gzip.open(EN_DAT_CACHE, "wb") as f:
        f.write(data)
    print("FCC data cached.")
    return data


def get_callsigns_by_zip(zipcode: str, en_dat: bytes) -> list[str]:
    """
    Parse EN.dat and return callsigns whose zip code starts with `zipcode`.

    EN.dat is pipe-delimited:
      field 0  = record type (EN)
      field 4  = call sign
      field 18 = zip code
    """
    target = zipcode[:5]
    callsigns: list[str] = []
    seen: set[str] = set()

    for line in en_dat.decode("latin-1").splitlines():
        if not line.startswith("EN|"):
            continue
        parts = line.split("|")
        if len(parts) <= 18:
            continue
        call = parts[4].strip().upper()
        zip5 = parts[18].strip()[:5]
        if call and zip5 == target and call not in seen:
            seen.add(call)
            callsigns.append(call)

    return callsigns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <zipcode>")

    zipcode = sys.argv[1].strip()
    output_file = f"ham_operators_{zipcode}.csv"

    session = requests.Session()

    print("Loading credentials from ~/.qrz …")
    username, password = load_credentials()

    print("Authenticating with QRZ.com …")
    session_key = get_qrz_session(username, password)
    print("Session established.")

    en_dat = get_en_dat(session)

    print(f"Searching FCC database for zip code {zipcode} …")
    callsigns = get_callsigns_by_zip(zipcode, en_dat)
    if not callsigns:
        print("No amateur radio operators found for that zip code.")
        sys.exit(0)
    print(f"Found {len(callsigns)} operator(s).")

    print("Looking up QRZ profiles …")
    width = len(str(len(callsigns)))
    rows: list[tuple[str, str]] = []
    seen_calls: set[str] = set()
    for i, callsign in enumerate(callsigns, 1):
        print(f"  [{i:>{width}}/{len(callsigns)}] {callsign:<10}", end="\r")
        record = lookup_qrz(session_key, callsign)
        if record:
            call = record["callsign"]
            if call not in seen_calls:
                seen_calls.add(call)
                rows.append((call, record["views"]))
        time.sleep(QRZ_DELAY)

    rows.sort(key=lambda r: int(r[1]), reverse=True)

    if Path(output_file).exists():
        Path(output_file).unlink()
        print(f"\nDeleted existing {output_file}.")

    print(f"Writing {output_file} …")
    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Callsign", "Profile Views"])
        writer.writerows(rows)

    print(f"Done. {len(rows)} record(s) written to {output_file}.")


if __name__ == "__main__":
    main()
