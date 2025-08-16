import json
import random
import time
import ast
import operator
import sys
import csv
import re
from typing import Dict, Any, List

# ----------------------
# Safe expression eval
# ----------------------
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,   # remove this if you want to disallow exponent
}
_ALLOWED_UNARYOPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

RANK_TO_VALUE = {
    "A": 1, "J": 11, "Q": 12, "K": 13,
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9, "10": 10,
    # lowercase fallbacks
    "a": 1, "j": 11, "q": 12, "k": 13,
}

VALUE_TO_RANK = {1: "A", 11: "J", 12: "Q", 13: "K"}

NO_SOLUTION_TOKENS = {"no sol", "nosol", "no solution", "0", "-1"}

# Allow A/J/Q/K directly in formulas
_RANK_TOKEN_MAP = {"A": "1", "J": "11", "Q": "12", "K": "13"}
_RANK_TOKEN_RE = re.compile(r'(?<![A-Za-z0-9_.])([AaJjQqKk])(?![A-Za-z0-9_.])')

def preprocess_ranks(expr: str) -> str:
    def _repl(m):
        ch = m.group(1).upper()
        return _RANK_TOKEN_MAP[ch]
    return _RANK_TOKEN_RE.sub(_repl, expr)

def rank_to_value(rank: str) -> int:
    r = str(rank).strip().strip('"').strip("'")
    if r in RANK_TO_VALUE:
        return RANK_TO_VALUE[r]
    if r.isdigit():
        return int(r)
    raise ValueError(f"Unrecognized rank: {rank}")

def value_to_rank(v: int) -> str:
    return VALUE_TO_RANK.get(int(v), str(int(v)))

def extract_constants(expr: str) -> List[int]:
    """Return all numeric constants used in the expression as integers."""
    expr = preprocess_ranks(expr).replace("^", "**")
    try:
        tree = ast.parse(expr, mode="eval")
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")

    consts: List[int] = []

    class Visitor(ast.NodeVisitor):
        def visit_Constant(self, node: ast.Constant):
            if isinstance(node.value, (int, float)):
                v = node.value
                if isinstance(v, float):
                    if abs(v - round(v)) < 1e-12:
                        consts.append(int(round(v)))
                    else:
                        raise ValueError("Only integer constants are allowed (card values 1–13).")
                else:
                    consts.append(int(v))
            else:
                raise ValueError("Only numeric constants allowed.")

    Visitor().visit(tree)
    return consts

def safe_eval(expr: str) -> float:
    """Evaluate arithmetic expression safely with + - * / ** and parentheses."""
    expr = preprocess_ranks(expr).replace("^", "**")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numeric constants allowed.")
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
            return _ALLOWED_UNARYOPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            left = _eval(node.left)
            right = _eval(node.right)
            op = _ALLOWED_BINOPS[type(node.op)]
            return op(left, right)
        raise ValueError("Unsupported expression.")

    try:
        tree = ast.parse(expr, mode="eval")
        return float(_eval(tree))
    except ZeroDivisionError:
        raise
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")

# ----------------------
# Game helpers
# ----------------------
def load_puzzles(json_path: str) -> List[Dict[str, Any]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON root must be a list of puzzles.")
    return data

def get_values(p: Dict[str, Any]) -> List[int]:
    if "values" in p and isinstance(p["values"], list) and p["values"]:
        return [int(v) for v in p["values"]]
    ranks = p.get("cards", [])
    return [rank_to_value(r) for r in ranks]

def get_ranks_for_display(p: Dict[str, Any]) -> List[str]:
    """Prefer true ranks if present; otherwise derive from numeric values (11->J)."""
    ranks = p.get("cards")
    if ranks and isinstance(ranks, list) and len(ranks) == 4:
        # Normalize to strings; if they are numeric-like, convert 11->J etc.
        vals = []
        mixed_numeric = True
        for x in ranks:
            sx = str(x)
            if sx.isdigit():
                vals.append(int(sx))
            else:
                mixed_numeric = False
                break
        if mixed_numeric:
            return [value_to_rank(v) for v in vals]
        # Already proper ranks like ["A","10","Q","5"]
        return [str(r) for r in ranks]
    # Fallback from numeric values
    return [value_to_rank(v) for v in get_values(p)]

def has_no_solution(p: Dict[str, Any]) -> bool:
    sols = p.get("solutions", [])
    return not sols

def level_of(p: Dict[str, Any]) -> str:
    lvl = p.get("level", "")
    return str(lvl).strip()

def no_1_or_2(values: List[int]) -> bool:
    return 1 not in values and 2 not in values

def filter_base(puzzles: List[Dict[str, Any]], level_choice: str) -> List[Dict[str, Any]]:
    level_choice = level_choice.lower()
    base = []
    if level_choice in ("easy", "1"):
        for p in puzzles:
            if level_of(p) in ("Easy", "Medium") or has_no_solution(p):
                base.append(p)
    elif level_choice in ("medium", "2"):
        for p in puzzles:
            if level_of(p) == "Medium" or has_no_solution(p):
                base.append(p)
    elif level_choice in ("hard", "3"):
        for p in puzzles:
            vals = get_values(p)
            if level_of(p) == "Hard" or no_1_or_2(vals) or has_no_solution(p):
                base.append(p)
    else:
        raise ValueError("Invalid difficulty selection.")
    random.shuffle(base)
    return base

# ----------------------
# UI + timing
# ----------------------
GREETING = "24point - game — use 4 numbers to formula to 24 points"

def show_greeting():
    print("=" * len(GREETING))
    print(GREETING)
    print("=" * len(GREETING))
    print("Type a math expression using + - * / ** and parentheses.")
    print("You can use ranks in formulas: A, J, Q, K (case-insensitive).")
    print("Commands: 'help' (one), 'help all' (all), 'skip' (next), 'time' (elapsed), 'stop' (quit).")
    print("No-solution answers: 'no sol', '0', or '-1'.")
    print("Rule: Your formula must use exactly the four card values shown.")
    print()

def pick_difficulty() -> str:
    while True:
        sel = input("Choose difficulty (easy/1, medium/2, hard/3): ").strip().lower()
        if sel in {"easy", "1", "medium", "2", "hard", "3"}:
            return sel
        print("Please enter: easy or 1, medium or 2, hard or 3.")

def cards_line_for_prompt(p: Dict[str, Any]) -> str:
    ranks = get_ranks_for_display(p)                 # e.g., ["3","5","6","J"]
    values = [rank_to_value(r) for r in ranks]       # e.g., [3,5,6,11]
    ranks_part = f"[{', '.join(ranks)}]"
    values_part = f"(values: {', '.join(map(str, values))})"
    return f"{ranks_part}   {values_part}"

def question_string_for_report(p: Dict[str, Any]) -> str:
    """Use same bracketed rank list for the report."""
    ranks = get_ranks_for_display(p)
    return f"[{', '.join(ranks)}]"

def fmt_secs(sec: float) -> str:
    if sec < 60:
        return f"{sec:.1f}s"
    m = int(sec // 60)
    s = sec - 60 * m
    return f"{m}m{s:04.1f}s"

def multiset_equal(a: List[int], b: List[int]) -> bool:
    return sorted(a) == sorted(b)

def explain_multiset_mismatch(need: List[int], used: List[int]) -> str:
    from collections import Counter
    need_c, used_c = Counter(need), Counter(used)
    extra, missing = [], []
    for k in sorted(set(list(need_c.keys()) + list(used_c.keys()))):
        diff = used_c[k] - need_c[k]
        if diff > 0:
            extra.append(f"{k}x{diff}")
        elif diff < 0:
            missing.append(f"{k}x{-diff}")
    out = []
    if missing: out.append("missing " + ", ".join(missing))
    if extra:   out.append("extra " + ", ".join(extra))
    return "; ".join(out) if out else "numbers mismatch"

def play_round(p: Dict[str, Any], seqno: int) -> Dict[str, Any]:
    """
    Returns record with:
      seqno, question, solved(bool), time_sec(float),
      attempts(int), used_help(bool), solved_via('formula'|'no-solution'|None)
    """
    ranks_display = get_ranks_for_display(p)
    values_needed = get_values(p)
    print(f"\nQ{seqno} — Cards: {cards_line_for_prompt(p)}")

    start = time.time()
    attempts = 0
    used_help = False

    while True:
        user = input("Your answer (or 'help'/'help all'/'skip'/'time'/'stop'): ").strip()
        now = time.time()
        time_used = now - start
        if not user:
            continue

        cmd = user.lower()
        if cmd not in {"time", "help", "help all", "skip", "stop"}:
            attempts += 1

        if cmd == "time":
            print(f"Elapsed: {fmt_secs(time_used)}")
            continue

        if cmd == "stop":
            print("Stopping…")
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": False,
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": None,
                "stopped": True
            }

        if cmd == "skip":
            print(f"Skipped after {fmt_secs(time_used)}.")
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": False,
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": None
            }

        if cmd in {"help", "help all"}:
            sols = p.get("solutions") or []
            used_help = True
            if sols:
                if cmd == "help":
                    print(f"Solution (1/{len(sols)}): {random.choice(sols)}")
                else:
                    print(f"All {len(sols)} solution(s):")
                    for i, s in enumerate(sols, 1):
                        print(f"  {i}. {s}")
            else:
                print("No solution.")
            # auto-advance after showing help
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": False,
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": None
            }

        # No-solution claim
        if user.strip().lower() in NO_SOLUTION_TOKENS:
            if has_no_solution(p):
                print(f"✅ Correct: this puzzle has no solution. ({fmt_secs(time_used)})")
                return {
                    "seqno": seqno,
                    "question": question_string_for_report(p),
                    "solved": True,
                    "time_sec": time_used,
                    "attempts": attempts,
                    "used_help": used_help,
                    "solved_via": "no-solution"
                }
            else:
                print("❌ A solution exists for this puzzle. Use 'help'/'help all' to see it.")
                continue

        # Validate card usage first (must match the four values as a multiset)
        try:
            used_consts = extract_constants(user)
        except ValueError as e:
            print(f"Invalid expression: {e}")
            continue

        if not multiset_equal(used_consts, values_needed):
            print("❌ You must use exactly these four numbers once each.")
            print(f"Expected: {sorted(values_needed)}; Found: {sorted(used_consts)} "
                  f"({explain_multiset_mismatch(values_needed, used_consts)})")
            continue

        # Evaluate numeric expression
        try:
            val = safe_eval(user)
        except ZeroDivisionError:
            print("Invalid: division by zero.")
            continue
        except ValueError as e:
            print(f"Invalid expression: {e}")
            continue

        if abs(val - 24.0) < 1e-9:
            print(f"✅ Correct! ({fmt_secs(time_used)})")
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": True,
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": "formula"
            }
        else:
            print(f"❌ Not 24 (got {val}). Elapsed {fmt_secs(time_used)}. Try again or 'help'/'help all'/'skip'/'time'/'stop'.")

def print_and_save_report(records: List[Dict[str, Any]], csv_path: str = "session_report.csv"):
    if not records:
        return

    print("\nFinal Report")
    print("seqno, question, solved, time, attempts, used_help, solved_via")
    for r in records:
        solved = "Yes" if r.get("solved") else "No"
        used_help = "Yes" if r.get("used_help") else "No"
        solved_via = r.get("solved_via") or ""
        print(f"{r['seqno']}, {r['question']}, {solved}, {fmt_secs(r['time_sec'])}, "
              f"{r.get('attempts', 0)}, {used_help}, {solved_via}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["seqno", "question", "solved", "time_sec", "attempts", "used_help", "solved_via"])
        for r in records:
            writer.writerow([
                r["seqno"], r["question"], int(bool(r.get("solved"))),
                f"{r['time_sec']:.3f}", r.get("attempts", 0),
                int(bool(r.get("used_help"))), r.get("solved_via") or ""
            ])
    print(f"\nSaved report to {csv_path}")

def game_loop(puzzles: List[Dict[str, Any]]):
    if not puzzles:
        print("No puzzles loaded. Exiting.")
        return

    show_greeting()
    sel = pick_difficulty()
    base = filter_base(puzzles, sel)
    if not base:
        print("No puzzles match that difficulty. Exiting.")
        return

    print(f"\nLoaded {len(base)} puzzles for this session.")
    print("Starting…")

    records: List[Dict[str, Any]] = []
    seqno = 1

    while base:
        p = base.pop()
        rec = play_round(p, seqno)
        records.append(rec)
        seqno += 1
        if rec.get("stopped"):
            break

    print_and_save_report(records)
    print()
    show_greeting()

# ----------------------
# Entry
# ----------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python play_24point.py <answers.json>")
        sys.exit(1)
    puzzles = load_puzzles(sys.argv[1])
    game_loop(puzzles)

if __name__ == "__main__":
    main()

