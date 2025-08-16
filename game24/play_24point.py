#!/usr/bin/env python3
import json, random, time, ast, sys, csv
from typing import Dict, Any, List
import random, hashlib, json
import webbrowser
#import os, shutil, subprocess, webbrowser
import subprocess, shlex, os

from .card_utils import rank_to_value, value_to_rank, get_values, get_ranks_for_display
from .picker import QuestionPicker
from .complexity import preprocess_ranks
from .safety_eval import safe_eval_bounded, UnsafeExpression

AUTO_PREVIEW = False  # set True later if interop works

def open_html_best_effort(filepath: str):
    """
    Try to open a local HTML file across environments:
    - WSL: use wslview if available
    - Linux desktop: xdg-open / gio open / gnome-open
    - macOS: open
    - Generic: webbrowser
    Falls back to printing the path/URL if nothing works.
    """
    abspath = os.path.abspath(filepath)
    file_url = f"file://{abspath}"

    # 1) WSL first: wslview opens in Windows default browser
    if shutil.which("wslview"):
        try:
            subprocess.run(["wslview", abspath], check=False)
            return
        except Exception:
            pass

    # 2) Linux desktop helpers
    for cmd in (["xdg-open", file_url], ["gio", "open", file_url], ["gnome-open", file_url]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False)
                return
            except Exception:
                continue

    # 3) macOS
    if shutil.which("open"):
        try:
            subprocess.run(["open", file_url], check=False)
            return
        except Exception:
            pass

    # 4) Generic webbrowser (may fail in headless terminals)
    try:
        ok = webbrowser.open(file_url)
        if ok:
            return
    except Exception:
        pass

    # 5) Fallback: tell the user where it is
    print(f"[preview] Open manually: {file_url}")

def _is_wsl() -> bool:
    try:
        with open("/proc/sys/kernel/osrelease","r") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False

def _interop_enabled() -> bool:
    # WSL interop exposes this file when enabled
    return os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")

def open_html_best_effort2(filepath: str):
    abspath = os.path.abspath(filepath)
    file_url = f"file://{abspath}"

    # 1) WSL → use wslview only if interop is enabled
    if _is_wsl() and _interop_enabled() and shutil.which("wslview"):
        try:
            subprocess.run(["wslview", abspath], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass

    # 2) Linux desktop helpers
    for cmd in (["xdg-open", file_url], ["gio", "open", file_url], ["gnome-open", file_url]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue

    # 3) macOS
    if shutil.which("open"):
        try:
            subprocess.run(["open", file_url], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass

    # 4) Generic webbrowser
    try:
        if webbrowser.open(file_url):
            return
    except Exception:
        pass

    print(f"[preview] Open manually: {file_url}")

def open_html_best_effort_wrong(filepath: str):
    """
    Try to open a local HTML file across environments:
    - WSL: use wslview if available
    - Linux desktop: xdg-open / gio open / gnome-open
    - macOS: open
    - Generic: webbrowser
    Falls back to printing the path/URL if nothing works.
    """
    abspath = os.path.abspath(filepath)
    file_url = f"file://{abspath}"

    # 1) WSL first: wslview opens in Windows default browser
    if shutil.which("wslview"):
        try:
            subprocess.run(["wslview", abspath], check=False)
            return
        except Exception:
            pass

    # 2) Linux desktop helpers
    for cmd in (["xdg-open", file_url], ["gio", "open", file_url], ["gnome-open", file_url]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False)
                return
            except Exception:
                continue

    # 3) macOS
    if shutil.which("open"):
        try:
            subprocess.run(["open", file_url], check=False)
            return
        except Exception:
            pass

    # 4) Generic webbrowser (may fail in headless terminals)
    try:
        ok = webbrowser.open(file_url)
        if ok:
            return
    except Exception:
        pass

    # 5) Fallback: tell the user where it is
    print(f"[preview] Open manually: {file_url}")


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

def show_ending(records: List[Dict[str, Any]]):
    # Exclude the final 'stopped' row from performance stats
    eligible = [r for r in records if r.get("status") != "stopped"]

    played = len(eligible)
    solved = sum(1 for r in eligible if r.get("status") in ("solved-formula", "solved-no-solution"))
    revealed = sum(1 for r in eligible if r.get("status") == "revealed")
    skipped = sum(1 for r in eligible if r.get("status") == "skipped")

    times = [r["time_sec"] for r in eligible if "time_sec" in r]
    fastest = min(times) if times else 0.0
    avg = (sum(times) / len(times)) if times else 0.0

    print("\n" + "=" * 56)
    print("Thanks for playing 24‑Point!")
    print("-" * 56)
    print(f" Rounds played  : {played}")
    print(f" Solved         : {solved}  ({(solved/played*100):.0f}%)" if played else " Solved         : 0")
    print(f" Skipped        : {skipped}")
    print(f" Revealed (help): {revealed}")
    print(f" Fastest time   : {fmt_secs(fastest)}")
    print(f" Average time   : {fmt_secs(avg)}")
    print("=" * 56 + "\n")


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
    CURRENT_THEME = "classic"  # "kids" or "seniors"

    print(f"\nQ{seqno} — Cards: {fmt_cards_line(p)}")


    # Optional: show which image files this round would use (for the future web UI)
    try:
        values_key = tuple(get_values(p))  # (1, 1, 9, 13) etc.
        seed_src = f"{values_key}-{seqno}"  # or just values_key if you want same across sessions
        seed = int(hashlib.sha256(json.dumps(seed_src).encode()).hexdigest(), 16) % (10**8)
        rng = random.Random(seed)
        
        
        allow_dup = False if sel in ("hard", "3") else True
        imgs = pick_card_images(get_values(p), theme=CURRENT_THEME,
                        pictures_root="pictures", allow_duplicate_suit=allow_dup, rng=rng)

        img_list = ", ".join(i["code"] for i in imgs)
        # Example: Images (classic): AS, 10H, QC, 4D
        print(f"Images (classic): {img_list}")

    except Exception:
        # If pictures folder isn't set up yet, silently skip
        pass
    
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

        # STOP
        if cmd == "stop":
            print("Stopping…")
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": False,              # kept for backward compat; stats will use 'status'
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": None,
                "status": "stopped",
                "stopped": True
            }
        
        # SKIP
        if cmd == "skip":
            print(f"Skipped after {fmt_secs(time_used)}.")
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": False,
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": None,
                "status": "skipped"
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
                "solved_via": None,
                "status": "revealed"
            }
        
        # NO-SOLUTION claim (correct)
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
                    "solved_via": "no-solution",
                    "status": "solved-no-solution"
                }
            else:
                print("❌ A solution exists for this puzzle. Use 'help'/'help all' to see it.")
                continue

        # Evaluate numeric expression (hardened)
        val = None
        try:
            val = safe_eval_bounded(preprocess_ranks(user))
        except ZeroDivisionError:
            print("Invalid: division by zero.")
            continue
        except Exception as e:
            # catches UnsafeExpression and any other unexpected error paths
            print(f"Invalid expression: {e}")
            continue
        
        # Only reached if val was set
        if abs(val - 24.0) < 1e-9:
            print(f"✅ Correct! ({fmt_secs(time_used)})")
            return {
                "seqno": seqno,
                "question": question_string_for_report(p),
                "solved": True,
                "time_sec": time_used,
                "attempts": attempts,
                "used_help": used_help,
                "solved_via": "formula",
                "status": "solved-formula"
            }
        else:
            print(f"❌ Not 24 (got {val}). Elapsed {fmt_secs(time_used)}. "
                  f"Try again or 'help'/'help all'/'skip'/'time'/'stop'.")
        

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
    print("seqno, question, status, solved, time, attempts, used_help, solved_via")
    for r in records:
        status = r.get("status") or ""
        # For display, don't mark 'stopped' as No — show a dash
        if status == "stopped":
            solved_disp = "—"
        else:
            solved_disp = "Yes" if r.get("solved") else "No"
        used_help = "Yes" if r.get("used_help") else "No"
        solved_via = r.get("solved_via") or ""
        print(f"{r['seqno']}, {r['question']}, {status}, {solved_disp}, {fmt_secs(r['time_sec'])}, "
              f"{r.get('attempts', 0)}, {used_help}, {solved_via}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["seqno", "question", "status", "solved", "time_sec", "attempts", "used_help", "solved_via"])
        for r in records:
            status = r.get("status") or ""
            solved_field = "" if status == "stopped" else int(bool(r.get("solved")))
            w.writerow([
                r["seqno"],
                r["question"],
                status,
                solved_field,
                f"{r['time_sec']:.3f}",
                r.get("attempts", 0),
                int(bool(r.get("used_help"))),
                r.get("solved_via") or ""
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
    show_ending(records)

def main():
    if len(sys.argv) < 2:
        print("Usage: python play_24point.py <answers.json>")
        sys.exit(1)
    puzzles = load_puzzles(sys.argv[1])
    game_loop(puzzles)

if __name__ == "__main__":
    main()

