#!/usr/bin/env python3
"""
QRZ Callsign Lookup CLI

Looks up a single callsign on QRZ.com and displays all available
profile information in a formatted table.

Usage:
    python3 qrz.py <callsign>

Credentials are read from ~/.qrz (JSON with "login" and "api" keys).
"""

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

QRZ_XML_URL = "https://xmldata.qrz.com/xml/current/"
AGENT_NAME  = "qrz_cli_v1.0"

# Ordered list of (xml_tag, display_label) pairs
FIELDS = [
    ("call",     "Callsign"),
    ("fname",    "First Name"),
    ("name",     "Last Name"),
    ("nickname", "Nickname"),
    ("born",     "Born"),
    ("addr1",    "Address"),
    ("addr2",    "City"),
    ("state",    "State"),
    ("zip",      "Zip Code"),
    ("country",  "Country"),
    ("lat",      "Latitude"),
    ("lon",      "Longitude"),
    ("grid",     "Grid Square"),
    ("county",   "County"),
    ("cqzone",   "CQ Zone"),
    ("ituzone",  "ITU Zone"),
    ("class",    "License Class"),
    ("codes",    "License Codes"),
    ("efdate",   "Effective Date"),
    ("expdate",  "Expiration Date"),
    ("email",    "Email"),
    ("url",      "Website"),
    ("lotw",     "LoTW Member"),
    ("eqsl",     "eQSL Member"),
    ("mqsl",     "Accepts Paper QSL"),
    ("u_views",  "Profile Views"),
    ("image",    "Profile Image URL"),
    ("geoloc",   "Geo Source"),
    ("attn",     "Attention"),
]


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def load_credentials() -> tuple[str, str]:
    cred_path = Path.home() / ".qrz"
    if not cred_path.exists():
        sys.exit(f"Error: credentials file not found at {cred_path}")
    with open(cred_path) as f:
        creds = json.load(f)
    username = creds.get("login") or creds.get("username") or creds.get("email", "")
    password = creds.get("api", "")
    if not username or not password:
        sys.exit("Error: ~/.qrz must contain 'login' (or 'username'/'email') and 'api'.")
    return username, password


# ---------------------------------------------------------------------------
# QRZ helpers
# ---------------------------------------------------------------------------

def _strip_ns(xml_text: str) -> ET.Element:
    clean = re.sub(r' xmlns[^"]*"[^"]*"', "", xml_text)
    return ET.fromstring(clean)


def get_session(username: str, password: str) -> str:
    resp = requests.get(
        f"{QRZ_XML_URL}?username={username};password={password};agent={AGENT_NAME}",
        timeout=30,
    )
    resp.raise_for_status()
    root = _strip_ns(resp.text)
    key = root.find(".//Key")
    if key is not None:
        return key.text.strip()
    err = root.find(".//Error")
    sys.exit(f"QRZ auth failed: {err.text.strip() if err is not None else resp.text[:200]}")


def lookup(session_key: str, callsign: str) -> dict[str, str]:
    resp = requests.get(
        f"{QRZ_XML_URL}?s={session_key};callsign={callsign}",
        timeout=30,
    )
    resp.raise_for_status()
    root = _strip_ns(resp.text)

    err = root.find(".//Error")
    if err is not None:
        sys.exit(f"QRZ error: {err.text.strip()}")

    def text(tag: str) -> str:
        elem = root.find(f".//{tag}")
        return elem.text.strip() if elem is not None and elem.text else ""

    return {tag: text(tag) for tag, _ in FIELDS}


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------

def print_table(data: dict[str, str]) -> None:
    rows = [(label, data[tag]) for tag, label in FIELDS if data.get(tag)]
    if not rows:
        print("No data returned.")
        return

    label_w = max(len(label) for label, _ in rows)
    value_w = 54
    div = f"+{'-' * (label_w + 2)}+{'-' * (value_w + 2)}+"

    print(div)
    print(f"| {'Field':<{label_w}} | {'Value':<{value_w}} |")
    print(div)
    for label, value in rows:
        # Wrap values longer than value_w
        first = True
        while value or first:
            chunk, value = value[:value_w], value[value_w:]
            lbl = label if first else ""
            print(f"| {lbl:<{label_w}} | {chunk:<{value_w}} |")
            first = False
    print(div)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <callsign>")

    callsign = sys.argv[1].strip().upper()

    username, password = load_credentials()
    session_key = get_session(username, password)
    data = lookup(session_key, callsign)
    print_table(data)


if __name__ == "__main__":
    main()
