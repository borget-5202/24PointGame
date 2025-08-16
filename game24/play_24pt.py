#!/usr/bin/env python3
import json
import random
import time
import ast
import operator
import sys
import csv
import re
from typing import Dict, Any, List

# --- imports from your helper modules ---
from card_utils import rank_to_value, value_to_rank, get_values, get_ranks_for_display
from picker import QuestionPicker
from complexity import preprocess_ranks
from safety_eval import safe_eval_bounded, UnsafeExpression


# ----------------------
# Config / constants
# ----------------------
NO_SOLUTION_TOKENS = {"no sol", "nosol", "no solution", "0", "-1"}

# Display mapping for numeric -> rank
VALUE_TO_RANK = {1: "A", 11: "J", 12: "Q", 13: "K"}

GREETING = "24point - game — use 4 numbers to formula to 24 points"

# ----------------------
# Basic helpers
# ----------------------

def load_puzzles(json_path: str) -> List[Dict[str, Any]]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON root must be a list.")
    return data


def fmt_cards_line(p: Dict[str, Any]) -> str:
    ranks = get_ranks_for_display(p)                  # e.g., ["3","5","6","J"]
    values = [rank_to_value(r) for r in ranks]        # e.g., [3,5,6,11]
    return f"[{', '.join(ranks)}]   (values: {', '.join(map(str, values))})"

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

# Extract constants used in user's expression (for multiset check)
def extract_constants(expr: str) -> List[int]:
    expr = preprocess_ranks(expr).replace("^", "**")
    try:
        tree = ast.parse(expr, mode="eval")
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")
    consts: List[int] = []
    class V(ast.NodeVisitor):
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
    V().visit(tree)
    return consts

# ----------------------
# UI
# ----------------------
def show_greeting():
    print("=" * len(GREETING))
    print(GREETING)
    print("=" * len(GREETING))
    print("Type a math expression using + - * / ** and parentheses.")
    print("Ranks allowed directly in formulas: A, J, Q, K (case-insensitive).")
    print("Commands: 'help' (one), 'help all' (all), 'skip' (next), 'time' (elapsed), 'stop' (quit).")
    print("No-solution answers: 'no sol', '0', or '-1'.")
    print("Rule: Your formula must use exactly the four card values shown.\n")

def pick_difficulty() -> str:
    while True:
        sel = input("Choose difficulty (easy/1, medium/2, hard/3): ").strip().lower()
        if sel in {"easy", "1", "medium", "2", "hard", "3"}:
            return sel
        print("Please enter: easy or 1, medium or 2, hard or 3.")

def question_string_for_report(p: Dict[str, Any]) -> str:
    ranks = get_ranks_for_display(p)
    return f"[{', '.join(ranks)}]"

# ----------------------
# Round gameplay
# ----------------------
def play_round(p: Dict[str, Any], seqno: int) -> Dict[str, Any]:
    """
    Returns record with:
      seqno, question, solved(bool), time_sec(float),
      attempts(int), used_help(bool), solved_via('formula'|'no-solution'|None)
    """
    print(f"\nQ{seqno} — Cards: {fmt_cards_line(p)}")
    values_needed = get_values(p)
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
            if not p.get("solutions"):
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

        # Evaluate numeric expression (hardened)
        try:
            val = safe_eval_bounded(preprocess_ranks(user))
        except UnsafeExpression as e:
            print(f"Invalid expression: {e}")
            continue
        except ZeroDivisionError:
            print("Invalid: division by zero.")
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
            print(f"❌ Not 24 (got {val}). Elapsed {fmt_secs(time_used)}. "
                  f"Try again or 'help'/'help all'/'skip'/'time'/'stop'.")

# ----------------------
# Report
# ----------------------
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
        w = csv.writer(f)
        w.writerow(["seqno", "question", "solved", "time_sec", "attempts", "used_help", "solved_via"])
        for r in records:
            w.writerow([
                r["seqno"], r["question"], int(bool(r.get("solved"))),
                f"{r['time_sec']:.3f}", r.get("attempts", 0),
                int(bool(r.get("used_help"))), r.get("solved_via") or ""
            ])
    print(f"\nSaved report to {csv_path}")

# ----------------------
# Main loop
# ----------------------
def game_loop(puzzles: List[Dict[str, Any]]):
    if not puzzles:
        print("No puzzles loaded. Exiting.")
        return

    show_greeting()
    sel = pick_difficulty()

    # Build smart picker:
    #   - medium_no_sol_target = 0.10 (10%)
    #   - recent_window = 60 (avoid repeats of last 60 by numeric combo)
    qp = QuestionPicker(puzzles, recent_window=60, medium_no_sol_target=0.10)

    print("\nStarting…")
    records: List[Dict[str, Any]] = []
    seqno = 1

    while True:
        p = qp.pick(sel)
        if not p:
            print("\nNo more puzzles available for this difficulty (given constraints).")
            break
        rec = play_round(p, seqno)
        records.append(rec)
        seqno += 1
        if rec.get("stopped"):
            break

    print_and_save_report(records)
    print()
    show_greeting()

def main():
    if len(sys.argv) < 2:
        print("Usage: python play_24point.py <answers.json>")
        sys.exit(1)
    puzzles = load_puzzles(sys.argv[1])
    game_loop(puzzles)

if __name__ == "__main__":
    main()

