import json
import re

def parse_24pt_file(txt_path, json_path):
    puzzles = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split each question block
    blocks = re.split(r'Question (\d+): ', content)[1:]  # Skip leading empty
    for i in range(0, len(blocks), 2):
        case_id = int(blocks[i])
        block = blocks[i + 1]

        # Parse card numbers
        card_match = re.match(r'([\d,\s]+)', block)
        cards = list(map(int, card_match.group(1).split(','))) if card_match else []

        # Find all solutions
        solution_lines = re.findall(r'\d+\.\s+(.+)', block)
        solutions = [s.strip() for s in solution_lines]

        # Find level
        level_match = re.search(r'Level\s+--\s+(\w+)', block)
        level = level_match.group(1) if level_match else 'Unknown'

        puzzle = {
            "case_id": case_id,
            "cards": cards,
            "solutions": solutions,
            "level": level
        }
        puzzles.append(puzzle)

    # Save to JSON
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(puzzles, f, indent=2)
    print(f"✅ Converted {len(puzzles)} puzzles to JSON → {json_path}")

# Example usage:
parse_24pt_file("test3.txt", "solution.json")

