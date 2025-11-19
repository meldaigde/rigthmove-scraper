import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# Stabil ve ban yemeyi azaltan başlıklar
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Connection": "keep-alive",
}


def _get_html(url: str, timeout: int = 12, retries: int = 2, backoff: float = 1.2) -> Optional[requests.Response]:
    """Sağlam istek: 403/429/5xx durumlarında kısa retry yapar."""
    session = requests.Session()
    session.headers.update(HEADERS)

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429, 500, 502, 503, 504):
                time.sleep(backoff * (attempt + 1))
                continue
            # diğer error kodlarında dön
            return resp
        except Exception as e:
            last_exc = e
            time.sleep(backoff * (attempt + 1))
    if last_exc:
        raise last_exc
    return None


def _extract_first_json_object(script_text: str) -> Optional[dict]:
    """Script içindeki ilk JSON objesini parçalayıp dict döndürmeye çalışır."""
    # Hızlı deneme: dengeli süslü parantez taraması
    start = script_text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(script_text)):
            ch = script_text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = script_text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break

    # Fallback: kaba regex ile {} blok yakalama (en uzun)
    try:
        for m in re.finditer(r"\{.*\}", script_text, flags=re.DOTALL):
            candidate = m.group(0)
            try:
                return json.loads(candidate)
            except Exception:
                continue
    except Exception:
        pass
    return None


def _extract_state_from_html(html: str) -> Optional[dict]:
    """Rightmove sayfasındaki gömülü state JSON'unu döndürür."""
    soup = BeautifulSoup(html, "lxml")
    scripts = [s.string or "" for s in soup.find_all("script")]

    state_keys = [
        "window.__PRELOADED_STATE__",
        "window.__INITIAL_STATE__",
        "__RMLISTING_STATE__",
        '"propertyData":',
        '"analyticsProperty":',
    ]

    for script in scripts:
        if any(key in script for key in state_keys):
            js = _extract_first_json_object(script)
            if isinstance(js, dict):
                return js
    return None


def _int_or_none(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        s = str(x).replace(",", "").strip()
        return int(s) if s.isdigit() else None
    except Exception:
        return None


def _extract_images(property_data: dict) -> List[str]:
    urls: List[str] = []
    # propertyData.images genelde list biçiminde olur
    imgs = property_data.get("images") or []
    if isinstance(imgs, list):
        for it in imgs:
            # bazen dict -> {src:"...", large:"...", small:"..."}
            if isinstance(it, dict):
                for key in ("src", "large", "small", "url"):
                    v = it.get(key)
                    if isinstance(v, str) and v.startswith("http"):
                        urls.append(v)
            elif isinstance(it, str) and it.startswith("http"):
                urls.append(it)
    # Ayrıca staticMapImgUrls vs varsa eklemiyoruz; sadece gerçek foto
    # Duplicates kaldır
    return list(dict.fromkeys(urls))


def _extract_agent_info(state: dict) -> Dict[str, Optional[str]]:
    ap = state.get("analyticsInfo", {}).get("analyticsProperty", {}) if isinstance(state, dict) else {}
    branch_name = ap.get("branchName")
    display_address = ap.get("displayAddress")
    # Telefon için bazı sayfalarda contactInfo altında olabilir:
    contact = state.get("propertyData", {}).get("contactInfo", {}) if isinstance(state, dict) else {}
    phone = None
    if isinstance(contact, dict):
        phone = contact.get("telephone") or contact.get("phoneNumber")

    return {
        "name": branch_name or ap.get("companyName"),
        "display_address": display_address,
        "phone": phone,
    }


def _extract_epc(property_data: dict) -> Dict[str, Optional[str]]:
    # EPC metni bazen propertyData.features/epcGraphs altında olabilir
    # burada basit anahtarlar ile deneyelim:
    epc_rating = None
    epc_graphs = property_data.get("epcGraphs") or []
    if isinstance(epc_graphs, list) and epc_graphs:
        # Görsel URL’leri varsa dönmeyelim; rating text yoksa None kalsın
        pass
    # Bazı ilanlarda keyFeatures içinde EPC grade yazılabiliyor (A/B/C gibi)
    # burada ek bir akıl yürütme yapmıyoruz — None olabilir.
    return {"rating": epc_rating}


def _extract_listing_history(state: dict) -> Dict[str, Any]:
    ap = state.get("analyticsInfo", {}).get("analyticsProperty", {}) if isinstance(state, dict) else {}
    added = ap.get("added")  # YYYYMMDD gibi gelebilir
    # priceReduced flag analytics'te her zaman yok
    reduced = False

    hist = state.get("propertyData", {}).get("listingHistory", {})
    if isinstance(hist, dict):
        # örn: {"events":[{"event":"PRICE_REDUCED","date":"..."}]}
        events = hist.get("events") or []
        for ev in events:
            if isinstance(ev, dict) and str(ev.get("event", "")).upper().startswith("PRICE_REDUCED"):
                reduced = True
                break

    return {"added": added, "reduced": reduced}


def _extract_tenure(property_data: dict) -> Optional[str]:
    # propertyData.tenure genelde string olur (Freehold/Leasehold)
    ten = property_data.get("tenure")
    if isinstance(ten, dict):
        return ten.get("tenure") or ten.get("value")
    if isinstance(ten, str):
        return ten
    return None


def _extract_location(state: dict) -> Dict[str, Optional[float]]:
    ap = state.get("analyticsInfo", {}).get("analyticsProperty", {}) if isinstance(state, dict) else {}
    lat = ap.get("latitude")
    lon = ap.get("longitude")
    try:
        return {"lat": float(lat) if lat is not None else None, "lon": float(lon) if lon is not None else None}
    except Exception:
        return {"lat": None, "lon": None}


def _extract_key_features(property_data: dict) -> List[str]:
    feats = property_data.get("keyFeatures") or property_data.get("features") or []
    out: List[str] = []
    if isinstance(feats, list):
        for f in feats:
            if isinstance(f, dict):
                txt = f.get("text")
                if isinstance(txt, str) and txt.strip():
                    out.append(txt.strip())
            elif isinstance(f, str) and f.strip():
                out.append(f.strip())
    return out


def fetch_property_summary(url: str) -> dict:
    """
    Geniş özet:
    - price, bedrooms, bathrooms
    - property_type, property_subtype, final_property_type
    - address (display/line1/area/city/postcode)
    - postcode
    - agent (name, phone, display_address)
    - location (lat, lon)
    - images (list)
    - tenure
    - epc (rating)
    - listing_history (added, reduced)
    """
    result: Dict[str, Any] = {
        "url": url,
        "status": "success",
        "price": None,
        "bedrooms": None,
        "bathrooms": None,
        "property_type": None,
        "property_subtype": None,
        "final_property_type": None,
        "address": None,
        "postcode": None,
        "agent": None,
        "location": None,
        "images": [],
        "tenure": None,
        "epc": {"rating": None},
        "listing_history": {"added": None, "reduced": False},
        "key_features": [],
    }

    resp = _get_html(url)
    if not resp:
        result["status"] = "error_no_response"
        return result
    if resp.status_code != 200:
        result["status"] = f"error_http_{resp.status_code}"
        return result

    state = _extract_state_from_html(resp.text)
    if not isinstance(state, dict):
        result["status"] = "error_no_state"
        return result

    property_data = state.get("propertyData", {}) if isinstance(state, dict) else {}
    ap = state.get("analyticsInfo", {}).get("analyticsProperty", {}) if isinstance(state, dict) else {}

    # --- Price (analytics en güvenilir) ---
    result["price"] = _int_or_none(ap.get("price"))

    # --- Beds / Baths ---
    if isinstance(property_data, dict):
        result["bedrooms"] = _int_or_none(property_data.get("bedrooms"))
        result["bathrooms"] = _int_or_none(property_data.get("bathrooms"))

    # --- Property Type/Subtype ---
    ptype = ap.get("propertyType") or property_data.get("propertyType")
    psub = ap.get("propertySubType") or property_data.get("propertySubType")
    result["property_type"] = ptype
    result["property_subtype"] = psub
    if ptype and psub:
        result["final_property_type"] = f"{psub} {ptype}"
    else:
        result["final_property_type"] = ptype or psub

    # --- Address structured + postcode ---
    addr = {"display": None, "line1": None, "area": None, "city": None, "postcode": None}
    display = ap.get("displayAddress")
    p_addr = property_data.get("address", {}) if isinstance(property_data, dict) else {}
    if not display and isinstance(p_addr, dict):
        display = p_addr.get("displayAddress")

    if isinstance(display, str) and display.strip():
        addr["display"] = display
        parts = [p.strip() for p in display.replace("\n", ",").split(",") if p.strip()]
        if len(parts) >= 1:
            addr["line1"] = parts[0]
        if len(parts) >= 2:
            addr["area"] = parts[1]
        if len(parts) >= 3:
            last = parts[-1]
            if not (ap.get("postcode") and isinstance(last, str) and ap.get("postcode") in last):
                addr["city"] = last

    addr["postcode"] = (
        ap.get("postcode")
        or (p_addr.get("postcode") if isinstance(p_addr, dict) else None)
        or addr["postcode"]
    )

    # London düzeltmesi
    if addr["city"] is None:
        if addr["area"] and str(addr["area"]).lower() == "london":
            addr["city"] = "London"
        elif addr["display"] and "london" in str(addr["display"]).lower():
            addr["city"] = "London"
        elif addr["postcode"] and str(addr["postcode"])[:1] in ["N", "E", "W", "S"]:
            addr["city"] = "London"

    result["address"] = addr
    result["postcode"] = addr["postcode"]

    # --- Agent info, location, images, tenure, epc, history, features ---
    result["agent"] = _extract_agent_info(state)
    result["location"] = _extract_location(state)
    result["images"] = _extract_images(property_data)
    result["tenure"] = _extract_tenure(property_data)
    result["epc"] = _extract_epc(property_data)
    result["listing_history"] = _extract_listing_history(state)
    result["key_features"] = _extract_key_features(property_data)

    return result
