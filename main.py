import calendar
import csv
import io
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from fastmcp import FastMCP

import tempfile

def _default_db_path() -> str:
    folder = Path(__file__).parent
    if os.access(folder, os.W_OK):
        return str(folder / "expenses.db")
    # Server par project folder read-only ho sakta hai, is liye temp folder use karein
    return str(Path(tempfile.gettempdir()) / "expenses.db")

DB_PATH = os.environ.get("EXPENSE_DB_PATH", _default_db_path())

DEFAULT_CATEGORIES = {
    "Food": ["Groceries", "Restaurants", "Snacks"],
    "Health": ["Medicine", "Doctor", "Gym"],
    "Education": ["Books", "Fees", "Courses"],
    "Transport": ["Fuel", "Bus", "Taxi"],
    "Bills": ["Electricity", "Internet", "Mobile"],
}

mcp = FastMCP(name="Expense Tracker")


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS subcategories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            UNIQUE(category_id, name)
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK(amount > 0),
            entry_type TEXT NOT NULL DEFAULT 'debit' CHECK(entry_type IN ('debit', 'credit')),
            category_id INTEGER NOT NULL REFERENCES categories(id),
            subcategory_id INTEGER REFERENCES subcategories(id) ON DELETE SET NULL,
            description TEXT DEFAULT '',
            entry_date TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS budgets (
            category_id INTEGER PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
            monthly_limit REAL NOT NULL CHECK(monthly_limit > 0)
        );
        CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(entry_date);
        CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category_id);
        """)
        for cat, subs in DEFAULT_CATEGORIES.items():
            conn.execute("INSERT OR IGNORE INTO categories(name) VALUES (?)", (cat,))
            cid = conn.execute("SELECT id FROM categories WHERE name = ?", (cat,)).fetchone()["id"]
            for sub in subs:
                conn.execute(
                    "INSERT OR IGNORE INTO subcategories(category_id, name) VALUES (?, ?)",
                    (cid, sub),
                )


# ---------- Helpers ----------

def _money(value: float) -> float:
    value = round(float(value), 2)
    if value <= 0:
        raise ValueError("Amount must be greater than 0.")
    return value


def _valid_date(value: str) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("Date must be in YYYY-MM-DD format, for example 2026-11-10.")


def _valid_type(value: str) -> str:
    value = (value or "debit").lower()
    if value not in ("debit", "credit"):
        raise ValueError("entry_type must be 'debit' (expense) or 'credit' (money returned or income).")
    return value


def _month_range(month: str):
    if not month:
        month = date.today().strftime("%Y-%m")
    try:
        year, mon = map(int, month.split("-"))
        last_day = calendar.monthrange(year, mon)[1]
    except ValueError:
        raise ValueError("Month must be in YYYY-MM format, for example 2026-11.")
    return f"{year}-{mon:02d}-01", f"{year}-{mon:02d}-{last_day:02d}"


def _date_filter(start_date: str, end_date: str):
    sql, params = "", []
    if start_date:
        sql += " AND e.entry_date >= ?"
        params.append(_valid_date(start_date))
    if end_date:
        sql += " AND e.entry_date <= ?"
        params.append(_valid_date(end_date))
    return sql, params


def _category_id(conn, name: str) -> int:
    row = conn.execute(
        "SELECT id FROM categories WHERE LOWER(name) = LOWER(?)", (name.strip(),)
    ).fetchone()
    if not row:
        raise ValueError(f"Category '{name}' not found. Create it first with add_category.")
    return row["id"]


def _subcategory_id(conn, category_id: int, name: str):
    if not name:
        return None
    row = conn.execute(
        "SELECT id FROM subcategories WHERE category_id = ? AND LOWER(name) = LOWER(?)",
        (category_id, name.strip()),
    ).fetchone()
    if not row:
        raise ValueError(f"Subcategory '{name}' does not exist in this category. Create it first with add_subcategory.")
    return row["id"]


def _budget_warning(conn, category_id: int, entry_date: str) -> str:
    budget = conn.execute(
        "SELECT monthly_limit FROM budgets WHERE category_id = ?", (category_id,)
    ).fetchone()
    if not budget:
        return ""
    start, end = _month_range(entry_date[:7])
    spent = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) FROM expenses
           WHERE category_id = ? AND entry_type = 'debit' AND entry_date BETWEEN ? AND ?""",
        (category_id, start, end),
    ).fetchone()[0]
    limit = budget["monthly_limit"]
    if spent > limit:
        return f"\nWARNING: Monthly budget exceeded: {spent:.2f} / {limit:.2f}"
    if spent >= 0.8 * limit:
        return f"\nWARNING: More than 80% of the budget is used: {spent:.2f} / {limit:.2f}"
    return ""


# ---------- Categories ----------

@mcp.tool
def add_category(name: str) -> str:
    """Add a new main category, for example Food, Health or Education."""
    name = name.strip()
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM categories WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        if exists:
            raise ValueError(f"Category '{name}' already exists.")
        conn.execute("INSERT INTO categories(name) VALUES (?)", (name,))
    return f"Category '{name}' added."


@mcp.tool
def rename_category(old_name: str, new_name: str) -> str:
    """Rename a category."""
    with db() as conn:
        cid = _category_id(conn, old_name)
        try:
            conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name.strip(), cid))
        except sqlite3.IntegrityError:
            raise ValueError(f"A category named '{new_name}' already exists.")
    return f"Category '{old_name}' renamed to '{new_name}'."


@mcp.tool
def delete_category(name: str) -> str:
    """Delete a category, only if it has no entries. Its subcategories are deleted too."""
    with db() as conn:
        cid = _category_id(conn, name)
        used = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE category_id = ?", (cid,)
        ).fetchone()[0]
        if used:
            raise ValueError(
                f"'{name}' has {used} entries. Move them to another category with edit_expense first."
            )
        conn.execute("DELETE FROM categories WHERE id = ?", (cid,))
    return f"Category '{name}' deleted."


@mcp.tool
def add_subcategory(category: str, name: str) -> str:
    """Add a subcategory inside a category, for example Groceries inside Food."""
    name = name.strip()
    with db() as conn:
        cid = _category_id(conn, category)
        exists = conn.execute(
            "SELECT 1 FROM subcategories WHERE category_id = ? AND LOWER(name) = LOWER(?)",
            (cid, name),
        ).fetchone()
        if exists:
            raise ValueError(f"'{name}' already exists in this category.")
        conn.execute("INSERT INTO subcategories(category_id, name) VALUES (?, ?)", (cid, name))
    return f"Subcategory '{name}' added to '{category}'."


@mcp.tool
def delete_subcategory(category: str, name: str) -> str:
    """Delete a subcategory. Old entries stay, but they will have no subcategory."""
    with db() as conn:
        cid = _category_id(conn, category)
        sid = _subcategory_id(conn, cid, name)
        conn.execute("DELETE FROM subcategories WHERE id = ?", (sid,))
    return f"Subcategory '{name}' deleted."


@mcp.tool
def list_categories() -> dict:
    """List all categories and their subcategories."""
    with db() as conn:
        cats = conn.execute("SELECT id, name FROM categories ORDER BY name").fetchall()
        result = {}
        for c in cats:
            subs = conn.execute(
                "SELECT name FROM subcategories WHERE category_id = ? ORDER BY name",
                (c["id"],),
            ).fetchall()
            result[c["name"]] = [s["name"] for s in subs]
    return result


# ---------- Budgets ----------

@mcp.tool
def set_budget(category: str, monthly_limit: float) -> str:
    """Set or update the monthly budget limit for a category."""
    limit = _money(monthly_limit)
    with db() as conn:
        cid = _category_id(conn, category)
        conn.execute(
            """INSERT INTO budgets(category_id, monthly_limit) VALUES (?, ?)
               ON CONFLICT(category_id) DO UPDATE SET monthly_limit = excluded.monthly_limit""",
            (cid, limit),
        )
    return f"Monthly budget for '{category}' set to {limit:.2f}."


@mcp.tool
def budget_status(month: str = "") -> list[dict]:
    """Show each budgeted category: amount spent, remaining, and warning status. Month is YYYY-MM, default is the current month."""
    start, end = _month_range(month)
    with db() as conn:
        rows = conn.execute(
            """SELECT c.name, b.monthly_limit,
                      COALESCE((SELECT SUM(e.amount) FROM expenses e
                                WHERE e.category_id = b.category_id AND e.entry_type = 'debit'
                                AND e.entry_date BETWEEN ? AND ?), 0) AS spent
               FROM budgets b JOIN categories c ON c.id = b.category_id
               ORDER BY c.name""",
            (start, end),
        ).fetchall()
    result = []
    for r in rows:
        spent, limit = round(r["spent"], 2), r["monthly_limit"]
        if spent > limit:
            status = "EXCEEDED"
        elif spent >= 0.8 * limit:
            status = "WARNING (80%+)"
        else:
            status = "OK"
        result.append({
            "category": r["name"],
            "limit": limit,
            "spent": spent,
            "remaining": round(limit - spent, 2),
            "status": status,
        })
    return result


# ---------- Expenses ----------

@mcp.tool
def add_expense(
    amount: float,
    category: str,
    subcategory: str = "",
    description: str = "",
    entry_date: str = "",
    entry_type: str = "debit",
) -> str:
    """Add a new expense (debit) or money returned/income (credit). If date is empty, today's date is used."""
    amount = _money(amount)
    entry_type = _valid_type(entry_type)
    entry_date = _valid_date(entry_date)
    with db() as conn:
        cid = _category_id(conn, category)
        sid = _subcategory_id(conn, cid, subcategory)
        cur = conn.execute(
            """INSERT INTO expenses(amount, entry_type, category_id, subcategory_id, description, entry_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (amount, entry_type, cid, sid, description, entry_date),
        )
        msg = f"Entry #{cur.lastrowid} saved: {entry_type} {amount:.2f} ({category}/{subcategory or '-'}) on {entry_date}"
        if entry_type == "debit":
            msg += _budget_warning(conn, cid, entry_date)
    return msg


@mcp.tool
def list_expenses(
    start_date: str = "",
    end_date: str = "",
    category: str = "",
    entry_type: str = "",
    limit: int = 50,
) -> list[dict]:
    """List expenses. You can filter by date range, category, or type (debit/credit)."""
    sql = """
        SELECT e.id, e.entry_date, e.entry_type, e.amount,
               c.name AS category, s.name AS subcategory, e.description
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        LEFT JOIN subcategories s ON s.id = e.subcategory_id
        WHERE 1=1
    """
    date_sql, params = _date_filter(start_date, end_date)
    sql += date_sql
    if category:
        sql += " AND LOWER(c.name) = LOWER(?)"
        params.append(category.strip())
    if entry_type:
        sql += " AND e.entry_type = ?"
        params.append(_valid_type(entry_type))
    sql += " ORDER BY e.entry_date DESC, e.id DESC LIMIT ?"
    params.append(limit)
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@mcp.tool
def search_expenses(keyword: str, limit: int = 50) -> list[dict]:
    """Search for a keyword in the description, category or subcategory."""
    pattern = f"%{keyword.strip()}%"
    with db() as conn:
        rows = conn.execute(
            """SELECT e.id, e.entry_date, e.entry_type, e.amount,
                      c.name AS category, s.name AS subcategory, e.description
               FROM expenses e
               JOIN categories c ON c.id = e.category_id
               LEFT JOIN subcategories s ON s.id = e.subcategory_id
               WHERE e.description LIKE ? OR c.name LIKE ? OR s.name LIKE ?
               ORDER BY e.entry_date DESC, e.id DESC LIMIT ?""",
            (pattern, pattern, pattern, limit),
        ).fetchall()
    return [dict(r) for r in rows]


@mcp.tool
def edit_expense(
    expense_id: int,
    amount: float = 0,
    category: str = "",
    subcategory: str = "",
    description: str = "",
    entry_date: str = "",
    entry_type: str = "",
) -> str:
    """Edit the details of an expense. Leave a field empty to keep its current value."""
    with db() as conn:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if not row:
            raise ValueError(f"Entry #{expense_id} not found.")

        updates = {}
        if amount:
            updates["amount"] = _money(amount)
        if description:
            updates["description"] = description
        if entry_date:
            updates["entry_date"] = _valid_date(entry_date)
        if entry_type:
            updates["entry_type"] = _valid_type(entry_type)
        if category:
            cid = _category_id(conn, category)
            updates["category_id"] = cid
            updates["subcategory_id"] = _subcategory_id(conn, cid, subcategory)
        elif subcategory:
            updates["subcategory_id"] = _subcategory_id(conn, row["category_id"], subcategory)

        if not updates:
            return "No changes were given."

        set_clause = ", ".join(f"{col} = ?" for col in updates)
        conn.execute(
            f"UPDATE expenses SET {set_clause} WHERE id = ?",
            (*updates.values(), expense_id),
        )
    return f"Entry #{expense_id} updated."


@mcp.tool
def delete_expense(expense_id: int) -> str:
    """Permanently delete an expense."""
    with db() as conn:
        cur = conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        if cur.rowcount == 0:
            raise ValueError(f"Entry #{expense_id} not found.")
    return f"Entry #{expense_id} deleted."


# ---------- Reports and export ----------

@mcp.tool
def summary(start_date: str = "", end_date: str = "") -> dict:
    """Show total spent, total credited, net amount, and spending by category. Date range is optional."""
    date_sql, params = _date_filter(start_date, end_date)
    with db() as conn:
        totals = conn.execute(
            f"""SELECT
                  COALESCE(SUM(CASE WHEN e.entry_type = 'debit' THEN e.amount END), 0) AS spent,
                  COALESCE(SUM(CASE WHEN e.entry_type = 'credit' THEN e.amount END), 0) AS credited
                FROM expenses e WHERE 1=1 {date_sql}""",
            params,
        ).fetchone()
        by_cat = conn.execute(
            f"""SELECT c.name, SUM(CASE WHEN e.entry_type = 'debit' THEN e.amount ELSE 0 END) AS spent
                FROM expenses e JOIN categories c ON c.id = e.category_id
                WHERE 1=1 {date_sql}
                GROUP BY c.name ORDER BY spent DESC""",
            params,
        ).fetchall()
    spent, credited = round(totals["spent"], 2), round(totals["credited"], 2)
    return {
        "spent": spent,
        "credited": credited,
        "net": round(spent - credited, 2),
        "by_category": {r["name"]: round(r["spent"], 2) for r in by_cat},
    }


@mcp.tool
def monthly_report(month: str = "") -> dict:
    """Full report for one month: totals, and spending by category and subcategory. Month is YYYY-MM, default is the current month."""
    start, end = _month_range(month)
    with db() as conn:
        totals = conn.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN entry_type = 'debit' THEN amount END), 0) AS spent,
                 COALESCE(SUM(CASE WHEN entry_type = 'credit' THEN amount END), 0) AS credited
               FROM expenses WHERE entry_date BETWEEN ? AND ?""",
            (start, end),
        ).fetchone()
        by_sub = conn.execute(
            """SELECT c.name AS category, COALESCE(s.name, '(none)') AS subcategory,
                      ROUND(SUM(e.amount), 2) AS spent
               FROM expenses e
               JOIN categories c ON c.id = e.category_id
               LEFT JOIN subcategories s ON s.id = e.subcategory_id
               WHERE e.entry_type = 'debit' AND e.entry_date BETWEEN ? AND ?
               GROUP BY c.name, s.name ORDER BY spent DESC""",
            (start, end),
        ).fetchall()
    spent, credited = round(totals["spent"], 2), round(totals["credited"], 2)
    return {
        "month": start[:7],
        "spent": spent,
        "credited": credited,
        "net": round(spent - credited, 2),
        "by_subcategory": [dict(r) for r in by_sub],
    }


@mcp.tool
def export_csv(start_date: str = "", end_date: str = "") -> str:
    """Export expenses as CSV text. Works on both local and remote servers, so no file is saved on disk."""
    date_sql, params = _date_filter(start_date, end_date)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT e.id, e.entry_date, e.entry_type, e.amount,
                       c.name AS category, COALESCE(s.name, '') AS subcategory, e.description
                FROM expenses e
                JOIN categories c ON c.id = e.category_id
                LEFT JOIN subcategories s ON s.id = e.subcategory_id
                WHERE 1=1 {date_sql}
                ORDER BY e.entry_date, e.id""",
            params,
        ).fetchall()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "entry_date", "entry_type", "amount", "category", "subcategory", "description"])
    writer.writerows([tuple(r) for r in rows])
    return f"{len(rows)} entries exported.\n\n" + buffer.getvalue()


init_db()

if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT", "stdio") == "http":
        # Remote mode: serves over HTTP on the port the host gives us (Render sets PORT).
        mcp.run(transport="http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
    else:
        # Local mode: same as before, used by Claude Desktop.
        mcp.run()