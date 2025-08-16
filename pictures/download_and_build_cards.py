#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download & build a ready-named PNG set from Wikimedia Commons (CC0).

Fixes 403 by sending a compliant User-Agent per:
https://meta.wikimedia.org/wiki/User-Agent_policy

Usage:
  pip install requests cairosvg
  python download_and_build_cards.py --out ./cards_png --height 300 --email you@example.com --project "24point game"
"""

import argparse
import time
import re
import sys
from pathlib import Path
from typing import Dict, Optional, List

import requests

try:
    import cairosvg
except ImportError:
    print("ERROR: cairosvg not installed. Run: pip install cairosvg", file=sys.stderr)
    sys.exit(1)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
CATEGORY_TITLE = "Category:SVG_English_pattern_playing_cards"

RANK_MAP = {
    "ace": "A", "a": "A",
    "jack": "J", "j": "J",
    "queen": "Q", "q": "Q",
    "king": "K", "k": "K",
    "2": "2","3": "3","4": "4","5":"5","6":"6",
    "7": "7","8": "8","9":"9","10":"10",
}
SUIT_MAP = {
    "spade": "S", "spades": "S",
    "heart": "H", "hearts": "H",
    "diamond": "D", "diamonds": "D",
    "club": "C", "clubs": "C",
}
VALID_CODES = {f"{r}{s}" for r in (["A"]+[str(i) for i in range(2,11)]+["J","Q","K"]) for s in "SHDC"}
TOKENIZE = re.compile(r"[A-Za-z0-9]+")

# ---- Networking helpers ----
def build_session(email: str, project: Optional[str]) -> requests.Session:
    ua = f"{(project or '24point-game')}/1.0 (contact: {email}); python-requests"
    s = requests.Session()
    s.headers.update({"User-Agent": ua})
    return s

def backoff_sleep(attempt: int):
    time.sleep(min(2 ** attempt, 10))

def req_get_json(session: requests.Session, params: Dict, max_retries: int = 5) -> Dict:
    params = dict(params)
    params.setdefault("format", "json")
    params.setdefault("origin", "*")  # CORS-friendly; harmless for server-side too
    for attempt in range(max_retries):
        r = session.get(COMMONS_API, params=params, timeout=30)
        if r.status_code in (200,):
            return r.json()
        if r.status_code in (403, 429) or 500 <= r.status_code < 600:
            backoff_sleep(attempt)
            continue
        r.raise_for_status()
    r.raise_for_status()
    return {}

def list_category_files(session: requests.Session, category: str) -> List[str]:
    titles = []
    cmcontinue = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": "file",
            "cmlimit": "500",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = req_get_json(session, params)
        members = data.get("query", {}).get("categorymembers", [])
        for m in members:
            title = m.get("title")
            if title and title.startswith("File:"):
                titles.append(title)
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    return titles

def get_original_url(session: requests.Session, file_title: str) -> Optional[str]:
    data = req_get_json(session, {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url",
    })
    pages = data.get("query", {}).get("pages", {})
    for _pid, page in pages.items():
        infos = page.get("imageinfo")
        if infos:
            return infos[0].get("url")
    return None

def download(session: requests.Session, url: str, dest: Path, max_retries: int = 5, chunk_size: int = 65536):
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(max_retries):
        r = session.get(url, stream=True, timeout=60)
        if r.status_code == 200:
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
            return
        if r.status_code in (403, 429) or 500 <= r.status_code < 600:
            backoff_sleep(attempt)
            continue
        r.raise_for_status()
    r.raise_for_status()

# ---- Parsing helpers ----
def parse_code_from_title(file_title: str) -> Optional[str]:
    base = file_title.split("File:", 1)[-1]
    base = base.rsplit(".", 1)[0]
    tokens = [t.lower() for t in TOKENIZE.findall(base)]
    rank = None
    suit = None
    for t in tokens:
        if t in RANK_MAP and rank is None:
            rank = RANK_MAP[t]
        elif t in SUIT_MAP and suit is None:
            suit = SUIT_MAP[t]
        elif t.isdigit():
            if t in [str(i) for i in range(2, 11)]:
                rank = rank or t
            elif t == "1":
                rank = rank or "A"
            elif t == "11":
                rank = rank or "J"
            elif t == "12":
                rank = rank or "Q"
            elif t == "13":
                rank = rank or "K"
    if rank and suit:
        code = f"{rank}{suit}"
        return code if code in VALID_CODES else None
    return None

def svg_to_png(svg_path: Path, png_path: Path, height: int):
    png_path.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_height=height)

# ---- Main ----
def main():
    ap = argparse.ArgumentParser(description="Download & build ready-named PNG cards from Wikimedia Commons.")
    ap.add_argument("--out", required=True, help="Output directory for PNGs")
    ap.add_argument("--height", type=int, default=300, help="PNG height (px), default 300")
    ap.add_argument("--keep-svg", action="store_true", help="Keep downloaded SVGs alongside PNGs")
    ap.add_argument("--email", required=True, help="Contact email for User-Agent (required by Wikimedia)")
    ap.add_argument("--project", default="24point-game", help="Project name in User-Agent")
    args = ap.parse_args()

    session = build_session(args.email, args.project)
    out_dir = Path(args.out)
    svg_dir = out_dir / "_svgs"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Listing files from Commons category…")
    titles = list_category_files(session, CATEGORY_TITLE)
    if not titles:
        print("ERROR: No files found in category.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(titles)} files. Downloading SVGs and converting…")

    seen_codes = set()
    for title in titles:
        code = parse_code_from_title(title)
        if not code:
            # Skip non-face files (backs/jokers) if present
            continue

        url = get_original_url(session, title)
        if not url:
            print(f"Skip (no URL): {title}")
            continue

        svg_path = svg_dir / f"{code}.svg"
        png_path = out_dir / f"{code}.png"

        if not svg_path.exists():
            try:
                download(session, url, svg_path)
            except Exception as e:
                print(f"Download failed for {title}: {e}", file=sys.stderr)
                continue

        try:
            svg_to_png(svg_path, png_path, args.height)
        except Exception as e:
            print(f"SVG->PNG failed for {svg_path.name}: {e}", file=sys.stderr)
            continue

        seen_codes.add(code)
        print(f"{code:4}  {title}  ->  {png_path.name}")
        time.sleep(0.3)  # be polite

    if not args.keep_svg and svg_dir.exists():
        for p in svg_dir.glob("*.svg"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            svg_dir.rmdir()
        except Exception:
            pass

    print("\nSummary")
    print(f"  Generated: {len(seen_codes)} / 52 PNGs at height {args.height}px")
    missing = sorted(list(VALID_CODES - seen_codes))
    if missing:
        print("  Missing (not found or failed):", ", ".join(missing))
        print("  Tip: re-run; if still missing, tell me and I’ll adjust parsing or fetch from an alternate CC0 set.")
    else:
        print("  All 52 cards generated ✔")

if __name__ == "__main__":
    main()

