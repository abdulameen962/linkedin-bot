import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

TAGS_FILE = os.path.join(os.path.dirname(__file__), "tags.json")

def load_tags() -> List[Dict[str, Any]]:
    if not os.path.exists(TAGS_FILE):
        return []
    with open(TAGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_tags(tags: List[Dict[str, Any]]) -> None:
    with open(TAGS_FILE, "w", encoding="utf-8") as f:
        json.dump(tags, f, indent=2, ensure_ascii=False)

def get_next_search_tag() -> Optional[Dict[str, Any]]:
    tags = load_tags()
    if not tags:
        return None
    # Sort by priority descending, then by times_used ascending
    sorted_tags = sorted(tags, key=lambda t: (-t.get("priority", 0), t.get("times_used", 0)))
    return sorted_tags[0]

def record_tag_usage(tag_str: str) -> None:
    tags = load_tags()
    for t in tags:
        if t["tag"] == tag_str:
            t["times_used"] = t.get("times_used", 0) + 1
            t["last_used_at"] = datetime.now(timezone.utc).isoformat()
            break
    save_tags(tags)

def update_tag_priorities(ranked_tags: List[Dict[str, Any]]) -> None:
    """
    ranked_tags: list of dicts with keys "tag", "priority", and optional "is_dynamic", "category"
    Updates existing tags or appends new dynamic tags.
    """
    existing_tags = load_tags()
    tag_map = {t["tag"].lower().strip(): t for t in existing_tags}

    for item in ranked_tags:
        tag_str = item.get("tag", "").strip()
        if not tag_str:
            continue
        priority = item.get("priority", 50)
        category = item.get("category", "dynamic")
        is_dynamic = item.get("is_dynamic", True)

        key = tag_str.lower()
        if key in tag_map:
            tag_map[key]["priority"] = priority
            if "category" in item:
                tag_map[key]["category"] = category
        else:
            new_entry = {
                "tag": tag_str,
                "priority": priority,
                "category": category,
                "is_dynamic": is_dynamic,
                "times_used": 0,
                "last_used_at": None
            }
            existing_tags.append(new_entry)
            tag_map[key] = new_entry

    save_tags(existing_tags)

if __name__ == "__main__":
    next_tag = get_next_search_tag()
    print("Next search tag:", next_tag)
