from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3, os, datetime, json

class UTF8JSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")

app = FastAPI(title="Согым App API", default_response_class=UTF8JSONResponse)

DB = os.path.join(os.path.dirname(__file__), "sogym.db")

ANIMAL_CONFIG = {
    "cow":   {"name": "🐄 Сиыр",   "shares": 4, "weight": 200, "default_price": 2500},
    "horse": {"name": "🐎 Жылқы",  "shares": 4, "weight": 220, "default_price": 3000},
    "sheep": {"name": "🐑 Қой",    "shares": 2, "weight": 45,  "default_price": 2000},
}


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            animal TEXT NOT NULL,
            price_per_kg INTEGER NOT NULL,
            weight INTEGER NOT NULL,
            shares INTEGER NOT NULL,
            event_date TEXT,
            location TEXT,
            owner_name TEXT NOT NULL,
            owner_phone TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            shares INTEGER DEFAULT 1,
            paid INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(purchase_id, phone)
        );
        """)


init_db()


# ── Models ──────────────────────────────────
class CreatePurchase(BaseModel):
    title: str
    animal: str
    price_per_kg: int
    event_date: Optional[str] = None
    location: Optional[str] = None
    owner_name: str
    owner_phone: str


class JoinPurchase(BaseModel):
    name: str
    phone: str


class MarkPaid(BaseModel):
    owner_phone: str
    participant_phone: str


# ── Helpers ─────────────────────────────────
def purchase_detail(pid: int):
    with db() as c:
        p = c.execute("SELECT * FROM purchases WHERE id=?", (pid,)).fetchone()
        if not p:
            return None
        parts = c.execute("SELECT * FROM participants WHERE purchase_id=?", (pid,)).fetchall()

    cfg = ANIMAL_CONFIG.get(p["animal"], {})
    taken = sum(x["shares"] for x in parts)
    free = p["shares"] - taken
    price_per_share = p["price_per_kg"] * p["weight"] // p["shares"]

    return {
        "id": p["id"],
        "title": p["title"],
        "animal": p["animal"],
        "animal_name": cfg.get("name", p["animal"]),
        "price_per_kg": p["price_per_kg"],
        "weight": p["weight"],
        "shares": p["shares"],
        "taken": taken,
        "free": free,
        "price_per_share": price_per_share,
        "event_date": p["event_date"],
        "location": p["location"],
        "owner_name": p["owner_name"],
        "owner_phone": p["owner_phone"],
        "status": p["status"],
        "created_at": p["created_at"],
        "participants": [dict(x) for x in parts],
    }


# ── Routes ──────────────────────────────────
@app.get("/api/purchases")
def list_purchases(status: str = "open"):
    with db() as c:
        rows = c.execute(
            "SELECT p.*, (SELECT SUM(shares) FROM participants WHERE purchase_id=p.id) as taken "
            "FROM purchases p WHERE status=? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
    result = []
    for p in rows:
        cfg = ANIMAL_CONFIG.get(p["animal"], {})
        taken = p["taken"] or 0
        result.append({
            "id": p["id"],
            "title": p["title"],
            "animal_name": cfg.get("name", p["animal"]),
            "animal": p["animal"],
            "shares": p["shares"],
            "taken": taken,
            "free": p["shares"] - taken,
            "price_per_share": p["price_per_kg"] * p["weight"] // p["shares"],
            "event_date": p["event_date"],
            "location": p["location"],
            "status": p["status"],
            "created_at": p["created_at"],
        })
    return result


@app.get("/api/purchases/{pid}")
def get_purchase(pid: int):
    d = purchase_detail(pid)
    if not d:
        raise HTTPException(404, "Табылмады")
    return d


@app.post("/api/purchases")
def create_purchase(data: CreatePurchase):
    cfg = ANIMAL_CONFIG.get(data.animal)
    if not cfg:
        raise HTTPException(400, "Мал түрі қате")
    with db() as c:
        cur = c.execute(
            "INSERT INTO purchases (title,animal,price_per_kg,weight,shares,event_date,location,owner_name,owner_phone) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (data.title, data.animal, data.price_per_kg, cfg["weight"], cfg["shares"],
             data.event_date, data.location, data.owner_name, data.owner_phone)
        )
    return purchase_detail(cur.lastrowid)


@app.post("/api/purchases/{pid}/join")
def join_purchase(pid: int, data: JoinPurchase):
    d = purchase_detail(pid)
    if not d:
        raise HTTPException(404, "Табылмады")
    if d["status"] != "open":
        raise HTTPException(400, "Согым жабық")
    if d["free"] <= 0:
        raise HTTPException(400, "Бос үлес жоқ")
    try:
        with db() as c:
            c.execute(
                "INSERT INTO participants (purchase_id,name,phone) VALUES (?,?,?)",
                (pid, data.name, data.phone)
            )
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Бұл телефон бұрыннан тіркелген")
    return purchase_detail(pid)


@app.delete("/api/purchases/{pid}/leave/{phone}")
def leave_purchase(pid: int, phone: str):
    with db() as c:
        c.execute("DELETE FROM participants WHERE purchase_id=? AND phone=?", (pid, phone))
    return purchase_detail(pid)


@app.post("/api/purchases/{pid}/paid")
def mark_paid(pid: int, data: MarkPaid):
    d = purchase_detail(pid)
    if not d:
        raise HTTPException(404)
    if d["owner_phone"] != data.owner_phone:
        raise HTTPException(403, "Тек ұйымдастырушы белгілей алады")
    with db() as c:
        c.execute(
            "UPDATE participants SET paid=1 WHERE purchase_id=? AND phone=?",
            (pid, data.participant_phone)
        )
    return purchase_detail(pid)


@app.post("/api/purchases/{pid}/close")
def close_purchase(pid: int, owner_phone: str):
    d = purchase_detail(pid)
    if not d:
        raise HTTPException(404)
    if d["owner_phone"] != owner_phone:
        raise HTTPException(403)
    with db() as c:
        c.execute("UPDATE purchases SET status='closed' WHERE id=?", (pid,))
    return purchase_detail(pid)


@app.get("/api/animals")
def get_animals():
    return [{"id": k, **v} for k, v in ANIMAL_CONFIG.items()]


# ── Static + SPA ────────────────────────────
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    index = os.path.join(static_dir, "index.html")
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
