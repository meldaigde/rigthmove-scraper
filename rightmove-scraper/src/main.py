import sys
from pathlib import Path

# Add project root and src folder to PYTHONPATH dynamically
ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "rightmove_scraper"
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(SRC_DIR))

from rightmove_scraper.url_scraper import fetch_property_summary
from rightmove_scraper.address_search import find_listing_url_with_fallback

if __name__ == "__main__":
    address = input("Enter full or partial address: ")

    url = find_listing_url_with_fallback(address)
    print("\nFound URL:", url)

    if url:
        data = fetch_property_summary(url)
        print("\nProperty Summary:")
        print(data)





