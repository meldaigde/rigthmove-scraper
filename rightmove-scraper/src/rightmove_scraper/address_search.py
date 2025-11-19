from typing import Any, Dict, List, Optional, Tuple
import time
import json
import re

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
}

# --- TypeAhead: birincil endpoint (los) ---
LOS_ENDPOINT = "https://los.rightmove.co.uk/typeahead"
# --- TypeAhead: alternatif endpoint (fallback) ---
ALT_ENDPOINT = "https://www.rightmove.co.uk/typeahead/ukpropertyfor-sale/{}?maxResults=10"


def _json_get(resp: requests.Response) -> Optional[dict]:
    try:
        return resp.json()
    except Exception:
        return None


def autocomplete_address(query: str, timeout: int = 10) -> Optional[Dict[str, str]]:
    """
    Smart scoring ile en iyi eşleşen yeri döndürür:
    { "name": displayName, "type": TYPE, "id": ID, "locationIdentifier": "TYPE^ID" }
    """
    q = (query or "").strip()
    if len(q) < 2:
        return None

    # 1) Birincil (LOS)
    try:
        r = requests.get(
            LOS_ENDPOINT,
            params={"query": q, "limit": 10, "channel": "BUY"},
            headers=HEADERS,
            timeout=timeout,
        )
        if r.status_code == 200:
            data = _json_get(r) or {}
            results = data.get("matches") or data.get("typeahead") or []
            choice = _pick_best_match(q, results)
            if choice:
                return choice
    except Exception:
        pass

    # 2) Alternatif (www) — bazen farklı veri döner
    try:
        r2 = requests.get(ALT_ENDPOINT.format(q.replace(" ", "%20")), headers=HEADERS, timeout=timeout)
        if r2.status_code == 200:
            res = _json_get(r2) or []
            # www endpoint doğrudan list döndürür
            results = []
            for it in res:
                results.append(
                    {
                        "id": it.get("id"),
                        "type": it.get("type"),
                        "displayName": it.get("displayName"),
                    }
                )
            choice = _pick_best_match(q, results)
            if choice:
                return choice
    except Exception:
        pass

    return None


def _score_match(q: str, name: str, typ: str) -> float:
    """A1 – smart scoring: prefix + içerme + type önceliği (STREET > POSTCODE > REGION)."""
    q_l = q.lower()
    n_l = (name or "").lower()
    score = 0.0

    if n_l.startswith(q_l):
        score += 2.0
    if q_l in n_l:
        score += 1.0

    # type boost
    if typ == "STREET":
        score += 1.5
    elif typ in ("POSTCODE", "OUTCODE"):
        score += 1.2
    elif typ == "REGION":
        score += 1.0

    # London/UK sinyalleri (yanlış ülke riskini azaltır)
    if "london" in n_l:
        score += 0.3

    return score


def _pick_best_match(q: str, results: List[dict]) -> Optional[Dict[str, str]]:
    if not results:
        return None

    best = None
    best_score = -1.0
    for it in results:
        name = it.get("displayName") or it.get("name") or ""
        typ = it.get("type") or ""
        idv = it.get("id") or it.get("locationIdentifier") or ""

        sc = _score_match(q, name, typ)
        if sc > best_score:
            best_score = sc
            best = {"name": name, "type": typ, "id": str(idv), "locationIdentifier": f"{typ}^{idv}"}

    # Eksik parça varsa None dön
    if not best or not best.get("type") or not best.get("id"):
        return None
    return best


def find_listing_url_from_location_identifier(location_identifier: str, timeout: int = 12) -> Optional[str]:
    """
    TYPE^ID ile arama sayfasına gider, ilk ilan linkini döndürür.
    """
    base = "https://www.rightmove.co.uk/property-for-sale/find.html"
    params = {
        "locationIdentifier": location_identifier,
        "sortType": "6",  # Most recent
        "propertyTypes": "detached,semi-detached,terraced,flat",
        "viewType": "LIST",
        "channel": "BUY",
        "index": "0",
    }

    try:
        r = requests.get(base, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
    except Exception:
        return None

    soup = BeautifulSoup(r.text, "lxml")
    a = soup.select_one("a.propertyCard-link")
    if not a:
        return None
    href = a.get("href") or ""
    if href.startswith("/properties"):
        return "https://www.rightmove.co.uk" + href
    return href or None


def find_listing_url_with_fallback(address_text: str, timeout: int = 12) -> Optional[str]:
    """
    En güvenilir zincir:
    1) autocomplete → TYPE^ID
    2) find.html ile ilk ilan linkini al
    3) Gerekirse eski yaklaşım: search.html + 'a.propertyCard-link'
    """
    q = (address_text or "").strip()
    if len(q) < 2:
        return None

    # 1) Autocomplete
    best = autocomplete_address(q, timeout=timeout)
    if best and best.get("locationIdentifier"):
        url = find_listing_url_from_location_identifier(best["locationIdentifier"], timeout=timeout)
        if url:
            return url

    # 2) Fallback — eski yöntem
    from urllib.parse import urlencode
    base = "https://www.rightmove.co.uk/property-for-sale/search.html"
    params = {
        "searchLocation": q,
        "buy": "For sale",
        "useLocationIdentifier": "true",
    }
    try:
        r2 = requests.get(base + "?" + urlencode(params), headers=HEADERS, timeout=timeout)
        if r2.status_code != 200:
            return None
        soup = BeautifulSoup(r2.text, "lxml")
        a = soup.select_one("a.propertyCard-link")
        if not a:
            return None
        href = a.get("href") or ""
        if href.startswith("/properties"):
            return "https://www.rightmove.co.uk" + href
        return href or None
    except Exception:
        return None
