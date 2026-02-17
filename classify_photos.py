"""Classify care home photos: has people or not."""
import csv, json, base64, os, time
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Collect all photo URLs
with open(os.path.join(DATA_DIR, "stuttgart_final.csv"), encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

all_urls = []
for r in rows:
    urls = [u.strip() for u in r.get("photo_urls", "").split(";") if u.strip().startswith("http")]
    all_urls.extend(urls)

print(f"Total photos to classify: {len(all_urls)}")

# Classify in batches of 5 images per API call
people_urls = []
no_people_urls = []
BATCH_SIZE = 5

for batch_start in range(0, len(all_urls), BATCH_SIZE):
    batch = all_urls[batch_start:batch_start + BATCH_SIZE]
    print(f"  Batch {batch_start // BATCH_SIZE + 1}/{(len(all_urls) + BATCH_SIZE - 1) // BATCH_SIZE}...", end=" ")

    # Build content with image URLs
    content = []
    for i, url in enumerate(batch):
        content.append({"type": "image", "source": {"type": "url", "url": url}})
        content.append({"type": "text", "text": f"Image {i+1}"})

    content.append({
        "type": "text",
        "text": "For each image above, answer ONLY with the image number and YES or NO. Say YES only if people are a PROMINENT subject — clearly visible faces, groups interacting, or caregiving scenes. Say NO for building exteriors, rooms, furniture, gardens, hallways, or any photo where people are tiny/background figures. When in doubt, say NO. Format: 1:YES 2:NO etc."
    })

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        answer = resp.json()["content"][0]["text"].strip()
        print(answer)

        # Parse answers
        for i, url in enumerate(batch):
            if f"{i+1}:YES" in answer or f"{i+1}: YES" in answer:
                people_urls.append(url)
            else:
                no_people_urls.append(url)

    except Exception as e:
        print(f"ERROR: {e}")
        # Skip batch on error

    time.sleep(0.5)

# Save results
output = {
    "people_photos": people_urls,
    "no_people_photos": no_people_urls,
    "total": len(all_urls),
    "with_people": len(people_urls),
}

out_path = os.path.join(DATA_DIR, "photo_classification.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)

print(f"\nDone! {len(people_urls)} with people, {len(no_people_urls)} without")
print(f"Saved to {out_path}")
