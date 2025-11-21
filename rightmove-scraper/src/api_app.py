import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

# -------------------------------
# PYTHON PATH FIX (src klasörü için)
# -------------------------------
ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# -------------------------------
# SCRAPER IMPORTS
# -------------------------------
from src.rightmove_scraper.url_scraper import fetch_property_summary
from src.rightmove_scraper.address_search import (
    find_listing_url_with_fallback,
    autocomplete_address
)

# -------------------------------
# FASTAPI CONFIG
# -------------------------------
app = FastAPI(
    title="Rightmove Scraper API",
    version="1.0.0",
    description="API service for Rightmove property scraping and search."
)

# -------------------------------
# 0) HEALTH CHECK
# -------------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "rightmove-scraper-api",
        "status": "running"
    }

# -------------------------------
# 1) /autocomplete
# -------------------------------
@app.get("/autocomplete")
def autocomplete(q: str = Query(..., min_length=2, description="Address or area text")):
    """
    Returns the best match as Rightmove locationIdentifier (e.g. 'REGION^87490')
    """
    try:
        loc_id = autocomplete_address(q)
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "input": {"query": q},
                "data": {"locationIdentifier": loc_id}
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# -------------------------------
# 2) /listing-url
# -------------------------------
@app.get("/listing-url")
def listing_url(address: str = Query(..., min_length=2)):
    """
    Takes full or partial address and returns the first matching Rightmove listing URL.
    """
    try:
        url = find_listing_url_with_fallback(address)
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "input": {"address": address},
                "data": {"url": url}
            }
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# -------------------------------
# 3) /summary
# -------------------------------
@app.get("/summary")
def summary(url: str = Query(..., description="Rightmove property URL")):
    """
    Returns key property details scraped from the listing URL.
    """
    try:
        data = fetch_property_summary(url)
        payload = {
            "ok": True,
            "input": {"url": url},
            "data": {
                "price": data.get("price"),
                "bedrooms": data.get("bedrooms"),
                "bathrooms": data.get("bathrooms"),
                "property_type": data.get("property_type"),
                "property_subtype": data.get("property_subtype"),
                "final_property_type": data.get("final_property_type"),
                "address": data.get("address"),
                "postcode": data.get("postcode"),
                "agent": data.get("agent"),
                "location": data.get("location"),
                "images": data.get("images"),
                "tenure": data.get("tenure"),
                "epc": data.get("epc"),
                "listing_history": data.get("listing_history"),
                "key_features": data.get("key_features")
            }
        }
        return JSONResponse(status_code=200, content=payload)
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})

# -------------------------------
# 4) /resolve  (1 endpoint → full workflow)
# -------------------------------
@app.get("/resolve")
def resolve(
    address: Optional[str] = Query(None, description="Full or partial address"),
    url: Optional[str] = Query(None, description="Rightmove property URL")
):
    """
    If URL is provided → returns summary
    If address is provided → finds URL + returns summary
    """
    try:
        if url:
            data = fetch_property_summary(url)
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "mode": "url",
                    "input": {"url": url},
                    "data": data
                }
            )

        if address:
            prop_url = find_listing_url_with_fallback(address)
            data = fetch_property_summary(prop_url)
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "mode": "address",
                    "input": {"address": address, "url": prop_url},
                    "data": data
                }
            )

        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "Provide either 'address' or 'url'."}
        )

    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
        # -------------------------------
# -------------------------------
# 5) /address-endpoint (improved)
# -------------------------------
@app.get("/address-endpoint")
def address_endpoint(
    address: str = Query(..., description="Full address string from the Excel sheet")
):
    """
    Improved version for Michael D'rew:
    - Takes a full address string
    - Finds the corresponding Rightmove listing URL using existing search logic
    - Returns both the address and the matched URL
    """
    cleaned = address.strip()

    if not cleaned:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Address cannot be empty."})

    try:
        # 1) Find the Rightmove URL 
        url = find_listing_url_with_fallback(cleaned)

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "input": {"address": cleaned},
                "data": {
                    "listing_url": url
                },
                "message": "Address processed and URL retrieved successfully."
            }
        )

    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})




