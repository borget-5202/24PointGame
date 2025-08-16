import json
import re
import sys
from typing import List, Dict, Any

RANK_TO_VALUE = {
    "A": 1, "J": 11, "Q": 12, "K": 13,
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "10": 10,
    # In case someone writes lowercase
    "a": 1, "j": 11, "q": 12, "k": 13,
}

def rank_to_value(rank: str) -> int:
    r = rank.strip().strip('"').strip("'")
    if r in RANK_TO_VALUE:
        return RANK_TO_VALUE[r]
    # Fallback: numeric strings like "1", "12"
    if r.isdigit():
        return int(r)
    raise ValueError(f"Unrecognized rank: {rank}")

def parse_block(block: str, idx: int) -> Dict[str, Any]:
    """
    Parse one block of:
        cards:      ['A', 'A', 'A', '10']
        level:      [Easy]
        solutions:  [(expr1; expr2; ...)]
    """
    # cards
    m_cards = re.search(r"cards:\s*\[(.*?)\]", block, flags=re.S)
    if not m_cards:
        raise ValueError(f"Block #{idx}: missing 'cards' line.\n{block}")
    cards_inner = m_cards.group(1)
    # Extract items inside quotes; tolerate single or double quotes
    card_ranks = re.findall(r"'([^']*)'|\"([^\"]*)\"", cards_inner)
    # card_ranks is list of tuples; pick non-empty group from each
    ranks = [(a if a else b) for (a, b) in card_ranks]
    if not ranks:
        # As a fallback, split by comma if quotes were omitted
        ranks = [c.strip().strip("'").strip('"') for c in cards_inner.split(",") if c.strip()]

    # level
    m_level = re.search(r"level:\s*\[(.*?)\]", block, flags=re.S | re.I)
    if not m_level:
        raise ValueError(f"Block #{idx}: missing 'level' line.\n{block}")
    level_raw = m_level.group(1).strip()
    # Remove quotes if any
    level = level_raw.strip("'").strip('"')

    # solutions
    m_solutions = re.search(r"solutions:\s*\[(.*?)\]", block, flags=re.S | re.I)
    if not m_solutions:
        raise ValueError(f"Block #{idx}: missing 'solutions' line.\n{block}")
    sols_inner = m_solutions.group(1).strip()

    solutions: List[str] = []
    if sols_inner:
        # Examples look like: (expr1; expr2; expr3)
        # Remove a single wrapping pair of parentheses if the entire string is enclosed
        if sols_inner.startswith("(") and sols_inner.endswith(")"):
            sols_inner = sols_inner[1:-1].strip()

        # Now split by semicolons that separate expressions
        parts = [p.strip() for p in sols_inner.split(";")]
        # Filter empties and preserve original math punctuation/parentheses
        solutions = [p for p in parts if p]

    data = {
        "id": idx,                         # sequential id (starting at 1)
        "cards": ranks,                    # ranks as given, e.g., ["A","A","A","10"]
        "values": [rank_to_value(r) for r in ranks],  # mapped numeric values
        "level": level,                    # e.g., "Easy" | "Medium" | "Hard"
        "solutions": solutions,            # list of strings; [] if none
    }
    return data

def parse_24pt_file(txt_path: str, json_path: str) -> None:
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    # Split blocks by one or more blank lines
    raw_blocks = re.split(r"Question.*?\s*\n+", content)
    print("raw_blocks ",len(raw_blocks))
    print(raw_blocks[27:30])
    # Filter out empty/whitespace-only blocks
    blocks = [b.strip() for b in raw_blocks if b.strip()]

    results: List[Dict[str, Any]] = []
    for i, block in enumerate(blocks, start=1):
        # Skip non-block noise if any
        if not re.search(r"cards:\s*\[", block, flags=re.I):
            continue
        results.append(parse_block(block, i))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"✅ Parsed {len(results)} puzzles → {json_path}")

def main():
    # CLI: python convert_24pt_txt_to_json.py input.txt output.json
    if len(sys.argv) < 3:
        print("Usage: python convert_24pt_txt_to_json.py <input.txt> <output.json>")
        sys.exit(1)
    parse_24pt_file(sys.argv[1], sys.argv[2])

if __name__ == "__main__":
    main()

