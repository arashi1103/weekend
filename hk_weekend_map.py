#!/usr/bin/env python3
"""
HK Weekend Arts Activities Map Generator
Scrapes art-mate.net, timable.com, and xplorehk.com for the upcoming weekend
and generates an interactive HTML map.

Usage:
    python3 hk_weekend_map.py              # auto-detect next weekend
    python3 hk_weekend_map.py --sat 20260613 --sun 20260614
    python3 hk_weekend_map.py --out ~/Desktop/hk_weekend_map.html
"""

import re
import sys
import json
import gzip
import time
import argparse
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Tuple, List, Dict

# ── Config ─────────────────────────────────────────────────────────────────────
BASE        = "https://www.art-mate.net"
OUT_FILE    = Path.home() / "Desktop" / "hk_weekend_map.html"
MAX_WORKERS = 15
PAGE_DELAY  = 0.15
HEADERS     = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# Full browser headers required by timable.com (no brotli — stdlib can't decode it)
TIMABLE_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-HK,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",   # NO br — brotli garbles without third-party lib
}

# XploreHK Google Sheets config (public sheet + public API key)
XPLOREHK_SHEET_ID = "1G_8RMWjf0T9sNdMxKYy_Fc051I6zhdLLy6ehLak4CX4"
XPLOREHK_KEY      = "AIzaSyCPyerGljBK4JJ-XA3aRr5cRvWssI3rwhI"

# ── Known venue coordinates ─────────────────────────────────────────────────────
KNOWN_VENUES = [
    # West Kowloon Cultural District
    ("戲曲中心",           22.3053, 114.1610),
    ("xiqu centre",        22.3053, 114.1610),
    ("自由空間",           22.3040, 114.1590),
    ("freespace",          22.3040, 114.1590),
    ("西九文化區",         22.3033, 114.1601),
    ("west kowloon",       22.3033, 114.1601),
    # Tsim Sha Tsui
    ("香港文化中心",       22.2943, 114.1705),
    ("cultural centre",    22.2943, 114.1705),
    ("太空館",             22.2959, 114.1710),
    ("香港藝術館",         22.2963, 114.1721),
    ("museum of art",      22.2963, 114.1721),
    ("柯士甸道",           22.3009, 114.1670),
    ("austin road",        22.3009, 114.1670),
    ("尖沙咀",             22.2980, 114.1718),
    ("tsim sha tsui",      22.2980, 114.1718),
    # Central / Sheung Wan
    ("pmq",                22.2821, 114.1516),
    ("元創方",             22.2821, 114.1516),
    ("大館",               22.2800, 114.1556),
    ("tai kwun",           22.2800, 114.1556),
    ("藝穗會",             22.2817, 114.1568),
    ("fringe club",        22.2817, 114.1568),
    ("奶庫",               22.2817, 114.1568),
    ("香港大會堂",         22.2826, 114.1668),
    ("city hall",          22.2826, 114.1668),
    ("中環",               22.2830, 114.1580),
    ("central",            22.2830, 114.1580),
    ("上環",               22.2856, 114.1499),
    ("sheung wan",         22.2856, 114.1499),
    # Wan Chai
    ("香港藝術中心",       22.2799, 114.1718),
    ("hong kong arts centre", 22.2799, 114.1718),
    ("壽臣劇院",           22.2799, 114.1718),
    ("shouson",            22.2799, 114.1718),
    ("灣仔",               22.2780, 114.1720),
    ("wan chai",           22.2780, 114.1720),
    # Causeway Bay
    ("銅鑼灣",             22.2810, 114.1842),
    ("causeway bay",       22.2810, 114.1842),
    ("維多利亞公園",       22.2839, 114.1877),
    # Performing arts
    ("香港演藝學院",       22.2786, 114.1742),
    ("演藝學院",           22.2786, 114.1742),
    ("hkapa",              22.2786, 114.1742),
    ("香港體育館",         22.3033, 114.1840),
    ("紅館",               22.3033, 114.1840),
    ("紅磡",               22.3040, 114.1830),
    ("hung hom",           22.3040, 114.1830),
    # To Kwa Wan
    ("牛棚",               22.3222, 114.1912),
    ("cattle depot",       22.3222, 114.1912),
    ("馬頭角",             22.3222, 114.1912),
    # Kowloon City
    ("九龍城",             22.3280, 114.1910),
    ("kowloon city",       22.3280, 114.1910),
    # Sham Shui Po
    ("兆基創意書院",       22.3324, 114.1558),
    ("hkicc",              22.3324, 114.1558),
    ("深水埗",             22.3280, 114.1613),
    ("sham shui po",       22.3280, 114.1613),
    # Shek Kip Mei
    ("賽馬會創意藝術中心", 22.3347, 114.1685),
    ("jccac",              22.3347, 114.1685),
    ("石硤尾",             22.3345, 114.1695),
    # Mong Kok / Yau Ma Tei
    ("旺角",               22.3190, 114.1694),
    ("mong kok",           22.3190, 114.1694),
    ("油麻地",             22.3130, 114.1700),
    ("yau ma tei",         22.3130, 114.1700),
    # San Po Kong / Kowloon East
    ("同德工業大廈",       22.3390, 114.2082),
    ("雙喜街",             22.3390, 114.2082),
    ("新蒲崗",             22.3390, 114.2082),
    ("san po kong",        22.3390, 114.2082),
    ("東九文化中心",       22.3279, 114.2043),
    ("east kowloon cultural", 22.3279, 114.2043),
    ("觀塘",               22.3124, 114.2249),
    ("kwun tong",          22.3124, 114.2249),
    ("九龍灣",             22.3250, 114.2100),
    ("kowloon bay",        22.3250, 114.2100),
    ("啟德",               22.3288, 114.2028),
    ("kai tak",            22.3288, 114.2028),
    # Wong Tai Sin
    ("黃大仙",             22.3413, 114.1933),
    ("wong tai sin",       22.3413, 114.1933),
    # Tsuen Wan
    ("荃灣大會堂",         22.3715, 114.1178),
    ("tsuen wan town hall", 22.3715, 114.1178),
    ("南豐紗廠",           22.3714, 114.1128),
    ("chat六廠",           22.3714, 114.1128),
    ("chat 六廠",          22.3714, 114.1128),
    ("六廠",               22.3714, 114.1128),
    ("荃灣",               22.3705, 114.1185),
    ("tsuen wan",          22.3705, 114.1185),
    # Sha Tin
    ("沙田大會堂",         22.3810, 114.1874),
    ("sha tin town hall",  22.3810, 114.1874),
    ("沙田",               22.3832, 114.1877),
    ("sha tin",            22.3832, 114.1877),
    # Yuen Long
    ("元朗劇院",           22.4450, 114.0235),
    ("yuen long theatre",  22.4450, 114.0235),
    ("錦上路",             22.4467, 114.0604),
    ("kam sheung",         22.4467, 114.0604),
    ("元朗",               22.4420, 114.0220),
    ("yuen long",          22.4420, 114.0220),
    ("天水圍",             22.4490, 114.0080),
    ("tin shui wai",       22.4490, 114.0080),
    # Tai Po
    ("大埔文娛中心",       22.4503, 114.1651),
    ("大埔藝術中心",       22.4501, 114.1668),
    ("tai po arts centre", 22.4501, 114.1668),
    ("tai po community",   22.4503, 114.1651),
    ("大埔",               22.4500, 114.1640),
    ("tai po",             22.4500, 114.1640),
    # Other NT
    ("馬鞍山",             22.4248, 114.2316),
    ("ma on shan",         22.4248, 114.2316),
    ("上水",               22.5020, 114.1200),
    ("sheung shui",        22.5020, 114.1200),
    ("屯門",               22.3936, 113.9768),
    ("tuen mun",           22.3936, 113.9768),
    ("將軍澳",             22.3079, 114.2577),
    ("tseung kwan o",      22.3079, 114.2577),
    ("西貢",               22.3815, 114.2714),
    ("sai kung",           22.3815, 114.2714),
    # Islands
    ("南丫",               22.2142, 114.1313),
    ("lamma",              22.2142, 114.1313),
    ("長洲",               22.2070, 114.0276),
    ("cheung chau",        22.2070, 114.0276),
    ("東涌",               22.2895, 113.9445),
    ("tung chung",         22.2895, 113.9445),
    ("大嶼山",             22.2650, 113.9460),
    ("lantau",             22.2650, 113.9460),
    # TST East / hotels
    ("hotel stage",        22.2970, 114.1778),
    ("the muse",           22.2970, 114.1778),
    ("尖東",               22.2972, 114.1748),
    ("tsim sha tsui east", 22.2972, 114.1748),
    # AsiaWorld-Arena / HKIA area
    ("asiaworld",          22.3098, 113.9347),
    ("亞洲國際博覽館",     22.3098, 113.9347),
    ("機場博覽館",         22.3098, 113.9347),
    # Gallery spaces & museums
    ("m+ 戲院",            22.3030, 114.1582),
    ("m+",                 22.3030, 114.1582),
    ("hart haus",          22.3714, 114.1128),
    ("vA!",                22.2826, 114.1668),
    ("parasite",           22.2830, 114.1555),
    ("hanart",             22.2826, 114.1668),
    ("scad",               22.2800, 114.1556),
    ("k11",                22.2987, 114.1720),
    ("roommate",           22.2830, 114.1580),
    ("尋樂",               22.3347, 114.1685),
    # Sports halls
    ("東蒲",               22.3222, 114.1912),
    ("李名靜體育館",       22.3222, 114.1912),
    # North District
    ("粉嶺",               22.4940, 114.1390),
    ("fanling",            22.4940, 114.1390),
    ("古洞",               22.5000, 114.1050),
    # Sai Wan Ho / Shau Kei Wan
    ("西灣河文娛中心",     22.2773, 114.2239),
    ("西灣河",             22.2773, 114.2239),
    ("sai wan ho",         22.2773, 114.2239),
    # Hong Kong Film Archive
    ("電影資料館",         22.2812, 114.2260),
    ("film archive",       22.2812, 114.2260),
    # Yau Tong / Kwun Tong east
    ("油塘",               22.3056, 114.2372),
    ("yau tong",           22.3056, 114.2372),
    ("大本型",             22.3056, 114.2372),
    # City University / Run Run Shaw
    ("run run shaw",       22.3373, 114.1724),
    ("creative media",     22.3373, 114.1724),
    ("city university",    22.3373, 114.1724),
    ("城市大學",           22.3373, 114.1724),
    # Extra venues for xplorehk coverage
    ("赤柱",               22.2189, 114.2094),
    ("stanley",            22.2189, 114.2094),
    ("數碼港",             22.2627, 114.1295),
    ("cyberport",          22.2627, 114.1295),
    ("香港海事博物館",     22.2826, 114.1668),
    ("海事博物館",         22.2826, 114.1668),
    ("薄扶林",             22.2693, 114.1327),
    ("pok fu lam",         22.2693, 114.1327),
    ("牛池灣",             22.3400, 114.2222),
    ("kowloon east",       22.3279, 114.2043),
    ("炮台山",             22.2852, 114.1934),
    ("fortress hill",      22.2852, 114.1934),
    ("土瓜灣",             22.3150, 114.1916),
    ("to kwa wan",         22.3150, 114.1916),
    ("佐敦",               22.3055, 114.1694),
    ("jordan",             22.3055, 114.1694),
    ("西營盤",             22.2862, 114.1434),
    ("sai ying pun",       22.2862, 114.1434),
]


# HK bounding box – anything outside this is rejected
_HK = dict(lat_min=22.13, lat_max=22.57, lng_min=113.82, lng_max=114.44)

def in_hk(lat, lng):
    return (_HK["lat_min"] <= lat <= _HK["lat_max"] and
            _HK["lng_min"] <= lng <= _HK["lng_max"])


# ── HTTP helpers ────────────────────────────────────────────────────────────────

def fetch(url, retries=3):
    """Simple fetch with basic User-Agent header."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ✗ fetch failed: {url}  ({e})", file=sys.stderr)
            time.sleep(1 + attempt)
    return None


def fetch_gzip(url, retries=3):
    """Fetch with full browser headers; handles gzip response (for timable)."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=TIMABLE_HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
                enc = r.info().get("Content-Encoding", "")
                if enc == "gzip":
                    return gzip.decompress(raw).decode("utf-8", errors="replace")
                return raw.decode("utf-8", errors="replace")
        except Exception as e:
            if attempt == retries - 1:
                print(f"  ✗ fetch_gzip failed: {url}  ({e})", file=sys.stderr)
            time.sleep(1 + attempt)
    return None


# ── Date helpers ────────────────────────────────────────────────────────────────

def upcoming_weekend():
    today = datetime.now()
    dow = today.weekday()   # Mon=0 … Sat=5, Sun=6
    # On Sat/Sun show the current weekend; Mon-Fri show the coming one
    if dow == 5:    days_to_sat = 0
    elif dow == 6:  days_to_sat = -1
    else:           days_to_sat = 5 - dow
    sat = today + timedelta(days=days_to_sat)
    sun = sat + timedelta(days=1)
    return sat.strftime("%Y%m%d"), sun.strftime("%Y%m%d")


# ── Art-mate scraper ─────────────────────────────────────────────────────────────

def get_max_page(html):
    nums = [int(x) for x in re.findall(r"page=(\d+)", html)]
    return max(nums) if nums else 1


SKIP_TITLES = {"報名", "購票", "查看", "立即報名", "立即購票", "登記"}

def extract_activities_from_page(html):
    seen = set()
    out = []
    for doc_id, title in re.findall(
        r"href='https://www\.art-mate\.net/doc/(\d+)[^']*' title='([^']+)'", html
    ):
        if doc_id not in seen and title not in SKIP_TITLES:
            seen.add(doc_id)
            out.append((doc_id, title))
    return out


def scrape_all_activities(date_str):
    """Scrape all listing pages for a date. Returns {doc_id: title}."""
    print(f"    Scraping art-mate listing pages for {date_str}…")
    first_url = f"{BASE}/group/hk_coming_performance?period={date_str}&page=1"
    first_html = fetch(first_url)
    if not first_html:
        return {}

    max_page = get_max_page(first_html)
    print(f"      Found {max_page} pages")

    all_ids = {}
    for doc_id, title in extract_activities_from_page(first_html):
        all_ids.setdefault(doc_id, title)

    for page in range(2, max_page + 1):
        url = f"{BASE}/group/hk_coming_performance?period={date_str}&page={page}"
        html = fetch(url)
        if html:
            for doc_id, title in extract_activities_from_page(html):
                all_ids.setdefault(doc_id, title)
        time.sleep(PAGE_DELAY)

    print(f"      Total unique activities: {len(all_ids)}")
    return all_ids


def parse_detail(html, target_dates):
    vm = re.search(
        r"venue_icon[^>]*>.*?</span><span[^>]*><a href='(/doc/\d+\?name=[^']+)'>([^<]+)</a>",
        html, re.S
    )
    venue_name = vm.group(2).strip() if vm else None
    all_slots = re.findall(
        r"dx_cell_wf1 dx_fs10 dx_lh15'>(\d{4}-\d{2}-\d{2}[^<]*)</span>", html
    )
    relevant = [s.strip() for s in all_slots if any(d in s for d in target_dates)]
    return {"venue_name": venue_name, "schedule": relevant}


def fetch_all_details(doc_ids, target_dates):
    """Parallel-fetch art-mate detail pages."""
    print(f"    Fetching {len(doc_ids)} detail pages…")
    results = {}

    def worker(doc_id, title):
        url = f"{BASE}/doc/{doc_id}"
        html = fetch(url)
        if not html:
            return doc_id, {"title": title, "venue_name": None, "schedule": []}
        detail = parse_detail(html, target_dates)
        detail["title"] = title
        return doc_id, detail

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(worker, doc_id, title): doc_id
                   for doc_id, title in doc_ids.items()}
        done = 0
        for fut in as_completed(futures):
            doc_id, info = fut.result()
            results[doc_id] = info
            done += 1
            if done % 50 == 0:
                print(f"      …{done}/{len(doc_ids)} detail pages fetched")

    return results


# ── Timable scraper ──────────────────────────────────────────────────────────────

def _extract_timable_docs(html):
    """Extract the embedded docs JSON array from a timable page."""
    m = re.search(r'"docs":\[', html)
    if not m:
        return []
    start = m.end() - 1  # position of '['
    depth = 0
    for i in range(start, min(start + 1_000_000, len(html))):
        c = html[i]
        if c == '[':
            depth += 1
        elif c == ']':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except json.JSONDecodeError:
                    return []
    return []


def _timable_section_on_date(section, target_date_str):
    """
    Check if a timable event section covers target_date_str (YYYY-MM-DD).
    Returns (on_date: bool, time_str: str|None).
    """
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

    def parse_hkt(s):
        s = re.sub(r"\.\d+Z?$", "", s.rstrip("Z"))
        return datetime.fromisoformat(s) + timedelta(hours=8)

    try:
        start_hkt = parse_hkt(section["startDatetime"])
    except (KeyError, ValueError):
        return False, None

    start_date = start_hkt.date()
    is_repeat  = section.get("repeat", False)
    to_this    = section.get("toThisDay")
    end_str    = section.get("endDatetime")

    if is_repeat and to_this:
        try:
            end_date = parse_hkt(to_this).date()
        except ValueError:
            return False, None
        if not (start_date <= target_date <= end_date):
            return False, None
        weekdays = section.get("recurrance", {}).get("weekday", [])
        if weekdays:
            if target_date.strftime("%A").lower() not in weekdays:
                return False, None
    elif end_str:
        try:
            end_date = parse_hkt(end_str).date()
        except ValueError:
            return False, None
        if not (start_date <= target_date <= end_date):
            return False, None
    else:
        if start_date != target_date:
            return False, None

    # Format display time
    if section.get("fullDay"):
        time_str = "全日活動"
    else:
        time_str = start_hkt.strftime("%H:%M")
        if end_str:
            try:
                time_str += "–" + parse_hkt(end_str).strftime("%H:%M")
            except ValueError:
                pass

    return True, time_str


def scrape_timable(sat_iso, sun_iso):
    """
    Scrape all pages of timable.com for the target weekend.
    Returns list of activity dicts ready for build_venues.
    """
    print("  Scraping timable.com…")
    base_tpl = (
        "https://timable.com/hk/zh/event"
        f"?time={sat_iso}%2C{sun_iso}&audience=&district=&category="
        "&page={page}&limit=12"
    )

    page1 = fetch_gzip(base_tpl.format(page=1))
    if not page1:
        print("  ✗ Could not reach timable.com", file=sys.stderr)
        return []

    m = re.search(r'"totalPages":(\d+)', page1)
    total_pages = int(m.group(1)) if m else 1
    print(f"    timable: {total_pages} pages")

    all_docs = _extract_timable_docs(page1)
    for page in range(2, total_pages + 1):
        html = fetch_gzip(base_tpl.format(page=page))
        if html:
            all_docs.extend(_extract_timable_docs(html))
        time.sleep(PAGE_DELAY)

    print(f"    timable: {len(all_docs)} events fetched")

    acts = []
    seen = set()  # deduplicate by (permalink, sat, sun)

    for doc in all_docs:
        name      = doc.get("name", "").strip()
        permalink = doc.get("permalink", "")
        if not name or not permalink:
            continue
        url = f"https://timable.com/hk/zh/event/{urllib.parse.quote(permalink, safe='')}"
        cat_items = [c.get("name", "") for c in (doc.get("categories") or []) if isinstance(c, dict)]
        category  = ", ".join(filter(None, cat_items))

        for section in doc.get("sections", []):
            coord = section.get("coordinate")   # [lng, lat]
            if not coord or len(coord) < 2:
                continue
            lng, lat = float(coord[0]), float(coord[1])
            venue_name = (section.get("location") or {}).get("name", "") or ""
            address    = section.get("address", "") or ""

            on_sat, sat_time = _timable_section_on_date(section, sat_iso)
            on_sun, sun_time = _timable_section_on_date(section, sun_iso)
            if not on_sat and not on_sun:
                continue

            key = (event_id or permalink, on_sat, on_sun)
            if key in seen:
                continue
            seen.add(key)

            acts.append({
                "title":      name,
                "url":        url,
                "lat":        lat,
                "lng":        lng,
                "venue_name": venue_name or address[:40] or "(未知地點)",
                "on_sat":     on_sat,
                "on_sun":     on_sun,
                "sat_times":  [sat_time or "Available this weekend"] if on_sat else [],
                "sun_times":  [sun_time or "Available this weekend"] if on_sun else [],
                "source":     "timable.com",
                "category":   category,
            })

    print(f"    timable activities on target weekend: {len(acts)}")
    return acts


# ── XploreHK scraper ─────────────────────────────────────────────────────────────

def _parse_xplorehk_dates(date_str, sat_dt, sun_dt):
    """
    Parse xplorehk date field (D/M or ranges/lists) against target weekend.
    Returns (on_sat: bool, on_sun: bool).
    """
    if not date_str or date_str.strip() in ("N/A", ""):
        return False, False

    year = sat_dt.year

    def dm_to_date(s):
        s = re.sub(r"^till\s*", "", s.strip(), flags=re.I)
        m = re.match(r"^(\d{1,2})/(\d{1,2})$", s)
        if not m:
            return None
        try:
            return datetime(year, int(m.group(2)), int(m.group(1))).date()
        except ValueError:
            return None

    on_sat = on_sun = False
    for part in re.split(r"[,，]", date_str):
        part = part.strip()
        rm = re.match(r"^(\d{1,2}/\d{1,2})-(\d{1,2}/\d{1,2})$", part)
        if rm:
            s = dm_to_date(rm.group(1))
            e = dm_to_date(rm.group(2))
            if s and e:
                if s <= sat_dt <= e: on_sat = True
                if s <= sun_dt <= e: on_sun = True
        else:
            dt = dm_to_date(part)
            if dt:
                if dt == sat_dt: on_sat = True
                if dt == sun_dt: on_sun = True

    return on_sat, on_sun


def scrape_xplorehk(sat_iso, sun_iso):
    """
    Scrape xplorehk.com via Google Sheets API and event.txt.
    Returns list of activity dicts ready for build_venues.
    """
    print("  Scraping xplorehk.com…")
    sat_dt = datetime.strptime(sat_iso, "%Y-%m-%d").date()
    sun_dt = datetime.strptime(sun_iso, "%Y-%m-%d").date()
    acts   = []

    def fetch_sheet(sheet_name):
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/"
            f"{XPLOREHK_SHEET_ID}/values/{urllib.parse.quote(sheet_name)}/"
            f"?key={XPLOREHK_KEY}"
        )
        raw = fetch(url)
        if not raw:
            return []
        try:
            return json.loads(raw).get("values", [])
        except Exception:
            return []

    def clean_time(t):
        return t if t and t.strip() not in ("N/A", "") else "Available this weekend"

    # ── Event(new) sheet ──
    # Cols: Available, Cost, Event name, Category, Cat2, Organizer, Link,
    #       Date, Beginning Date, (empty), Time, Location, Photo, Area
    event_rows = fetch_sheet("Event(new)")
    print(f"    xplorehk Event(new): {len(event_rows)} rows")
    event_count = 0
    for row in event_rows[1:]:
        if len(row) < 8:
            continue
        if row[0] != "Y":
            continue
        title    = row[2].strip() if len(row) > 2 else ""
        if not title:
            continue
        link     = row[6].strip()  if len(row) > 6 else ""
        date_str = row[7].strip()  if len(row) > 7 else ""
        time_str = row[10].strip() if len(row) > 10 else ""
        location = row[11].strip() if len(row) > 11 else ""
        cat1     = row[3].strip()  if len(row) > 3  else ""
        cat2     = row[4].strip()  if len(row) > 4  else ""
        category = cat1
        if cat2 and cat2 not in cat1:
            category = f"{cat1}, {cat2}" if cat1 else cat2

        if not location or location == "N/A":
            continue

        on_sat, on_sun = _parse_xplorehk_dates(date_str, sat_dt, sun_dt)
        if not on_sat and not on_sun:
            continue

        coords = geocode(location)
        if not coords:
            continue
        lat, lng = coords

        acts.append({
            "title":      title,
            "url":        link or "https://www.xplorehk.com",
            "lat":        lat,
            "lng":        lng,
            "venue_name": location[:60],
            "on_sat":     on_sat,
            "on_sun":     on_sun,
            "sat_times":  [clean_time(time_str)] if on_sat else [],
            "sun_times":  [clean_time(time_str)] if on_sun else [],
            "source":     "xplorehk.com",
            "category":   category,
        })
        event_count += 1

    print(f"      xplorehk events on target weekend: {event_count}")

    # ── Exhibition(new) sheet ──
    # Cols: Available, Cost, Event name, Category, (empty), Organizer, Link,
    #       Date (till D/M), Beginning Date, Ending Date, Time, Location, Photo, Area
    exhib_rows = fetch_sheet("Exhibition(new)")
    print(f"    xplorehk Exhibition(new): {len(exhib_rows)} rows")
    exhib_count = 0

    def parse_dm(s):
        if not s:
            return None
        s = re.sub(r"^till\s*", "", s.strip(), flags=re.I)
        m = re.match(r"^(\d{1,2})/(\d{1,2})$", s)
        if not m:
            return None
        try:
            return datetime(sat_dt.year, int(m.group(2)), int(m.group(1))).date()
        except ValueError:
            return None

    for row in exhib_rows[1:]:
        if len(row) < 10:
            continue
        if row[0] == "N":          # explicitly marked unavailable
            continue
        title    = row[2].strip() if len(row) > 2 else ""
        if not title:
            continue
        link     = row[6].strip()  if len(row) > 6 else ""
        begin_s  = row[8].strip()  if len(row) > 8 else ""
        end_s    = row[9].strip()  if len(row) > 9 else ""
        time_str = row[10].strip() if len(row) > 10 else ""
        location = row[11].strip() if len(row) > 11 else ""

        if not location or location == "N/A":
            continue

        begin_dt = parse_dm(begin_s)
        end_dt   = parse_dm(end_s)
        if not begin_dt or not end_dt:
            continue

        on_sat = (begin_dt <= sat_dt <= end_dt)
        on_sun = (begin_dt <= sun_dt <= end_dt)
        if not on_sat and not on_sun:
            continue

        coords = geocode(location)
        if not coords:
            continue
        lat, lng = coords

        acts.append({
            "title":      title,
            "url":        link or "https://www.xplorehk.com",
            "lat":        lat,
            "lng":        lng,
            "venue_name": location[:60],
            "on_sat":     on_sat,
            "on_sun":     on_sun,
            "sat_times":  [clean_time(time_str)] if on_sat else [],
            "sun_times":  [clean_time(time_str)] if on_sun else [],
            "source":     "xplorehk.com",
            "category":   "展覽",
        })
        exhib_count += 1

    print(f"      xplorehk exhibitions on target weekend: {exhib_count}")

    # ── event.txt (Xplore Events, YYYY-MM-DD dates) ──
    txt = fetch("https://www.xplorehk.com/event.txt")
    txt_count = 0
    if txt:
        events_raw = []
        cur = {}
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("Event Name:"):
                if cur.get("name"):
                    events_raw.append(cur)
                cur = {"name": line[11:].strip()}
            elif line.startswith("Date:"):
                cur["date"] = line[5:].strip()
            elif line.startswith("Time:"):
                cur["time"] = line[5:].strip()
            elif line.startswith("Venue:"):
                cur["venue"] = line[6:].strip()
            elif line.startswith("Application link:"):
                cur["link"] = line[17:].strip()
        if cur.get("name"):
            events_raw.append(cur)

        for ev in events_raw:
            date_s = ev.get("date", "")
            on_sat = date_s == sat_iso
            on_sun = date_s == sun_iso
            if not on_sat and not on_sun:
                continue
            venue = ev.get("venue", "").strip()
            if not venue or venue == "N/A":
                continue
            coords = geocode(venue)
            if not coords:
                continue
            lat, lng = coords
            acts.append({
                "title":      ev.get("name", ""),
                "url":        ev.get("link", "https://www.xplorehk.com"),
                "lat":        lat,
                "lng":        lng,
                "venue_name": venue[:60],
                "on_sat":     on_sat,
                "on_sun":     on_sun,
                "sat_times":  [clean_time(ev.get("time", ""))] if on_sat else [],
                "sun_times":  [clean_time(ev.get("time", ""))] if on_sun else [],
                "source":     "xplorehk.com",
                "category":   "",
            })
            txt_count += 1

    if txt_count:
        print(f"      xplorehk event.txt on target weekend: {txt_count}")

    print(f"    xplorehk total activities on target weekend: {len(acts)}")
    return acts


# ── Geocoding ───────────────────────────────────────────────────────────────────

_geocode_cache = {}

def geocode(venue_name):
    if not venue_name:
        return None
    if venue_name in _geocode_cache:
        return _geocode_cache[venue_name]

    vl = venue_name.lower()
    for key, lat, lng in KNOWN_VENUES:
        if key.lower() in vl:
            if in_hk(lat, lng):
                _geocode_cache[venue_name] = (lat, lng)
                return (lat, lng)
            _geocode_cache[venue_name] = None
            return None  # matched known venue but outside HK

    # Nominatim fallback — HK only
    try:
        q = venue_name if "hong kong" in venue_name.lower() else venue_name + ", Hong Kong"
        params = urllib.parse.urlencode({"q": q, "countrycodes": "hk",
                                         "format": "json", "limit": 1})
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": "HK-Weekend-Map/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        time.sleep(1.1)
        if data:
            lat, lng = float(data[0]["lat"]), float(data[0]["lon"])
            if in_hk(lat, lng):
                _geocode_cache[venue_name] = (lat, lng)
                return (lat, lng)
    except Exception:
        pass

    _geocode_cache[venue_name] = None
    return None


# ── Build venue list ─────────────────────────────────────────────────────────────

def build_venues(artmate_details, timable_acts, xplorehk_acts,
                 sat_date, sun_date, sat_ids, sun_ids):
    """
    Groups activities from all three sources by geocoded coordinates.
    Returns (venues_list, ungeocodable_list).
    """
    coord_map   = {}
    ungeocodable = []

    def add_to_map(lat, lng, venue_name, sat_list, sun_list):
        key = (round(lat, 4), round(lng, 4))
        if key not in coord_map:
            coord_map[key] = {
                "lat": lat, "lng": lng,
                "venue": venue_name,
                "sat_acts": [], "sun_acts": [],
            }
        coord_map[key]["sat_acts"].extend(sat_list)
        coord_map[key]["sun_acts"].extend(sun_list)

    # ── Art-mate ──
    for doc_id, info in artmate_details.items():
        on_sat = doc_id in sat_ids
        on_sun = doc_id in sun_ids
        schedule = info.get("schedule", [])

        # Skip if no evidence this activity is on the weekend
        if not schedule and not on_sat and not on_sun:
            continue

        coords = geocode(info.get("venue_name"))
        if not coords:
            if info.get("venue_name"):
                ungeocodable.append(info)
            continue

        sat_slots = [s for s in schedule if sat_date in s]
        sun_slots = [s for s in schedule if sun_date in s]
        if not sat_slots and on_sat:
            sat_slots = ["Available this weekend"]
        if not sun_slots and on_sun:
            sun_slots = ["Available this weekend"]

        if not sat_slots and not sun_slots:
            continue

        act = {
            "title":    info["title"],
            "doc_id":   doc_id,
            "url":      f"{BASE}/doc/{doc_id}",
            "source":   "art-mate.net",
            "category": "",
        }
        add_to_map(
            coords[0], coords[1], info["venue_name"],
            [{**act, "times": sat_slots}] if sat_slots else [],
            [{**act, "times": sun_slots}] if sun_slots else [],
        )

    # ── Timable ──
    for act in timable_acts:
        entry = {
            "title":    act["title"],
            "doc_id":   "",
            "url":      act["url"],
            "source":   "timable.com",
            "category": act.get("category", ""),
        }
        add_to_map(
            act["lat"], act["lng"], act["venue_name"],
            [{**entry, "times": act["sat_times"]}] if act["on_sat"] else [],
            [{**entry, "times": act["sun_times"]}] if act["on_sun"] else [],
        )

    # ── XploreHK ──
    for act in xplorehk_acts:
        entry = {
            "title":    act["title"],
            "doc_id":   "",
            "url":      act["url"],
            "source":   "xplorehk.com",
            "category": act.get("category", ""),
        }
        add_to_map(
            act["lat"], act["lng"], act["venue_name"],
            [{**entry, "times": act["sat_times"]}] if act["on_sat"] else [],
            [{**entry, "times": act["sun_times"]}] if act["on_sun"] else [],
        )

    # Deduplicate activities within each venue by normalised title.
    # Keeps the first occurrence (art-mate → timable → xplorehk priority).
    def dedup_acts(acts):
        seen = set()
        out  = []
        for a in acts:
            key = re.sub(r"\s+", " ", a["title"].strip()).lower()
            if key not in seen:
                seen.add(key)
                out.append(a)
        return out

    # Build final list
    venues = []
    for v in coord_map.values():
        v["sat_acts"] = dedup_acts(v["sat_acts"])
        v["sun_acts"] = dedup_acts(v["sun_acts"])
        if not v["sat_acts"] and not v["sun_acts"]:
            continue
        has_sat = bool(v["sat_acts"])
        has_sun = bool(v["sun_acts"])
        day = "both" if (has_sat and has_sun) else ("sat" if has_sat else "sun")
        venues.append({
            "name":     v["venue"],
            "lat":      v["lat"],
            "lng":      v["lng"],
            "day":      day,
            "sat_acts": v["sat_acts"],
            "sun_acts": v["sun_acts"],
        })

    return venues, ungeocodable


# ── HTML generation ─────────────────────────────────────────────────────────────

def make_html(venues, sat_label, sun_label):  # noqa: C901
    # Collect unique categories for the filter dropdown (Chinese first)
    cats_set = set()
    for v in venues:
        for a in v.get("sat_acts", []) + v.get("sun_acts", []):
            for c in re.split(r"[,，、]", a.get("category", "")):
                c = c.strip()
                if len(c) > 1:
                    cats_set.add(c)

    def _cat_sort(s):
        return (0 if any("一" <= ch <= "鿿" for ch in s) else 1, s)

    cat_opts = "\n".join(
        f'<option value="{c}">{c}</option>'
        for c in sorted(cats_set, key=_cat_sort)
    )

    venues_json = json.dumps(venues, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"/>
  <meta name="theme-color" content="#6366f1"/>
  <meta name="mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-capable" content="yes"/>
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
  <meta name="apple-mobile-web-app-title" content="HK Weekend"/>
  <link rel="manifest" href="manifest.json"/>
  <title>HK Weekend Activities – {sat_label} &amp; {sun_label}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
  <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
    html,body{{height:100%;overflow:hidden;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px}}

    /* ── Loading overlay ── */
    #loading{{
      position:fixed;inset:0;z-index:9999;
      background:linear-gradient(150deg,#eef2ff 0%,#faf5ff 100%);
      display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
      transition:opacity .5s ease;
    }}
    #loading.fade{{opacity:0;pointer-events:none}}
    .spin{{width:46px;height:46px;border-radius:50%;
      border:4px solid rgba(99,102,241,.15);border-top-color:#6366f1;
      animation:spin .8s linear infinite}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    #loading p{{font-size:13px;color:#6366f1;font-weight:600;letter-spacing:.4px}}

    /* ── Header – transparent glass ── */
    #hdr{{
      position:fixed;top:0;left:0;right:0;z-index:1000;
      background:rgba(255,255,255,0.08);
      backdrop-filter:blur(22px) saturate(160%);
      -webkit-backdrop-filter:blur(22px) saturate(160%);
      border-bottom:1px solid rgba(255,255,255,0.22);
      box-shadow:0 2px 18px rgba(0,0,0,0.07);
    }}
    #hdr-r1{{display:flex;align-items:center;gap:10px;padding:10px 16px}}
    #hdr-r2{{display:flex;align-items:center;gap:7px;padding:2px 16px 10px;flex-wrap:wrap}}

    /* Title */
    .hdr-title{{flex:1;min-width:0}}
    .hdr-title h1{{
      font-size:15px;font-weight:900;letter-spacing:-.2px;
      background:linear-gradient(120deg,#312e81 0%,#6366f1 55%,#a78bfa 100%);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent;
      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
      filter:drop-shadow(0 1px 2px rgba(0,0,0,0.18));
    }}
    .hdr-title .dates{{
      font-size:11px;color:#1e1b4b;margin-top:2px;font-weight:600;
      text-shadow:0 1px 3px rgba(255,255,255,0.9),0 0 8px rgba(255,255,255,0.7);
    }}

    /* Help button */
    #help-btn{{
      width:28px;height:28px;border-radius:50%;flex-shrink:0;
      border:1.5px solid rgba(99,102,241,.3);
      background:rgba(99,102,241,.08);color:#6366f1;
      font-size:13px;font-weight:800;cursor:pointer;
      display:flex;align-items:center;justify-content:center;
      transition:all .18s;
    }}
    #help-btn:hover{{background:rgba(99,102,241,.2);transform:scale(1.1)}}

    /* Day filter buttons */
    #day-btns{{display:flex;gap:5px;flex-shrink:0}}
    .db{{
      padding:5px 11px;border-radius:18px;
      border:1.5px solid rgba(0,0,0,.12);
      cursor:pointer;font-size:11px;font-weight:700;
      background:rgba(255,255,255,.82);color:#374151;
      backdrop-filter:blur(10px);
      box-shadow:0 1px 6px rgba(0,0,0,.10);
      transition:all .18s;white-space:nowrap;
    }}
    .db:active{{transform:scale(.96)}}
    .db-all {{background:#374151;color:#fff;border-color:#374151;box-shadow:0 2px 8px rgba(55,65,81,.3)}}
    .db-sat {{background:#DC2626;color:#fff;border-color:#DC2626;box-shadow:0 2px 8px rgba(220,38,38,.3)}}
    .db-sun {{background:#2563EB;color:#fff;border-color:#2563EB;box-shadow:0 2px 8px rgba(37,99,235,.3)}}
    .db-both{{background:#16A34A;color:#fff;border-color:#16A34A;box-shadow:0 2px 8px rgba(22,163,74,.3)}}

    /* Search */
    #search{{
      flex:1;min-width:120px;max-width:260px;
      padding:7px 12px;
      border:1.5px solid rgba(99,102,241,.25);border-radius:20px;
      font-size:12px;outline:none;
      background:rgba(255,255,255,.85);backdrop-filter:blur(10px);
      transition:all .2s;
    }}
    #search:focus{{border-color:#6366f1;background:#fff;box-shadow:0 0 0 3px rgba(99,102,241,.15)}}

    /* Category select */
    #cat-filter{{
      padding:6px 8px;border:1.5px solid rgba(99,102,241,.25);border-radius:10px;
      font-size:11px;outline:none;cursor:pointer;
      background:rgba(255,255,255,.85);backdrop-filter:blur(10px);max-width:140px;
    }}

    /* Time buttons */
    #time-btns{{display:flex;gap:4px;flex-shrink:0}}
    .tb{{
      padding:5px 9px;border-radius:12px;border:1.5px solid rgba(0,0,0,.12);
      cursor:pointer;font-size:11px;font-weight:600;
      background:rgba(255,255,255,.82);color:#374151;transition:all .18s;
    }}
    .tb:active{{transform:scale(.96)}}
    .tb-on{{background:#6366f1;color:#fff;border-color:#6366f1;box-shadow:0 2px 6px rgba(99,102,241,.35)}}

    #result-count{{font-size:10px;color:#9ca3af;white-space:nowrap}}

    /* Map */
    #map{{position:fixed;top:96px;left:0;right:0;bottom:0}}

    /* Custom map control buttons (reset + locate) */
    .map-fab{{
      width:36px;height:36px;
      background:rgba(255,255,255,.92);
      backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
      border:1.5px solid rgba(0,0,0,.1);border-radius:10px;
      cursor:pointer;font-size:17px;
      display:flex;align-items:center;justify-content:center;
      box-shadow:0 2px 10px rgba(0,0,0,.13);
      transition:all .18s;margin-bottom:6px;
    }}
    .map-fab:hover{{background:#fff;box-shadow:0 4px 16px rgba(0,0,0,.18);transform:translateY(-1px)}}
    .map-fab:active{{transform:scale(.94)}}
    .leaflet-top.leaflet-left .leaflet-control{{margin-top:6px;margin-left:6px}}

    /* Popup */
    .leaflet-popup-content-wrapper{{
      border-radius:16px;
      box-shadow:0 8px 36px rgba(0,0,0,.17);
      border:1px solid rgba(255,255,255,.75);
      background:rgba(255,255,255,.97);
    }}
    .leaflet-popup-content{{margin:14px 16px;width:auto!important;min-width:260px;max-width:340px}}
    .pv{{font-size:13px;font-weight:800;color:#111;margin-bottom:8px;
      border-bottom:2px solid #f0f0f0;padding-bottom:6px}}
    .pd{{font-size:11px;font-weight:700;color:#555;margin:8px 0 4px;
      display:flex;align-items:center;gap:6px}}
    .pd .badge{{display:inline-block;padding:2px 8px;border-radius:10px;
      font-size:10px;font-weight:800}}
    .bs{{background:#fee2e2;color:#DC2626}}
    .bn{{background:#dbeafe;color:#1d4ed8}}
    .pe{{border-left:3px solid #e5e7eb;padding:4px 0 4px 9px;margin:4px 0}}
    .pt{{font-size:12px;font-weight:600;color:#1a1a2e;line-height:1.35}}
    .pm{{font-size:11px;color:#374151;margin-top:2px}}
    .al{{font-size:10px;color:#4f46e5;text-decoration:none;display:inline-block;margin-top:2px}}
    .al:hover{{text-decoration:underline}}
    .src-badge{{display:inline-block;font-size:9px;padding:1px 5px;border-radius:4px;
      margin-left:4px;vertical-align:middle;font-weight:600}}
    .src-artmate {{background:#ede9fe;color:#6d28d9}}
    .src-timable {{background:#fce7f3;color:#be185d}}
    .src-xplorehk{{background:#dcfce7;color:#15803d}}
    .gm{{display:block;margin-top:11px;padding:9px;
      background:linear-gradient(135deg,#1F2937,#374151);color:#fff;
      text-align:center;border-radius:10px;font-size:12px;
      font-weight:700;text-decoration:none;letter-spacing:.3px;transition:all .18s}}
    .gm:hover{{background:linear-gradient(135deg,#111827,#1F2937);transform:translateY(-1px);
      box-shadow:0 4px 14px rgba(0,0,0,.28)}}

    /* Legend */
    .legend{{
      background:rgba(255,255,255,.88);backdrop-filter:blur(14px);
      padding:10px 14px;border-radius:12px;
      box-shadow:0 2px 16px rgba(0,0,0,.12);
      border:1px solid rgba(255,255,255,.7);font-size:12px;line-height:2}}
    .legend b{{font-size:13px}}
    .lr{{display:flex;align-items:center;gap:8px}}
    .ld{{width:13px;height:13px;border-radius:50%;flex-shrink:0;
      border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.25)}}
    .lnote{{font-size:10px;color:#999;margin-top:4px;line-height:1.5}}

    /* Help modal */
    #help-modal{{
      display:none;position:fixed;inset:0;z-index:5000;
      background:rgba(0,0,0,.45);backdrop-filter:blur(8px);
      align-items:center;justify-content:center;padding:20px;
    }}
    #help-modal.show{{display:flex}}
    .modal-box{{
      background:rgba(255,255,255,.97);backdrop-filter:blur(24px);
      border-radius:20px;padding:24px;max-width:360px;width:100%;
      border:1px solid rgba(255,255,255,.85);
      box-shadow:0 24px 64px rgba(0,0,0,.22);
    }}
    .modal-box h3{{font-size:16px;font-weight:800;color:#111;margin-bottom:12px}}
    .modal-box li{{font-size:13px;color:#374151;line-height:1.7;margin-bottom:2px}}
    .modal-box ul{{padding-left:18px;margin:6px 0}}
    .modal-srcs{{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}}
    .modal-close{{
      margin-top:16px;width:100%;padding:11px;
      background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff;
      border:none;border-radius:12px;font-size:13px;font-weight:700;
      cursor:pointer;transition:all .18s;
    }}
    .modal-close:hover{{opacity:.9;transform:translateY(-1px)}}

    /* ── Mobile ── */
    @media(max-width:640px){{
      #hdr-r1{{padding:8px 12px;gap:8px}}
      #hdr-r2{{padding:2px 12px 8px;gap:5px}}
      .hdr-title h1{{font-size:14px}}
      .db{{padding:4px 9px;font-size:10px}}
      #search{{min-width:90px}}
      #cat-filter{{max-width:110px;font-size:10px}}
      .tb{{padding:4px 7px;font-size:10px}}
      #map{{top:108px}}
    }}
    @media(max-width:420px){{
      .hdr-title h1{{font-size:13px}}
      #day-btns{{gap:3px}}
      .db{{padding:4px 7px;font-size:9px}}
      #time-btns .tb:nth-child(1){{display:none}}
    }}
  </style>
</head>
<body>

<!-- Loading overlay -->
<div id="loading">
  <div class="spin"></div>
  <p>Loading activities…</p>
</div>

<!-- Header -->
<div id="hdr">
  <div id="hdr-r1">
    <div class="hdr-title">
      <h1>🎭 HK Weekend Activities</h1>
      <div class="dates" id="hdr-dates">📅 {sat_label} (Sat) &amp; {sun_label} (Sun)</div>
    </div>
    <button id="help-btn" onclick="toggleHelp()" title="How to use">?</button>
    <div id="day-btns">
      <button class="db db-all" id="b-all"  onclick="setDay('all')">All</button>
      <button class="db"        id="b-sat"  onclick="setDay('sat')">🔴 Sat</button>
      <button class="db"        id="b-sun"  onclick="setDay('sun')">🔵 Sun</button>
      <button class="db"        id="b-both" onclick="setDay('both')">🟢 Both</button>
    </div>
  </div>
  <div id="hdr-r2">
    <input id="search" type="text" placeholder="🔍 Search activities, venues…" oninput="applyFilters()"/>
    <select id="cat-filter" onchange="applyFilters()">
      <option value="">All categories</option>
      {cat_opts}
    </select>
    <div id="time-btns">
      <button class="tb tb-on" id="t-all"       onclick="setTime('all')">All times</button>
      <button class="tb"       id="t-morning"   onclick="setTime('morning')">🌅 Morning</button>
      <button class="tb"       id="t-afternoon" onclick="setTime('afternoon')">☀️ Afternoon</button>
      <button class="tb"       id="t-evening"   onclick="setTime('evening')">🌙 Evening</button>
    </div>
    <span id="result-count"></span>
  </div>
</div>

<div id="map"></div>

<!-- Help modal -->
<div id="help-modal" onclick="toggleHelp()">
  <div class="modal-box" onclick="event.stopPropagation()">
    <h3>ℹ️ How to use</h3>
    <ul>
      <li>Tap a <b>pin</b> to see activities at that venue</li>
      <li>Pinch or scroll to zoom — clusters expand automatically</li>
      <li>Filter by <b>Sat / Sun / Both</b> using the day buttons</li>
      <li>Filter by <b>category</b> or <b>time of day</b> in the second row</li>
      <li>Use <b>Search</b> to find by activity name, venue or keyword</li>
      <li>Tap <b>⌂</b> on the map to reset to the Hong Kong view</li>
      <li>Tap <b>📍</b> to show your current location</li>
    </ul>
    <p style="margin-top:10px;font-size:11px;color:#6b7280;font-weight:600">Data sources</p>
    <div class="modal-srcs">
      <span class="src-badge src-artmate"  style="font-size:11px;padding:3px 8px">art-mate.net</span>
      <span class="src-badge src-timable"  style="font-size:11px;padding:3px 8px">timable.com</span>
      <span class="src-badge src-xplorehk" style="font-size:11px;padding:3px 8px">xplorehk.com</span>
    </div>
    <button class="modal-close" onclick="toggleHelp()">Got it!</button>
  </div>
</div>

<script>
const VENUES = {venues_json};

// ── Map setup (HK only) ───────────────────────────────────────────────────────
const HK_CENTER = [22.340, 114.155];
const HK_ZOOM   = 11;
const HK_BOUNDS = L.latLngBounds([[22.10, 113.75], [22.60, 114.50]]);

const map = L.map('map', {{
  maxBounds:            HK_BOUNDS,
  maxBoundsViscosity:   0.9,
  minZoom:              10,
}}).setView(HK_CENTER, HK_ZOOM);

// CartoDB Positron — clean, no terrain labels or contour lines
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
  subdomains: 'abcd',
  maxZoom: 19,
}}).addTo(map);

// Sync map top with header height (handles wrapping on narrow screens)
function syncMapTop() {{
  document.getElementById('map').style.top = document.getElementById('hdr').offsetHeight + 'px';
}}
syncMapTop();
window.addEventListener('resize', syncMapTop);

// ── Colours ───────────────────────────────────────────────────────────────────
const CLR = {{sat:'#DC2626', sun:'#2563EB', both:'#16A34A'}};

// ── Cluster group ─────────────────────────────────────────────────────────────
const mcg = L.markerClusterGroup({{
  maxClusterRadius: 70,
  disableClusteringAtZoom: 15,
  iconCreateFunction(cluster) {{
    const n  = cluster.getChildCount();
    const sz = n > 50 ? 54 : n > 20 ? 46 : n > 10 ? 40 : 34;
    return L.divIcon({{
      className: '',
      html: `<div style="width:${{sz}}px;height:${{sz}}px;
        background:rgba(31,41,55,0.87);border-radius:50%;
        border:3px solid rgba(255,255,255,.9);
        box-shadow:0 3px 14px rgba(0,0,0,.32);
        display:flex;align-items:center;justify-content:center;
        color:#fff;font-weight:800;font-size:${{n>99?10:13}}px;
        font-family:-apple-system,sans-serif">${{n}}</div>`,
      iconSize: [sz,sz], iconAnchor: [sz/2,sz/2]
    }});
  }}
}});
map.addLayer(mcg);

// ── Custom controls ───────────────────────────────────────────────────────────
const ResetControl = L.Control.extend({{
  onAdd() {{
    const b = L.DomUtil.create('button','map-fab');
    b.innerHTML = '⌂'; b.title = 'Reset to Hong Kong view';
    L.DomEvent.on(b,'click', e => {{
      L.DomEvent.stopPropagation(e);
      map.setView(HK_CENTER, HK_ZOOM);
    }});
    return b;
  }}
}});

const LocateControl = L.Control.extend({{
  onAdd() {{
    const b = L.DomUtil.create('button','map-fab');
    b.innerHTML = '📍'; b.title = 'Find my location';
    L.DomEvent.on(b,'click', e => {{
      L.DomEvent.stopPropagation(e);
      b.innerHTML = '⏳';
      map.locate({{setView:true, maxZoom:14}});
      map.once('locationfound', ()  => {{ b.innerHTML = '📍'; }});
      map.once('locationerror', ()  => {{
        b.innerHTML = '📍';
        alert('Location unavailable — please enable location access for this page.');
      }});
    }});
    return b;
  }}
}});

new ResetControl({{position:'topleft'}}).addTo(map);
new LocateControl({{position:'topleft'}}).addTo(map);

// ── Helpers ───────────────────────────────────────────────────────────────────
function getHour(s) {{
  if (!s) return null;
  s = s.replace(/\d{{4}}-\d{{2}}-\d{{2}}/g,'');
  const m = s.match(/(\d{{1,2}})(?::\d{{2}})?\s*(am|pm)?/i);
  if (!m) return null;
  let h = +m[1];
  const ap = (m[2]||'').toLowerCase();
  if (ap==='pm' && h<12) h+=12;
  if (ap==='am' && h===12) h=0;
  if (h<5 || h>23) return null;
  return h;
}}

function inSlot(h,slot) {{
  if (slot==='morning')   return h>=6  && h<12;
  if (slot==='afternoon') return h>=12 && h<18;
  if (slot==='evening')   return h>=18;
  return true;
}}

function srcBadge(src) {{
  if (!src) return '';
  const cls = src.includes('art-mate')?'src-artmate':src.includes('timable')?'src-timable':'src-xplorehk';
  return `<span class="src-badge ${{cls}}">${{src}}</span>`;
}}

function buildPopup(v) {{
  const gm = `https://www.google.com/maps/search/?api=1&query=${{v.lat}},${{v.lng}}`;
  let html = `<div class="pv">${{v.name}}</div>`;
  if (v.sat_acts.length) {{
    html += `<div class="pd"><span class="badge bs">🔴 Sat {sat_label[:6]}</span></div>`;
    for (const a of v.sat_acts) {{
      html += `<div class="pe">
        <div class="pt">${{a.title}}</div>
        <div class="pm">⏰ ${{a.times.join('<br>')}}</div>
        <a class="al" href="${{a.url}}" target="_blank">→ ${{a.source||'art-mate.net'}}</a>
        ${{srcBadge(a.source)}}
      </div>`;
    }}
  }}
  if (v.sun_acts.length) {{
    html += `<div class="pd" style="margin-top:8px"><span class="badge bn">🔵 Sun {sun_label[:6]}</span></div>`;
    for (const a of v.sun_acts) {{
      html += `<div class="pe">
        <div class="pt">${{a.title}}</div>
        <div class="pm">⏰ ${{a.times.join('<br>')}}</div>
        <a class="al" href="${{a.url}}" target="_blank">→ ${{a.source||'art-mate.net'}}</a>
        ${{srcBadge(a.source)}}
      </div>`;
    }}
  }}
  html += `<a class="gm" href="${{gm}}" target="_blank">📍 Open in Google Maps</a>`;
  return html;
}}

// ── Build markers ─────────────────────────────────────────────────────────────
const allMarkers = [];
VENUES.forEach(v => {{
  const n   = v.sat_acts.length + v.sun_acts.length;
  const sz  = n >= 8 ? 42 : n >= 4 ? 36 : n >= 2 ? 30 : 26;
  const col = CLR[v.day];
  const icon = L.divIcon({{
    className:'',
    html:`<div style="width:${{sz}}px;height:${{sz}}px;background:${{col}};
      border-radius:50%;border:3px solid rgba(255,255,255,.9);
      box-shadow:0 2px 10px rgba(0,0,0,.32);
      display:flex;align-items:center;justify-content:center;
      color:#fff;font-weight:800;font-size:${{n>9?10:12}}px;
      font-family:-apple-system,sans-serif">${{n}}</div>`,
    iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]
  }});
  const m = L.marker([v.lat,v.lng],{{icon}})
    .bindPopup(buildPopup(v),{{maxWidth:360,minWidth:270}});
  const allActs  = v.sat_acts.concat(v.sun_acts);
  const searchTx = (v.name+' '+allActs.map(a=>a.title+' '+(a.category||'')).join(' ')).toLowerCase();
  const catList  = [...new Set(allActs.flatMap(a=>(a.category||'').split(/[,，、]/).map(c=>c.trim())).filter(Boolean))];
  const hourList = allActs.flatMap(a=>a.times.map(getHour)).filter(h=>h!==null);
  m._f = {{day:v.day, tx:searchTx, cats:catList, hrs:hourList}};
  allMarkers.push(m);
}});
mcg.addLayers(allMarkers);

// ── Filter state ──────────────────────────────────────────────────────────────
let gDay='all', gTime='all';

function applyFilters() {{
  const q   = (document.getElementById('search').value||'').toLowerCase().trim();
  const cat = (document.getElementById('cat-filter').value||'').toLowerCase();
  const filtered = allMarkers.filter(m => {{
    const f = m._f;
    if (gDay!=='all') {{
      if (gDay==='sat'  && f.day==='sun')  return false;
      if (gDay==='sun'  && f.day==='sat')  return false;
      if (gDay==='both' && f.day!=='both') return false;
    }}
    if (q && !f.tx.includes(q)) return false;
    if (cat && !f.cats.some(c=>c.toLowerCase().includes(cat))) return false;
    if (gTime!=='all' && f.hrs.length>0 && !f.hrs.some(h=>inSlot(h,gTime))) return false;
    return true;
  }});
  mcg.clearLayers();
  mcg.addLayers(filtered);
  document.getElementById('result-count').textContent =
    filtered.length < allMarkers.length
      ? `${{filtered.length}} / ${{allMarkers.length}} venues`
      : `${{allMarkers.length}} venues`;
}}

function setDay(d) {{
  gDay = d;
  ['all','sat','sun','both'].forEach(t => {{
    const b = document.getElementById('b-'+t);
    b.className = 'db';
    if (t===d) b.classList.add('db-'+t);
  }});
  applyFilters();
}}

function setTime(t) {{
  gTime = t;
  ['all','morning','afternoon','evening'].forEach(k => {{
    document.getElementById('t-'+k).className = 'tb'+(k===t?' tb-on':'');
  }});
  applyFilters();
}}

function toggleHelp() {{
  document.getElementById('help-modal').classList.toggle('show');
}}

// ── Legend ────────────────────────────────────────────────────────────────────
const leg = L.control({{position:'bottomright'}});
leg.onAdd = () => {{
  const d = L.DomUtil.create('div','legend');
  d.innerHTML = `<b>Legend</b>
    <div class="lr"><div class="ld" style="background:#DC2626"></div> Saturday only</div>
    <div class="lr"><div class="ld" style="background:#2563EB"></div> Sunday only</div>
    <div class="lr"><div class="ld" style="background:#16A34A"></div> Both days</div>
    <div class="lr" style="margin-top:4px">
      <div class="ld" style="background:rgba(31,41,55,.85)"></div> Cluster (zoom to expand)
    </div>
    <div class="lnote">Number = activities at venue<br>Tap pin for details</div>`;
  return d;
}};
leg.addTo(map);

// ── Init ──────────────────────────────────────────────────────────────────────
applyFilters();

// Hide loading overlay after two animation frames (map has started rendering)
requestAnimationFrame(() => requestAnimationFrame(() => {{
  const el = document.getElementById('loading');
  if (el) {{
    el.classList.add('fade');
    setTimeout(() => {{ if (el.parentNode) el.remove(); }}, 550);
  }}
}}));
// Hard fallback at 4 s in case rAF fires before Leaflet initialises
setTimeout(() => {{
  const el = document.getElementById('loading');
  if (el) {{ el.classList.add('fade'); setTimeout(() => {{ if(el.parentNode)el.remove(); }},550); }}
}}, 4000);
</script>
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', () => navigator.serviceWorker.register('sw.js'));
}}
</script>
</body>
</html>"""


# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="HK Weekend Arts Map Generator")
    parser.add_argument("--sat",  help="Saturday date YYYYMMDD")
    parser.add_argument("--sun",  help="Sunday date YYYYMMDD")
    parser.add_argument("--out",  help="Output HTML file path", default=str(OUT_FILE))
    args = parser.parse_args()

    if args.sat and args.sun:
        sat_date, sun_date = args.sat, args.sun
    else:
        sat_date, sun_date = upcoming_weekend()

    sat_label = datetime.strptime(sat_date, "%Y%m%d").strftime("%-d %b %Y")
    sun_label = datetime.strptime(sun_date, "%Y%m%d").strftime("%-d %b %Y")
    sat_iso   = datetime.strptime(sat_date, "%Y%m%d").strftime("%Y-%m-%d")
    sun_iso   = datetime.strptime(sun_date, "%Y%m%d").strftime("%Y-%m-%d")
    target_dates = {sat_iso, sun_iso}

    print(f"\n🗓  Weekend: {sat_label} (Sat) & {sun_label} (Sun)")
    print("=" * 60)

    # 1. Art-mate listing pages
    print("\n[1/5] Scraping art-mate.net listing pages…")
    sat_ids = scrape_all_activities(sat_date)
    sun_ids = scrape_all_activities(sun_date)
    all_ids = {**sat_ids, **sun_ids}
    print(f"  art-mate unique activities (both days): {len(all_ids)}")

    # 2. Art-mate detail pages
    print("\n[2/5] Fetching art-mate.net detail pages…")
    artmate_details = fetch_all_details(all_ids, target_dates)
    print(f"  Fetched {len(artmate_details)} detail pages")

    # 3. Timable
    print("\n[3/5] Scraping timable.com…")
    timable_acts = scrape_timable(sat_iso, sun_iso)

    # 4. XploreHK
    print("\n[4/5] Scraping xplorehk.com…")
    xplorehk_acts = scrape_xplorehk(sat_iso, sun_iso)

    # 5. Geocode & build venues
    print("\n[5/5] Geocoding venues and building map…")
    venues, ungeocodable = build_venues(
        artmate_details, timable_acts, xplorehk_acts,
        sat_iso, sun_iso, sat_ids, sun_ids
    )
    print(f"  Mapped {len(venues)} venue pins")
    if ungeocodable:
        print(f"  Could not geocode {len(ungeocodable)} art-mate activities:")
        for a in ungeocodable[:5]:
            print(f"    - {a.get('title','?')} @ {a.get('venue_name','?')}")
        if len(ungeocodable) > 5:
            print(f"    … and {len(ungeocodable)-5} more")

    # Generate HTML
    html = make_html(venues, sat_label, sun_label)
    out_path = Path(args.out).expanduser()
    out_path.write_text(html, encoding="utf-8")

    total_acts = sum(len(v["sat_acts"]) + len(v["sun_acts"]) for v in venues)
    print(f"\n✅ Saved: {out_path}")
    print(f"   {len(venues)} venue pins · {total_acts} total activity entries")
    print(f"   art-mate: {len(all_ids)}  timable: {len(timable_acts)}  xplorehk: {len(xplorehk_acts)}")
    print(f'\n   Open: open "{out_path}"')


if __name__ == "__main__":
    main()
