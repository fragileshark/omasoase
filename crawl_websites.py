"""
Crawl4AI Website Enrichment — Stuttgart Care Homes
Crawls each care home's website and uses Claude to extract structured data
that isn't available in the AOK directory.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 crawl_websites.py

Reads:  data/stuttgart_enriched.csv
Writes: data/website_extractions.json
        data/stuttgart_final.csv
"""

import asyncio
import json
import csv
import os
import time
from datetime import datetime
from dotenv import load_dotenv

# Load .env file
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

# Crawl4AI imports
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from pydantic import BaseModel, Field

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Max concurrent crawls and delay
CONCURRENT = 5
DELAY_BETWEEN = 1.0


# --- Schema: what we want to extract from each website ---
class CareHomeWebData(BaseModel):
    verfuegbare_plaetze: str = Field(
        default="",
        description="Any mention of available beds/places (freie Plätze), waiting list (Warteliste), or current availability. Quote the exact text if found."
    )
    preise_details: str = Field(
        default="",
        description="Any pricing information: monthly costs, Eigenanteil, Pflegesätze, Investitionskosten, or fee schedules. Include specific numbers if found."
    )
    zimmer_typen: str = Field(
        default="",
        description="Types of rooms available: Einzelzimmer (single), Doppelzimmer (double), apartment sizes, room features."
    )
    pflegeangebote: str = Field(
        default="",
        description="Care services offered: Langzeitpflege, Kurzzeitpflege, Verhinderungspflege, Tagespflege, Demenzbetreuung, Palliativpflege, Junge Pflege."
    )
    besondere_schwerpunkte: str = Field(
        default="",
        description="Specializations: dementia care (Demenz), palliative care, young care (Junge Pflege), ventilation care (Beatmungspflege), psychiatric care."
    )
    aktivitaeten: str = Field(
        default="",
        description="Activities and programs offered: therapy, music, art, garden, outings, exercise programs, social events."
    )
    lage_umgebung: str = Field(
        default="",
        description="Description of location and surroundings: garden, park, nearby shops, public transport, neighborhood character."
    )
    traeger: str = Field(
        default="",
        description="Operator/owner (Träger): organization name, type (kirchlich/diakonisch/privat/kommunal), group affiliation."
    )
    besonderheiten: str = Field(
        default="",
        description="Any unique selling points, special features, awards, certifications, or notable qualities mentioned on the website."
    )
    kontakt_details: str = Field(
        default="",
        description="Contact details found: specific contact person names, email addresses, phone numbers, office hours for inquiries."
    )


async def crawl_batch(facilities, start_idx=0):
    """Crawl a batch of care home websites and extract data with Claude."""

    llm_strategy = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider="anthropic/claude-sonnet-4-5-20250929",
            api_token=ANTHROPIC_KEY,
        ),
        schema=CareHomeWebData.model_json_schema(),
        extraction_type="schema",
        instruction="""Du analysierst die Webseite eines deutschen Pflegeheims / Seniorenheims.
Extrahiere alle relevanten Informationen für Familien, die einen Pflegeplatz suchen.
Besonders wichtig: Verfügbarkeit von Plätzen, Preise/Kosten, Zimmertypen, und besondere Pflegeangebote.
Wenn eine Information nicht auf der Seite zu finden ist, lass das Feld leer.
Antworte auf Deutsch.""",
        extra_args={"temperature": 0.0, "max_tokens": 1500},
        chunk_token_threshold=4000,
        overlap_rate=0.1,
        apply_chunking=True,
        input_format="markdown",
    )

    browser_config = BrowserConfig(
        headless=True,
        text_mode=True,  # faster, skip images/css
    )

    crawl_config = CrawlerRunConfig(
        extraction_strategy=llm_strategy,
        cache_mode=CacheMode.BYPASS,
        page_timeout=30000,
        word_count_threshold=50,
    )

    results = []
    errors = []

    async with AsyncWebCrawler(config=browser_config) as crawler:
        for i, fac in enumerate(facilities):
            idx = start_idx + i
            name = fac["name"]
            url = fac["website"]
            aok_id = fac["id"]

            print(f"  [{idx+1}/{len(facilities)+start_idx}] {name[:45]:45s} {url[:50]}", end=" ")

            try:
                result = await crawler.arun(url=url, config=crawl_config)

                if result.success and result.extracted_content:
                    try:
                        extracted = json.loads(result.extracted_content)
                        # LLM extraction returns a list, take first item
                        if isinstance(extracted, list) and extracted:
                            extracted = extracted[0]

                        # Count non-empty fields
                        filled = sum(1 for v in extracted.values() if v and str(v).strip())
                        print(f"OK ({filled}/10 fields)")

                        results.append({
                            "aok_id": aok_id,
                            "name": name,
                            "url": url,
                            "extracted": extracted,
                            "markdown_length": len(result.markdown.raw_markdown) if result.markdown else 0,
                        })
                    except json.JSONDecodeError:
                        print(f"JSON ERROR")
                        errors.append({"aok_id": aok_id, "name": name, "url": url, "error": "JSON decode failed"})
                elif result.success:
                    print("NO CONTENT")
                    errors.append({"aok_id": aok_id, "name": name, "url": url, "error": "No extracted content"})
                else:
                    print(f"CRAWL FAIL: {result.error_message[:60] if result.error_message else 'unknown'}")
                    errors.append({"aok_id": aok_id, "name": name, "url": url, "error": result.error_message})

            except Exception as e:
                print(f"ERROR: {str(e)[:60]}")
                errors.append({"aok_id": aok_id, "name": name, "url": url, "error": str(e)})

            # Save progress every 20 sites
            if (i + 1) % 20 == 0:
                save_progress(results, errors)

            await asyncio.sleep(DELAY_BETWEEN)

    return results, errors


def save_progress(results, errors):
    """Save intermediate results."""
    path = os.path.join(DATA_DIR, "website_extractions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "extracted_at": datetime.now().isoformat(),
            "count": len(results),
            "errors": len(errors),
            "results": results,
            "error_list": errors,
        }, f, ensure_ascii=False, indent=2)


def merge_to_final_csv(extractions):
    """Merge website extractions into the enriched CSV."""
    # Load enriched CSV
    csv_path = os.path.join(DATA_DIR, "stuttgart_enriched.csv")
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Build lookup
    extraction_lookup = {}
    for ext in extractions:
        extraction_lookup[ext["aok_id"]] = ext.get("extracted", {})

    # Add extraction fields to rows
    extract_fields = [
        "verfuegbare_plaetze", "preise_details", "zimmer_typen",
        "pflegeangebote", "besondere_schwerpunkte", "aktivitaeten",
        "lage_umgebung", "traeger", "besonderheiten", "kontakt_details"
    ]

    for row in rows:
        ext = extraction_lookup.get(row["id"], {})
        for field in extract_fields:
            row[f"web_{field}"] = ext.get(field, "")

    # Write final CSV
    final_path = os.path.join(DATA_DIR, "stuttgart_final.csv")
    if rows:
        fieldnames = list(rows[0].keys())
        with open(final_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    print(f"  Saved: {final_path}")
    return final_path


async def main():
    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        return

    # Load facilities with websites
    csv_path = os.path.join(DATA_DIR, "stuttgart_enriched.csv")
    with open(csv_path, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    facilities = []
    seen_urls = set()
    for r in reader:
        url = r.get("website", "").strip()
        if url.startswith("http") and url not in seen_urls:
            facilities.append({"id": r["id"], "name": r["name"], "website": url})
            seen_urls.add(url)

    print(f"\n=== Crawl4AI Website Extraction ===")
    print(f"Facilities with unique websites: {len(facilities)}")
    print(f"LLM: Claude Sonnet 4.5 via Anthropic")
    print(f"Estimated cost: ~${len(facilities) * 0.02:.2f}")
    print()

    # Check for existing progress
    progress_path = os.path.join(DATA_DIR, "website_extractions.json")
    existing_ids = set()
    existing_results = []
    existing_errors = []

    if os.path.exists(progress_path):
        with open(progress_path, encoding="utf-8") as f:
            progress = json.load(f)
            existing_results = progress.get("results", [])
            existing_errors = progress.get("error_list", [])
            existing_ids = {r["aok_id"] for r in existing_results}
            print(f"  Resuming: {len(existing_results)} already done, {len(existing_errors)} errors")

    # Filter out already-done facilities
    remaining = [f for f in facilities if f["id"] not in existing_ids]
    print(f"  Remaining to crawl: {len(remaining)}")
    print()

    if not remaining:
        print("  All done! Merging to final CSV...")
        merge_to_final_csv(existing_results)
        return

    # Crawl
    results, errors = await crawl_batch(remaining, start_idx=len(existing_results))

    # Combine with existing
    all_results = existing_results + results
    all_errors = existing_errors + errors

    # Save final extraction JSON
    save_progress(all_results, all_errors)
    print(f"\n  Extractions saved: {len(all_results)} success, {len(all_errors)} errors")

    # Show LLM usage
    print()
    print("=== Merging to final CSV ===")
    merge_to_final_csv(all_results)

    # Summary stats
    total_fields = 0
    filled_fields = 0
    for r in all_results:
        ext = r.get("extracted", {})
        for v in ext.values():
            total_fields += 1
            if v and str(v).strip():
                filled_fields += 1

    print(f"\n=== Summary ===")
    print(f"  Websites crawled: {len(all_results)}")
    print(f"  Errors: {len(all_errors)}")
    print(f"  Data fields filled: {filled_fields}/{total_fields} ({filled_fields*100//max(total_fields,1)}%)")
    print(f"  Done!")


if __name__ == "__main__":
    asyncio.run(main())
