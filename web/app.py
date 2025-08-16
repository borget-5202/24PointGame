# web/app.py
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from typing import Optional, List, Dict, Any
import json as _json
import random
import hashlib

# ---- Import your existing game modules
from game24.picker import QuestionPicker
from game24.card_utils import get_values, get_ranks_for_display
from game24.complexity import preprocess_ranks
from game24.safety_eval import safe_eval_bounded, UnsafeExpression
from game24.card_assets import pick_card_images

# ---- Paths / Config
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_JSON_PATH = BASE_DIR / "data" / "answers.json"
PICTURES_ROOT = BASE_DIR / "pictures"    # filesystem path to your images root
DEFAULT_THEME = "classic"

# ---- App init & static mounts
app = FastAPI(title="Game24 API")
SEQ = 0

# Serve pictures via /assets/<theme>/<code>.png
app.mount("/assets", StaticFiles(directory=str(PICTURES_ROOT)), name="assets")
# Serve the single HTML page from /static
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# ---- Load puzzles once
with open(DATA_JSON_PATH, "r", encoding="utf-8") as f:
    PUZZLES: List[Dict[str, Any]] = _json.load(f)

# One picker instance (session-like behavior within a process)
PICKER = QuestionPicker(PUZZLES, recent_window=60, medium_no_sol_target=0.10)

# Simple per-process sequence number
NEXT_SEQ = 0

def _rng_for(values: List[int], salt: str = "") -> random.Random:
    seed_src = f"{tuple(values)}|{salt}"
    seed = int(hashlib.sha256(seed_src.encode()).hexdigest(), 16) % (10**8)
    return random.Random(seed)

def _find_puzzle_by_values(values_needed: List[int]) -> Optional[Dict[str, Any]]:
    tgt = sorted(int(x) for x in values_needed)
    for p in PUZZLES:
        if sorted(get_values(p)) == tgt:
            return p
    return None

# ---- Models
class NextResponse(BaseModel):
    seq: int
    ranks: List[str]
    values: List[int]
    images: List[Dict[str, Any]]  # {"code":"AS","url":"/assets/classic/AS.png"}
    question: str                 # "[A, 2, 2, 8] (values: 1, 2, 2, 8)"

class CheckRequest(BaseModel):
    values: List[int]
    answer: str

class CheckResponse(BaseModel):
    ok: bool
    value: Optional[float] = None
    reason: Optional[str] = None
    kind: Optional[str] = None  # "formula" | "no-solution" | "help-available"

class HelpRequest(BaseModel):
    values: List[int]
    all: Optional[bool] = False

class HelpResponse(BaseModel):
    solutions: List[str]
    has_solution: bool

# ---- Routes

@app.get("/", response_class=HTMLResponse)
def root():
    index = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(index.read_text(encoding="utf-8"))

@app.get("/api/next", response_model=NextResponse)
def api_next(
    level: str = Query("easy", description="Difficulty level"),
    theme: str = Query("classic", description="Card theme")
):
    #print(f"Request received - Difficulty: {level}, Theme: {theme}")  # Debug log
    
    p = PICKER.pick(level)  # Make sure this uses the 'level' parameter
    if not p:
        raise HTTPException(status_code=404, detail="No puzzles available for this difficulty")
    
    #print(f"Selected puzzle difficulty level: {p.get('level', 'unknown')}")  # Debug log
    #print(f"Selected puzzle str: {str(p)}")  # Debug log
    
    values = get_values(p)
    ranks = get_ranks_for_display(p)
    
    rng = _rng_for(values, salt=theme)
    cards = pick_card_images(values, theme=theme, pictures_root=str(PICTURES_ROOT), rng=rng)
    
    global NEXT_SEQ
    NEXT_SEQ += 1

    return {
        "seq": NEXT_SEQ,
        "ranks": ranks,
        "values": values,
        "images": [{"code": c["code"], "url": f"/assets/{theme}/{c['code']}.png"} for c in cards],
        "question": f"[{', '.join(ranks)}] (values: {', '.join(str(v) for v in values)})",
        "difficulty": p.get("difficulty", "unknown")  # Add this line for debugging
    }



@app.post("/api/check", response_model=CheckResponse)
def api_check(body: CheckRequest):
    values_needed = sorted(int(x) for x in body.values)
    ans = (body.answer or "").strip()

    # No-solution claim
    if ans.lower() in {"no sol", "nosol", "no solution", "0", "-1"}:
        puzzle = _find_puzzle_by_values(values_needed)
        sols_exist = bool(puzzle and puzzle.get("solutions"))
        if not sols_exist:
            return {"ok": True, "value": None, "kind": "no-solution"}
        else:
            return {
                "ok": False,
                "reason": "Try 'help' to see a solution example, 'help all' to see all solutions.",
                "kind": "help-available",
            }

    # Extract integer constants to enforce multiset usage
    import ast
    def extract_constants(expr: str) -> List[int]:
        expr2 = preprocess_ranks(expr).replace("^", "**")
        tree = ast.parse(expr2, mode="eval")
        consts: List[int] = []
        class V(ast.NodeVisitor):
            def visit_Constant(self, node: ast.Constant):
                if isinstance(node.value, (int, float)):
                    v = int(round(float(node.value)))
                    consts.append(v)
        V().visit(tree)
        return consts

    try:
        used_consts = sorted(extract_constants(ans))
    except Exception as e:
        return {"ok": False, "reason": f"Invalid expression: {e}"}

    if used_consts != values_needed:
        return {"ok": False, "reason": f"You must use exactly these numbers {values_needed}. Found {used_consts}."}

    # Evaluate safely
    try:
        val = safe_eval_bounded(preprocess_ranks(ans))
    except UnsafeExpression as e:
        return {"ok": False, "reason": str(e)}
    except ZeroDivisionError:
        return {"ok": False, "reason": "Division by zero."}
    except Exception as e:
        return {"ok": False, "reason": f"Invalid expression: {e}"}

    if abs(val - 24.0) < 1e-9:
        return {"ok": True, "value": val, "kind": "formula"}
    else:
        return {"ok": False, "value": val, "reason": f"Not 24 (got {val})."}

@app.post("/api/help", response_model=HelpResponse)
def api_help(body: HelpRequest):
    try:
        p = _find_puzzle_by_values(body.values)
        if not p:
            return {"solutions": [], "has_solution": False}

        sols = list(p.get("solutions", []))
        if not sols:
            return {"solutions": [], "has_solution": False}

        if body.all:
            return {"solutions": sols, "has_solution": True}
        return {"solutions": [random.choice(sols)], "has_solution": True}
    except Exception as e:
        return {"solutions": [], "has_solution": False}


@app.post("/api/restart")
def api_restart():
    global PICKER, NEXT_SEQ
    try:
        PICKER = QuestionPicker(PUZZLES, recent_window=60, medium_no_sol_target=0.10)
        NEXT_SEQ = 0
        return JSONResponse({"ok": True, "msg": "Pool reset"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

@app.post("/api/exit")
def api_exit():
    return JSONResponse({"ok": True, "msg": "Session ended"})

