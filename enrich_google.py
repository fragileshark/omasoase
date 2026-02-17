"""
Google Places Enrichment — Stuttgart Care Homes
Matches AOK-scraped facilities against Google Places to add:
  - Google rating (1-5 stars)
  - Review count
  - Top 5 reviews
  - Website URL
  - Google Maps place ID

Usage:
    python3 enrich_google.py

Reads:  data/stuttgart_carehomes.json
Writes: data/stuttgart_enriched.json
        data/stuttgart_enriched.csv
"""

import requests
import json
import csv
import time
import os
import math

API_KEY = "AIzaSyAzVTfLtYgg-ssFLYDKFRCnAAB0TOBOVrk"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
DETAIL_URL = "https://places.googleapis.com/v1/places"
DELAY = 0.3  # seconds between requests
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")


def search_place(name, lat, lon):
    """Search Google Places for a care home by name + location."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": API_KEY,
        "X-Goog-FieldMask": ",".join([
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.rating",
            "places.userRatingCount",
            "places.websiteUri",
            "places.nationalPhoneNumber",
            "places.googleMapsUri",
            "places.reviews",
            "places.photos",
        ])
    }

    body = {
        "textQuery": f"{name} Pflegeheim",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": 2000.0  # 2km radius around known location
            }
        },
        "languageCode": "de",
        "regionCode": "DE",
        "maxResultCount": 3
    }

    resp = requests.post(PLACES_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("places", [])


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance between two points in meters."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def best_match(places, target_lat, target_lon, target_name):
    """Pick the best matching place from search results."""
    if not places:
        return None

    best = None
    best_score = float('inf')

    for p in places:
        loc = p.get("location", {})
        plat = loc.get("latitude", 0)
        plon = loc.get("longitude", 0)

        dist = haversine_m(target_lat, target_lon, plat, plon)

        # Only consider matches within 500m
        if dist > 500:
            continue

        # Prefer closer matches
        if dist < best_score:
            best_score = dist
            best = p

    return best


def extract_reviews(place):
    """Extract review texts from a place result."""
    reviews = place.get("reviews", [])
    extracted = []
    for r in reviews:
        text = r.get("text", {}).get("text", "") if isinstance(r.get("text"), dict) else ""
        extracted.append({
            "rating": r.get("rating", 0),
            "text": text[:500],
            "author": r.get("authorAttribution", {}).get("displayName", ""),
            "time": r.get("relativePublishTimeDescription", ""),
        })
    return extracted


def main():
    # Load AOK data
    with open(os.path.join(OUTPUT_DIR, "stuttgart_carehomes.json"), encoding="utf-8") as f:
        aok_data = json.load(f)

    facilities = aok_data["facilities"]
    print(f"\n=== Google Places Enrichment ===")
    print(f"Enriching {len(facilities)} facilities...\n")

    enriched = []
    matched = 0
    with_rating = 0
    with_website = 0
    with_reviews = 0
    errors = 0

    for i, fac in enumerate(facilities):
        listing = fac["listing"]
        name = listing.get("locationName", "")
        coords = listing.get("coordinates", {})
        lat = coords.get("lat", 0)
        lon = coords.get("lon", 0)
        fid = listing.get("id", "")

        print(f"  [{i+1}/{len(facilities)}] {name[:50]:50s}", end=" ")

        try:
            places = search_place(name, lat, lon)
            match = best_match(places, lat, lon, name)

            google_data = {}
            if match:
                matched += 1
                dist = haversine_m(lat, lon,
                    match.get("location", {}).get("latitude", 0),
                    match.get("location", {}).get("longitude", 0))

                google_data = {
                    "google_place_id": match.get("id", ""),
                    "google_name": match.get("displayName", {}).get("text", ""),
                    "google_address": match.get("formattedAddress", ""),
                    "google_rating": match.get("rating", None),
                    "google_review_count": match.get("userRatingCount", 0),
                    "google_website": match.get("websiteUri", ""),
                    "google_phone": match.get("nationalPhoneNumber", ""),
                    "google_maps_url": match.get("googleMapsUri", ""),
                    "google_match_distance_m": round(dist),
                    "google_reviews": extract_reviews(match),
                    "google_photo_count": len(match.get("photos", [])),
                }

                if google_data["google_rating"]:
                    with_rating += 1
                if google_data["google_website"]:
                    with_website += 1
                if google_data["google_reviews"]:
                    with_reviews += 1

                status = f"MATCH ({dist:.0f}m) rating={google_data['google_rating']} reviews={google_data['google_review_count']} web={'Y' if google_data['google_website'] else 'N'}"
            else:
                status = "NO MATCH"

            print(status)

        except Exception as e:
            print(f"ERROR: {e}")
            google_data = {"error": str(e)}
            errors += 1

        enriched.append({
            "aok_id": fid,
            "name": name,
            "google": google_data,
        })

        time.sleep(DELAY)

    # Save enrichment data
    enriched_path = os.path.join(OUTPUT_DIR, "google_enrichment.json")
    with open(enriched_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {enriched_path}")

    # Merge into a combined CSV
    print(f"\n  Merging with AOK data...")

    # Load existing CSV
    csv_path = os.path.join(OUTPUT_DIR, "stuttgart_carehomes.csv")
    with open(csv_path, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    # Build lookup by AOK id
    google_lookup = {e["aok_id"]: e["google"] for e in enriched}

    # Add google fields to each row
    for row in reader:
        gd = google_lookup.get(row["id"], {})
        row["google_rating"] = gd.get("google_rating", "")
        row["google_review_count"] = gd.get("google_review_count", "")
        row["google_website"] = gd.get("google_website", "")
        row["google_maps_url"] = gd.get("google_maps_url", "")
        row["google_place_id"] = gd.get("google_place_id", "")
        row["google_match_distance_m"] = gd.get("google_match_distance_m", "")
        # Use Google website if AOK doesn't have one
        if not row.get("website") and gd.get("google_website"):
            row["website"] = gd["google_website"]

    # Write enriched CSV
    enriched_csv_path = os.path.join(OUTPUT_DIR, "stuttgart_enriched.csv")
    if reader:
        fieldnames = list(reader[0].keys())
        with open(enriched_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(reader)
    print(f"  Saved: {enriched_csv_path}")

    # Summary
    print(f"\n=== Summary ===")
    print(f"  Total facilities: {len(facilities)}")
    print(f"  Google matches:   {matched} ({matched*100//len(facilities)}%)")
    print(f"  With rating:      {with_rating}")
    print(f"  With website:     {with_website}")
    print(f"  With reviews:     {with_reviews}")
    print(f"  Errors:           {errors}")
    print(f"  Done!")


if __name__ == "__main__":
    main()
