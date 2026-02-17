"""
AOK Pflegenavigator Scraper — Stuttgart Region
Scrapes care home data from the AOK Pflegenavigator API.
No authentication required. Public JSON API.

Usage:
    python3 scrape_aok.py

Output:
    data/stuttgart_carehomes.json   — Full detailed data for all facilities
    data/stuttgart_carehomes.csv    — Flat CSV for quick analysis
"""

import requests
import json
import csv
import time
import os
from datetime import datetime

# --- Config ---
API_BASE = "https://navigatoren-api.aok.de/api/v1"
PLZ = "70173"           # Stuttgart center
RADIUS = 25000          # 25km — covers Region Stuttgart
PAGE_SIZE = 100         # Max allowed by API
DELAY = 0.5             # Seconds between detail requests (be respectful)
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}


def fetch_list(care_type=None):
    """Fetch all care homes in the Stuttgart region from the list endpoint."""
    all_results = []
    offset = 0

    while True:
        params = {
            "location": PLZ,
            "radius": RADIUS,
            "from": offset,
            "size": PAGE_SIZE,
        }
        if care_type:
            params["carehomes_care_typ"] = care_type

        url = f"{API_BASE}/carehomes"
        print(f"  Fetching list: offset={offset} ...", end=" ")
        resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        total = data.get("count", 0)
        all_results.extend(results)
        print(f"got {len(results)} (total: {total})")

        offset += PAGE_SIZE
        if offset >= total:
            break
        time.sleep(DELAY)

    return all_results, total


def fetch_detail(facility_id):
    """Fetch full detail for a single care home."""
    url = f"{API_BASE}/carehome/{facility_id}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def extract_flat_record(listing, detail):
    """Extract a flat dict from listing + detail data for CSV export."""
    address = listing.get("address", {})
    coords = listing.get("coordinates", {})

    # Parse Eigenanteil from contribution array
    eigenanteil = ""
    contributions = listing.get("contribution", [])
    for c in contributions:
        if c.get("type") == "personalContribution":
            eigenanteil = c.get("amount", "")
            break

    # Detail is nested under detail -> result -> details
    result_obj = detail.get("result", {}) if detail else {}
    det = result_obj.get("details", {}) if result_obj else {}

    # --- Pricing per Pflegegrad (the good stuff) ---
    prices = det.get("prices", {})
    ltc = prices.get("longTermCare", {}) if isinstance(prices, dict) else {}
    stc = prices.get("shortTermCare", {}) if isinstance(prices, dict) else {}

    # Extract per-Pflegegrad pricing from longTermCare
    price_per_pg = {}
    if isinstance(ltc, dict):
        care_focuses = ltc.get("careFocus", [])
        if isinstance(care_focuses, list):
            for focus in care_focuses:
                if isinstance(focus, dict):
                    for cl in focus.get("careLevels", []):
                        if isinstance(cl, dict):
                            pg = cl.get("careLevel", "")
                            price_per_pg[f"pg{pg}_total_month"] = cl.get("priceMonth", "")
                            price_per_pg[f"pg{pg}_eigenanteil"] = cl.get("ownShare", "")
                            price_per_pg[f"pg{pg}_housing_care"] = cl.get("housingAndCare", "")
                            price_per_pg[f"pg{pg}_invest"] = cl.get("invest", "")
                    break  # Take first focus (usually "Kein besonderer Schwerpunkt")

    has_kurzzeitpflege = bool(stc)

    # --- Staffing ratios ---
    staffing = det.get("personalausstattung", {})
    staff_ratio = ""
    if isinstance(staffing, dict):
        vereinbart = staffing.get("vereinbartePersonalausstattung", {})
        if isinstance(vereinbart, dict):
            table = vereinbart.get("table", {})
            if isinstance(table, dict):
                rows = table.get("data", [])
                if isinstance(rows, list) and rows:
                    staff_ratio = "; ".join(
                        f"{r.get('level','')}: {r.get('key','')}"
                        for r in rows if isinstance(r, dict)
                    )

    # --- Equipment / amenities ---
    equipment = det.get("equipment", {})
    facility_items = []
    room_items = []
    construction_year = ""
    if isinstance(equipment, dict):
        construction_year = equipment.get("constructionYear", "")
        items = equipment.get("items", [])
        if isinstance(items, list):
            facility_items = [i for i in items if isinstance(i, str)]
        ritems = equipment.get("roomItems", [])
        if isinstance(ritems, list):
            room_items = [i for i in ritems if isinstance(i, str)]

    # --- Offers / services ---
    offers = det.get("offers", {})
    care_offers = []
    if isinstance(offers, dict):
        for ol in offers.get("offerLists", []):
            if isinstance(ol, dict):
                items = ol.get("items", [])
                if isinstance(items, list):
                    care_offers.extend(i for i in items if isinstance(i, str))
                add_info = ol.get("additionalInfo", "")
                if add_info and isinstance(add_info, str):
                    care_offers.append(add_info.strip())

    # --- Meals ---
    meals = det.get("mealInformation", {})
    meal_info = ""
    if isinstance(meals, dict):
        items = meals.get("items", [])
        if isinstance(items, list):
            meal_info = "; ".join(i for i in items if isinstance(i, str))

    # --- Photos ---
    photos = det.get("slideshowOffice", [])
    photo_urls = []
    if isinstance(photos, list):
        photo_urls = [p for p in photos if isinstance(p, str)]

    # --- Quality report ---
    quality_report_url = ""
    qr = det.get("qualityReport", {})
    if isinstance(qr, dict):
        quality_report_url = qr.get("url", "")

    # --- Quality indicators ---
    quality = det.get("quality", {})
    quality_score = ""
    if isinstance(quality, dict):
        qi = quality.get("qualityIndicators", {})
        if isinstance(qi, dict):
            quality_score = json.dumps(qi, ensure_ascii=False)[:200]

    # --- Visiting ---
    visiting_always = det.get("visitingAlwaysPossible", False)
    visiting_hours = det.get("visitingHours", "") or ""

    # --- Accessibility ---
    accessibility = det.get("accessibility", {})
    accessibility_str = ""
    if isinstance(accessibility, dict):
        desc = accessibility.get("description", "")
        if desc:
            accessibility_str = desc

    # --- Contact persons ---
    contact_persons = result_obj.get("contactPersons", [])
    contact_str = "; ".join(
        f"{c.get('name', '')} ({c.get('function', '')})"
        for c in contact_persons if isinstance(c, dict)
    ) if isinstance(contact_persons, list) else ""

    # --- General contact info from detail ---
    allg = det.get("allgemeineInformationen", {})
    detail_email = ""
    detail_website = ""
    if isinstance(allg, dict):
        detail_email = allg.get("email", "") or ""

    # Last update
    last_update = result_obj.get("lastUpdate", "")
    website = listing.get("website", "") or result_obj.get("website", "") or ""
    email = listing.get("email", "") or result_obj.get("email", "") or detail_email

    record = {
        "id": listing.get("id", ""),
        "name": listing.get("locationName", ""),
        "street": address.get("street", ""),
        "zip": address.get("zip", ""),
        "city": address.get("city", ""),
        "lat": coords.get("lat", ""),
        "lon": coords.get("lon", ""),
        "distance_m": listing.get("distance", ""),
        "phone": listing.get("phone", ""),
        "email": email,
        "website": website,
        "care_type": listing.get("resultLabel", ""),
        "has_kurzzeitpflege": has_kurzzeitpflege,
        "eigenanteil_display": eigenanteil,
        # Per-Pflegegrad pricing
        **{k: v for k, v in price_per_pg.items()},
        # Staffing
        "staff_ratio": staff_ratio,
        # Building
        "construction_year": construction_year,
        "facility_amenities": "; ".join(facility_items),
        "room_amenities": "; ".join(room_items),
        # Services & meals
        "services": "; ".join(care_offers),
        "meal_info": meal_info,
        # Quality
        "quality_report_url": quality_report_url,
        # Photos
        "photo_count": len(photo_urls),
        "photo_urls": "; ".join(photo_urls[:5]),
        # Visiting
        "visiting_always": visiting_always,
        "visiting_hours": visiting_hours,
        # Accessibility
        "accessibility": accessibility_str,
        # Contact
        "contact_persons": contact_str,
        "last_update": last_update,
    }
    return record


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Step 1: Fetch all care homes in Stuttgart region
    print(f"\n=== AOK Pflegenavigator Scraper ===")
    print(f"Region: PLZ {PLZ}, Radius {RADIUS/1000:.0f}km")
    print(f"\n[1/3] Fetching facility list...")
    listings, total = fetch_list()
    print(f"  Found {len(listings)} facilities (API reports {total} total)")

    # Step 2: Fetch detail for each facility
    print(f"\n[2/3] Fetching details for each facility...")
    full_data = []
    flat_records = []
    errors = []

    for i, listing in enumerate(listings):
        fid = listing.get("id", "unknown")
        name = listing.get("locationName", "unknown")
        print(f"  [{i+1}/{len(listings)}] {name} (ID: {fid})", end=" ")

        try:
            detail = fetch_detail(fid)
            full_data.append({"listing": listing, "detail": detail})
            flat_records.append(extract_flat_record(listing, detail))
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append({"id": fid, "name": name, "error": str(e)})
            full_data.append({"listing": listing, "detail": None})
            flat_records.append(extract_flat_record(listing, None))

        time.sleep(DELAY)

    # Step 3: Save outputs
    print(f"\n[3/3] Saving data...")

    # Full JSON (all raw data)
    json_path = os.path.join(OUTPUT_DIR, "stuttgart_carehomes.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "scraped_at": datetime.now().isoformat(),
            "search": {"plz": PLZ, "radius_m": RADIUS},
            "total_count": total,
            "facilities": full_data,
            "errors": errors,
        }, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {json_path} ({len(full_data)} facilities)")

    # Flat CSV for analysis
    csv_path = os.path.join(OUTPUT_DIR, "stuttgart_carehomes.csv")
    if flat_records:
        fieldnames = flat_records[0].keys()
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat_records)
    print(f"  CSV:  {csv_path} ({len(flat_records)} rows)")

    # Summary
    with_website = sum(1 for r in flat_records if r.get("website"))
    with_eigenanteil = sum(1 for r in flat_records if r.get("eigenanteil"))
    with_phone = sum(1 for r in flat_records if r.get("phone"))

    print(f"\n=== Summary ===")
    print(f"  Total facilities: {len(flat_records)}")
    print(f"  With phone:       {with_phone}")
    print(f"  With website:     {with_website}")
    print(f"  With Eigenanteil: {with_eigenanteil}")
    print(f"  Errors:           {len(errors)}")
    print(f"  Done!")


if __name__ == "__main__":
    main()
