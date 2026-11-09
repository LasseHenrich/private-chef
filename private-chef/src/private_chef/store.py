"""SQLite persistence. Every public mutation uses a short, atomic transaction."""

import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .validation import ChefError

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id TEXT PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    member_id TEXT NOT NULL REFERENCES members(id),
    kind TEXT NOT NULL CHECK(kind IN ('like','dislike','exclude','cuisine','diet')),
    value TEXT NOT NULL, PRIMARY KEY(member_id, kind, value)
);
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, servings INTEGER NOT NULL,
    ingredients TEXT NOT NULL, instructions TEXT NOT NULL, tags TEXT NOT NULL,
    source_url TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id),
    recipe_id INTEGER NOT NULL REFERENCES recipes(id),
    rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), comment TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS selections (
    id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL REFERENCES recipes(id),
    member_id TEXT NOT NULL REFERENCES members(id), servings INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','cooked','cancelled')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS shopping (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL,
    manual_quantity TEXT NOT NULL DEFAULT '0', purchased INTEGER NOT NULL DEFAULT 0,
    UNIQUE(name, unit)
);
CREATE TABLE IF NOT EXISTS shopping_contributions (
    selection_id INTEGER NOT NULL REFERENCES selections(id),
    shopping_id INTEGER NOT NULL REFERENCES shopping(id), quantity TEXT NOT NULL,
    PRIMARY KEY(selection_id, shopping_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id),
    role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY, member_id TEXT NOT NULL REFERENCES members(id),
    message TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','complete','failed')),
    reply TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
PRAGMA user_version = 1;
"""


def normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def decode_recipe(row) -> dict:
    item = dict(row)
    for field in ("ingredients", "instructions", "tags"):
        item[field] = json.loads(item[field])
    return item


class Store:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self, names=("Person 1", "Person 2")) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ChefError("Database was created by a newer application version")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            for member_id, name in zip(("person-1", "person-2"), names, strict=True):
                db.execute(
                    "INSERT INTO members VALUES (?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                    (member_id, name),
                )
        self.path.chmod(0o600)

    def check_member(self, member_id: str) -> None:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM members WHERE id=?", (member_id,)).fetchone():
                raise ChefError("Unknown household member")

    def household(self) -> dict:
        with self.connect() as db:
            members = [dict(row) for row in db.execute("SELECT * FROM members ORDER BY id")]
            for member in members:
                member["preferences"] = [
                    dict(row)
                    for row in db.execute(
                        "SELECT kind,value FROM preferences WHERE member_id=? ORDER BY kind,value",
                        (member["id"],),
                    )
                ]
            return {"members": members}

    def preference(self, actor: str, kind: str, value: str, remove: bool) -> dict:
        value = normalized(value)
        with self.connect() as db:
            if remove:
                db.execute(
                    "DELETE FROM preferences WHERE member_id=? AND kind=? AND value=?",
                    (actor, kind, value),
                )
            else:
                opposite = {"like": "dislike", "dislike": "like"}.get(kind)
                if opposite:
                    db.execute(
                        "DELETE FROM preferences WHERE member_id=? AND kind=? AND value=?",
                        (actor, opposite, value),
                    )
                db.execute("INSERT OR IGNORE INTO preferences VALUES (?,?,?)", (actor, kind, value))
        return self.household()

    def save_recipe(self, **recipe) -> dict:
        ingredients = recipe["ingredients"]
        for ingredient in ingredients:
            ingredient["name"] = normalized(ingredient["name"])
            ingredient["unit"] = normalized(ingredient["unit"])
        recipe["tags"] = sorted({normalized(tag) for tag in recipe["tags"]})
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO recipes(title,servings,ingredients,instructions,tags,source_url) "
                "VALUES (?,?,?,?,?,?)",
                (
                    recipe["title"].strip(),
                    recipe["servings"],
                    json.dumps(ingredients),
                    json.dumps(recipe["instructions"]),
                    json.dumps(recipe["tags"]),
                    recipe["source_url"],
                ),
            )
            recipe_id = cursor.lastrowid
        return self.recipe(recipe_id)

    def recipe(self, recipe_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM recipes WHERE id=?", (recipe_id,)).fetchone()
            if not row:
                raise ChefError("Recipe does not exist")
            return decode_recipe(row)

    def recipes(self) -> list[dict]:
        with self.connect() as db:
            return [decode_recipe(row) for row in db.execute("SELECT * FROM recipes ORDER BY id")]

    def feedback(self, actor: str, recipe_id: int, rating: int, comment: str) -> dict:
        self.recipe(recipe_id)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO feedback(member_id,recipe_id,rating,comment) VALUES (?,?,?,?)",
                (actor, recipe_id, rating, comment),
            )
            return {"id": cursor.lastrowid, "member_id": actor, "saved": True}

    def history(self) -> dict:
        with self.connect() as db:
            return {
                "selections": [
                    dict(row)
                    for row in db.execute(
                        "SELECT s.*,r.title FROM selections s JOIN recipes r ON r.id=s.recipe_id "
                        "ORDER BY s.id DESC LIMIT 50"
                    )
                ],
                "feedback": [
                    dict(row)
                    for row in db.execute(
                        "SELECT f.*,r.title FROM feedback f JOIN recipes r ON r.id=f.recipe_id "
                        "ORDER BY f.id DESC LIMIT 100"
                    )
                ],
            }

    def select(self, actor: str, recipe_id: int, servings: int) -> dict:
        self.recipe(recipe_id)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO selections(recipe_id,member_id,servings) VALUES (?,?,?)",
                (recipe_id, actor, servings),
            )
            return {"selection_id": cursor.lastrowid, "recipe_id": recipe_id, "servings": servings}

    def set_selection_status(self, selection_id: int, status: str) -> dict:
        with self.connect() as db:
            cursor = db.execute("UPDATE selections SET status=? WHERE id=?", (status, selection_id))
            if not cursor.rowcount:
                raise ChefError("Selected meal does not exist")
            if status == "cancelled":
                db.execute(
                    "DELETE FROM shopping_contributions WHERE selection_id=?", (selection_id,)
                )
        return {"selection_id": selection_id, "status": status}

    def shopping(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM shopping ORDER BY name,unit").fetchall()
            result = []
            for row in rows:
                quantity = Decimal(row["manual_quantity"])
                for contribution in db.execute(
                    "SELECT quantity FROM shopping_contributions WHERE shopping_id=?", (row["id"],)
                ):
                    quantity += Decimal(contribution[0])
                if quantity > 0:
                    result.append(
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "unit": row["unit"],
                            "quantity": float(quantity),
                            "purchased": bool(row["purchased"]),
                        }
                    )
            return result

    def build_shopping(self) -> list[dict]:
        """Replace per-selection contributions; repeated builds never add quantities twice."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = {}
            for item in db.execute("SELECT shopping_id,quantity FROM shopping_contributions"):
                key = item["shopping_id"]
                previous[key] = previous.get(key, Decimal(0)) + Decimal(item["quantity"])
            for row in db.execute(
                "SELECT s.id,s.servings,r.servings AS base,r.ingredients FROM selections s "
                "JOIN recipes r ON r.id=s.recipe_id WHERE s.status='planned'"
            ).fetchall():
                db.execute("DELETE FROM shopping_contributions WHERE selection_id=?", (row["id"],))
                totals = {}
                for ingredient in json.loads(row["ingredients"]):
                    key = (ingredient["name"], ingredient["unit"])
                    quantity = Decimal(str(ingredient["quantity"])) * row["servings"] / row["base"]
                    totals[key] = totals.get(key, Decimal(0)) + quantity
                for (name, unit), quantity in totals.items():
                    db.execute(
                        "INSERT OR IGNORE INTO shopping(name,unit) VALUES (?,?)", (name, unit)
                    )
                    shopping_id = db.execute(
                        "SELECT id FROM shopping WHERE name=? AND unit=?", (name, unit)
                    ).fetchone()[0]
                    db.execute(
                        "INSERT INTO shopping_contributions VALUES (?,?,?)",
                        (row["id"], shopping_id, str(quantity)),
                    )
            current = {}
            for item in db.execute("SELECT shopping_id,quantity FROM shopping_contributions"):
                key = item["shopping_id"]
                current[key] = current.get(key, Decimal(0)) + Decimal(item["quantity"])
            for item_id, quantity in current.items():
                if quantity > previous.get(item_id, Decimal(0)):
                    db.execute("UPDATE shopping SET purchased=0 WHERE id=?", (item_id,))
        return self.shopping()

    def add_shopping(self, name: str, quantity: float, unit: str) -> list[dict]:
        name, unit = normalized(name), normalized(unit)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO shopping(name,unit) VALUES (?,?)", (name, unit))
            row = db.execute(
                "SELECT * FROM shopping WHERE name=? AND unit=?", (name, unit)
            ).fetchone()
            total = Decimal(row["manual_quantity"]) + Decimal(str(quantity))
            db.execute(
                "UPDATE shopping SET manual_quantity=?,purchased=0 WHERE id=?",
                (str(total), row["id"]),
            )
        return self.shopping()

    def mark_shopping(self, item_id: int, purchased: bool) -> list[dict]:
        with self.connect() as db:
            if not db.execute(
                "UPDATE shopping SET purchased=? WHERE id=?", (int(purchased), item_id)
            ).rowcount:
                raise ChefError("Shopping item does not exist")
        return self.shopping()

    def clear_shopping(self) -> dict:
        with self.connect() as db:
            db.execute("DELETE FROM shopping_contributions")
            db.execute("DELETE FROM shopping")
        return {"cleared": True}

    def remove_shopping(self, item_id: int) -> list[dict]:
        with self.connect() as db:
            db.execute("DELETE FROM shopping_contributions WHERE shopping_id=?", (item_id,))
            if not db.execute("DELETE FROM shopping WHERE id=?", (item_id,)).rowcount:
                raise ChefError("Shopping item does not exist")
        return self.shopping()

    def messages(self, actor: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT role,content FROM messages WHERE member_id=? ORDER BY id DESC LIMIT 12",
                (actor,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def save_exchange(self, actor: str, message: str, reply: str) -> None:
        with self.connect() as db:
            db.executemany(
                "INSERT INTO messages(member_id,role,content) VALUES (?,?,?)",
                [(actor, "user", message), (actor, "assistant", reply)],
            )
            db.execute(
                "DELETE FROM messages WHERE member_id=? AND id NOT IN "
                "(SELECT id FROM messages WHERE member_id=? ORDER BY id DESC LIMIT 40)",
                (actor, actor),
            )

    def begin_request(self, request_id: str, actor: str, message: str) -> str | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
            if row:
                if row["member_id"] != actor or row["message"] != message:
                    raise ChefError("Request ID was already used for a different message")
                if row["status"] == "complete":
                    return row["reply"]
                raise ChefError(
                    "This request is pending or failed; check saved changes before retrying"
                )
            db.execute(
                "INSERT INTO requests(id,member_id,message,status) VALUES (?,?,?,'pending')",
                (request_id, actor, message),
            )
        return None

    def finish_request(self, request_id: str, reply: str | None) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE requests SET status=?,reply=? WHERE id=?",
                ("complete" if reply is not None else "failed", reply, request_id),
            )
