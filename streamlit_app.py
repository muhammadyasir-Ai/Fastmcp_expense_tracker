import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "expenses.db"
CURRENCY = "PKR"

st.set_page_config(page_title="Expense Tracker", page_icon="💰", layout="wide")

THEME_CSS = """
<style>
.stApp { background: linear-gradient(135deg, #eef2ff 0%, #fdf2f8 100%); }
.hero {
    background: linear-gradient(90deg, #6366f1, #ec4899);
    color: white; padding: 22px 28px; border-radius: 18px;
    font-size: 26px; font-weight: 800; margin-bottom: 18px;
    box-shadow: 0 8px 24px rgba(99, 102, 241, .25);
}
h1, h2, h3 { color: #3730a3; }
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #4338ca, #7c3aed); }
section[data-testid="stSidebar"] * { color: #ffffff !important; }
div[data-testid="stMetric"] {
    background: #ffffff; border-radius: 16px; padding: 16px 20px;
    border-left: 6px solid #6366f1; box-shadow: 0 4px 14px rgba(99, 102, 241, .15);
}
div[data-testid="stForm"], div[data-testid="stDataFrame"], div[data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff; border-radius: 16px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, .06);
}
.stButton > button, .stFormSubmitButton > button {
    background: linear-gradient(90deg, #6366f1, #ec4899);
    color: #ffffff; border: none; border-radius: 12px; font-weight: 600;
}
.stButton > button:hover, .stFormSubmitButton > button:hover { opacity: .9; color: #ffffff; }
.stProgress > div > div > div > div { background: linear-gradient(90deg, #10b981, #34d399); }
@media (max-width: 768px) {
    .hero { font-size: 20px; padding: 16px; }
    div[data-testid="stMetric"] { margin-bottom: 8px; }
}
</style>
"""
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.markdown('<div class="hero">💰 Expense Tracker</div>', unsafe_allow_html=True)


# ---------- Database helpers ----------

def money(value) -> str:
    return f"{CURRENCY} {float(value or 0):,.2f}"


def run(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def query(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def month_str(d: date) -> str:
    return d.strftime("%Y-%m")


def shift_month(month: str, delta: int) -> str:
    y, m = map(int, month.split("-"))
    total = y * 12 + (m - 1) + delta
    return f"{total // 12}-{total % 12 + 1:02d}"


def monthly_spent(month: str) -> float:
    return float(query(
        "SELECT COALESCE(SUM(amount), 0) AS v FROM expenses WHERE entry_type = 'debit' AND substr(entry_date, 1, 7) = ?",
        (month,),
    ).iloc[0]["v"])


def budget_table(month: str) -> pd.DataFrame:
    return query(
        """SELECT c.name, b.monthly_limit,
                  COALESCE((SELECT SUM(e.amount) FROM expenses e
                            WHERE e.category_id = b.category_id AND e.entry_type = 'debit'
                            AND substr(e.entry_date, 1, 7) = ?), 0) AS spent
           FROM budgets b JOIN categories c ON c.id = b.category_id
           ORDER BY c.name""",
        (month,),
    )


def category_names_by_usage() -> list:
    return query(
        """SELECT c.name FROM categories c
           LEFT JOIN expenses e ON e.category_id = c.id
           GROUP BY c.id ORDER BY COUNT(e.id) DESC, c.name"""
    )["name"].tolist()


def all_subcategories() -> pd.DataFrame:
    return query(
        """SELECT c.name AS category, s.name AS name
           FROM subcategories s JOIN categories c ON c.id = s.category_id
           ORDER BY s.name"""
    )


def save_entry(amount, entry_type, category, subcategory, description, entry_date):
    cid = int(query("SELECT id FROM categories WHERE name = ?", (category,)).iloc[0, 0])
    sid = None
    if subcategory and subcategory != "(none)":
        sid = int(query(
            "SELECT id FROM subcategories WHERE category_id = ? AND name = ?",
            (cid, subcategory),
        ).iloc[0, 0])
    run(
        """INSERT INTO expenses(amount, entry_type, category_id, subcategory_id, description, entry_date)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (round(float(amount), 2), entry_type, cid, sid, (description or "").strip(), entry_date.isoformat()),
    )


def parse_quick(text: str, category_names: list, subs: pd.DataFrame):
    """Turn a line like '350 Food Groceries sabzi' into an entry."""
    lowered = text.lower()
    number = re.search(r"\d+(?:\.\d+)?", text)
    if not number:
        return None, "Amount not found. Include a number, for example: 350 Food Groceries sabzi"

    category = next(
        (n for n in category_names if re.search(rf"\b{re.escape(n.lower())}\b", lowered)), None
    )
    if category is None:
        return None, "Category not found. Write the category name in the text, for example: Food"

    subcategory = None
    for name in subs.loc[subs["category"] == category, "name"]:
        if re.search(rf"\b{re.escape(name.lower())}\b", lowered):
            subcategory = name
            break

    description = text.replace(number.group(), "", 1).strip(" +-,")
    return {
        "amount": float(number.group()),
        "entry_type": "credit" if text.strip().startswith("+") else "debit",
        "category": category,
        "subcategory": subcategory,
        "description": description,
    }, ""


def date_filter_ui():
    today = date.today()
    choice = st.radio(
        "Period", ["This week", "This month", "Last 30 days", "All time", "Custom"],
        horizontal=True, key="period",
    )
    if choice == "This week":
        return today - timedelta(days=today.weekday()), today
    if choice == "This month":
        return today.replace(day=1), today
    if choice == "Last 30 days":
        return today - timedelta(days=29), today
    if choice == "All time":
        return date(2000, 1, 1), today
    c1, c2 = st.columns(2)
    start = c1.date_input("From", value=today.replace(day=1), key="from_date")
    end = c2.date_input("To", value=today, key="to_date")
    return start, end


@st.dialog("Confirm deletion")
def confirm_delete(entry_id: int, label: str):
    st.write("Are you sure you want to delete this entry? This cannot be undone.")
    st.markdown(f"**{label}**")
    c1, c2 = st.columns(2)
    if c1.button("Yes, delete", type="primary"):
        run("DELETE FROM expenses WHERE id = ?", (entry_id,))
        st.rerun()
    if c2.button("Cancel"):
        st.rerun()


# ---------- Home ----------

def home_page():
    today = date.today()
    st.title("Home")
    st.caption(today.strftime("%A, %d %B %Y"))

    total_entries = int(query("SELECT COUNT(*) AS n FROM expenses").iloc[0]["n"])
    if total_entries == 0:
        st.info("Welcome! Start by setting up your categories, then add your first expense.")
        c1, c2 = st.columns(2)
        c1.page_link(PAGES["categories"], label="Set up categories", icon=":material/category:")
        c2.page_link(PAGES["add"], label="Add first expense", icon=":material/add_circle:")
        return

    this_month = month_str(today)
    spent_today = float(query(
        "SELECT COALESCE(SUM(amount), 0) AS v FROM expenses WHERE entry_type = 'debit' AND entry_date = ?",
        (today.isoformat(),),
    ).iloc[0]["v"])
    spent_month = monthly_spent(this_month)
    spent_last = monthly_spent(shift_month(this_month, -1))

    budgets = budget_table(this_month)
    budget_left = (budgets["monthly_limit"].sum() - budgets["spent"].sum()) if not budgets.empty else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spent today", money(spent_today))
    c2.metric("Spent this month", money(spent_month),
              delta=f"{spent_month - spent_last:+,.0f} vs last month", delta_color="inverse")
    c3.metric("Budget left", money(budget_left) if budget_left is not None else "No budgets set")
    c4.metric("Total entries", total_entries)

    st.subheader("Recent entries")
    recent = query(
        """SELECT e.entry_date, e.entry_type, e.amount, c.name AS category,
                  COALESCE(s.name, '') AS subcategory, COALESCE(e.description, '') AS description
           FROM expenses e
           JOIN categories c ON c.id = e.category_id
           LEFT JOIN subcategories s ON s.id = e.subcategory_id
           ORDER BY e.entry_date DESC, e.id DESC LIMIT 5"""
    )
    st.dataframe(
        recent, hide_index=True,
        column_config={"amount": st.column_config.NumberColumn("Amount", format=f"{CURRENCY} %.2f")},
    )


# ---------- Add expense ----------

def add_expense_page():
    st.title("Add expense")

    category_names = query("SELECT name FROM categories ORDER BY name")["name"].tolist()
    if not category_names:
        st.warning("No categories yet. Add one on the Categories & budgets page first.")
        return

    subs = all_subcategories()

    with st.container(border=True):
        st.markdown("**Quick add**: type the amount, category and note in one line.")
        st.caption("Examples: `350 Food Groceries sabzi` or `+5000 Bills Internet` (the + means credit)")
        quick_text = st.text_input("Quick entry", key="quick_text", placeholder="350 Food Groceries sabzi")
        if st.button("Add quick entry"):
            if not quick_text.strip():
                st.error("Please type something first.")
            else:
                parsed, error = parse_quick(quick_text, category_names, subs)
                if error:
                    st.error(error)
                else:
                    save_entry(parsed["amount"], parsed["entry_type"], parsed["category"],
                               parsed["subcategory"], parsed["description"], date.today())
                    st.success(
                        f"Saved: {parsed['entry_type']} of {money(parsed['amount'])} in "
                        f"{parsed['category']}" + (f" / {parsed['subcategory']}" if parsed["subcategory"] else "")
                    )

    st.subheader("Detailed entry")
    col1, col2 = st.columns(2)
    category = col1.selectbox("Category", category_names)
    sub_options = subs.loc[subs["category"] == category, "name"].tolist()
    subcategory = col2.selectbox("Subcategory", ["(none)"] + sub_options)

    st.session_state.setdefault("amount_input", 0.0)
    st.caption("Quick amounts")
    shortcut_cols = st.columns(6)
    for col, value in zip(shortcut_cols, [50, 100, 200, 500, 1000, 5000]):
        if col.button(f"{value:,}", key=f"shortcut_{value}"):
            st.session_state["amount_input"] = float(value)

    with st.form("add_expense_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        amount = c1.number_input(f"Amount ({CURRENCY})", min_value=0.0, step=10.0,
                                 format="%.2f", key="amount_input")
        entry_type = c2.radio(
            "Type", ["debit", "credit"], horizontal=True,
            format_func=lambda x: "Expense" if x == "debit" else "Credit (refund / income)",
        )
        entry_date = c3.date_input("Date", value=date.today())
        description = st.text_input("Description (optional)")
        submitted = st.form_submit_button("Save entry", type="primary")

    if submitted:
        if amount <= 0:
            st.error("Amount must be greater than 0.")
        else:
            save_entry(amount, entry_type, category, subcategory, description, entry_date)
            where = category if subcategory == "(none)" else f"{category} / {subcategory}"
            st.success(f"Saved: {entry_type} of {money(amount)} in {where}")


# ---------- Expenses ----------

def expenses_page():
    st.title("Expenses")

    start, end = date_filter_ui()
    cat_names = query("SELECT name FROM categories ORDER BY name")["name"].tolist()
    f1, f2 = st.columns(2)
    category = f1.selectbox("Category", ["All"] + cat_names)
    entry_type = f2.selectbox("Type", ["All", "debit", "credit"],
                              format_func=lambda x: {"All": "All", "debit": "Expenses", "credit": "Credits"}[x])

    sql = """
        SELECT e.id, e.entry_date, e.entry_type, e.amount,
               c.name AS category, COALESCE(s.name, '') AS subcategory,
               COALESCE(e.description, '') AS description
        FROM expenses e
        JOIN categories c ON c.id = e.category_id
        LEFT JOIN subcategories s ON s.id = e.subcategory_id
        WHERE e.entry_date BETWEEN ? AND ?
    """
    params = [start.isoformat(), end.isoformat()]
    if category != "All":
        sql += " AND c.name = ?"
        params.append(category)
    if entry_type != "All":
        sql += " AND e.entry_type = ?"
        params.append(entry_type)
    sql += " ORDER BY e.entry_date DESC, e.id DESC"
    data = query(sql, params)

    search = st.text_input("Search description, category or subcategory")
    if search and not data.empty:
        term = search.lower()
        data = data[data.apply(lambda r: term in " ".join(map(str, r.values)).lower(), axis=1)]

    if data.empty:
        st.info("No entries match these filters. Try a wider period, or add an expense on the Add expense page.")
        return

    debit = data.loc[data["entry_type"] == "debit", "amount"]
    credit = data.loc[data["entry_type"] == "credit", "amount"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entries", len(data))
    c2.metric("Spent", money(debit.sum()))
    c3.metric("Credited", money(credit.sum()))
    c4.metric("Biggest entry", money(data["amount"].max()))

    st.subheader("All entries")
    st.caption("You can edit the amount and description directly in the table.")
    edited = st.data_editor(
        data,
        hide_index=True,
        key="expense_editor",
        disabled=["id", "entry_date", "entry_type", "category", "subcategory"],
        column_config={
            "amount": st.column_config.NumberColumn("Amount", format=f"{CURRENCY} %.2f", min_value=0.01),
            "description": st.column_config.TextColumn("Description"),
        },
    )

    original = data.set_index("id")
    changed = False
    for _, row in edited.iterrows():
        before = original.loc[row["id"]]
        if abs(float(row["amount"]) - float(before["amount"])) > 0.001 or str(row["description"]) != str(before["description"]):
            run(
                "UPDATE expenses SET amount = ?, description = ? WHERE id = ?",
                (round(float(row["amount"]), 2), str(row["description"]).strip(), int(row["id"])),
            )
            changed = True
    if changed:
        st.rerun()

    st.download_button(
        "Download CSV",
        data=data.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"expenses_{start}_{end}.csv",
        mime="text/csv",
    )

    st.subheader("Delete an entry")
    entry_id = st.selectbox("Entry ID", data["id"].tolist())
    row = data[data["id"] == entry_id].iloc[0]
    if st.button("Delete entry"):
        label = f"{row['entry_date']} | {row['category']} | {money(row['amount'])}"
        confirm_delete(int(entry_id), label)


# ---------- Dashboard ----------

def dashboard_page():
    st.title("Dashboard")

    months = query(
        "SELECT DISTINCT substr(entry_date, 1, 7) AS month FROM expenses ORDER BY month DESC"
    )["month"].tolist()
    current = month_str(date.today())
    if current not in months:
        months.insert(0, current)
    month = st.selectbox("Month", months)
    previous = shift_month(month, -1)

    spent_now = monthly_spent(month)
    spent_prev = monthly_spent(previous)
    credited = float(query(
        "SELECT COALESCE(SUM(amount), 0) AS v FROM expenses WHERE entry_type = 'credit' AND substr(entry_date, 1, 7) = ?",
        (month,),
    ).iloc[0]["v"])
    biggest = query(
        """SELECT c.name AS category, e.amount FROM expenses e
           JOIN categories c ON c.id = e.category_id
           WHERE e.entry_type = 'debit' AND substr(e.entry_date, 1, 7) = ?
           ORDER BY e.amount DESC LIMIT 1""",
        (month,),
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spent", money(spent_now),
              delta=f"{spent_now - spent_prev:+,.0f} vs {previous}", delta_color="inverse")
    c2.metric("Credited", money(credited))
    c3.metric("Net", money(spent_now - credited))
    if biggest.empty:
        c4.metric("Biggest expense", "None")
    else:
        c4.metric("Biggest expense", money(biggest.iloc[0]["amount"]), delta=biggest.iloc[0]["category"],
                  delta_color="off")

    by_cat = query(
        """SELECT c.name AS category, ROUND(SUM(e.amount), 2) AS spent
           FROM expenses e JOIN categories c ON c.id = e.category_id
           WHERE e.entry_type = 'debit' AND substr(e.entry_date, 1, 7) = ?
           GROUP BY c.name ORDER BY spent DESC""",
        (month,),
    )

    st.subheader("Insights")
    if spent_prev > 0 and spent_now > 0:
        change = (spent_now - spent_prev) / spent_prev * 100
        if change > 0:
            st.warning(f"Spending is up {change:.0f}% compared to {previous}.")
        else:
            st.success(f"Spending is down {abs(change):.0f}% compared to {previous}.")
    if not by_cat.empty and spent_now > 0:
        top = by_cat.iloc[0]
        share = top["spent"] / spent_now * 100
        st.info(f"{top['category']} makes up {share:.0f}% of this month's spending.")
    if spent_now == 0:
        st.info("No expenses recorded for this month yet.")

    left, right = st.columns(2)
    with left:
        st.subheader("Spending by category")
        if by_cat.empty:
            st.caption("No data.")
        else:
            st.bar_chart(by_cat.set_index("category"), color="#8b5cf6")
    with right:
        st.subheader("Monthly trend")
        monthly = query(
            """SELECT substr(entry_date, 1, 7) AS month,
                      ROUND(SUM(CASE WHEN entry_type = 'debit' THEN amount ELSE 0 END), 2) AS spent,
                      ROUND(SUM(CASE WHEN entry_type = 'credit' THEN amount ELSE 0 END), 2) AS credited
               FROM expenses GROUP BY month ORDER BY month"""
        )
        if monthly.empty:
            st.caption("No data yet.")
        else:
            st.bar_chart(monthly.set_index("month")[["spent", "credited"]], color=["#f43f5e", "#10b981"])

    st.subheader("Budgets")
    budgets = budget_table(month)
    if budgets.empty:
        st.info("No budgets set. Add one on the Categories & budgets page.")
    else:
        over = (budgets["spent"] > budgets["monthly_limit"]).sum()
        near = ((budgets["spent"] >= 0.8 * budgets["monthly_limit"]) & (budgets["spent"] <= budgets["monthly_limit"])).sum()
        if over:
            st.error(f"{over} budget(s) exceeded this month.")
        if near:
            st.warning(f"{near} budget(s) above 80% of the limit.")
        for _, r in budgets.iterrows():
            ratio = float(r["spent"]) / float(r["monthly_limit"])
            st.write(f"**{r['name']}**: {money(r['spent'])} of {money(r['monthly_limit'])}")
            st.progress(min(ratio, 1.0))


# ---------- Categories & budgets ----------

def categories_page():
    st.title("Categories & budgets")

    st.subheader("Add category")
    new_cat = st.text_input("Category name")
    if st.button("Add category") and new_cat.strip():
        try:
            run("INSERT INTO categories(name) VALUES (?)", (new_cat.strip(),))
            st.success(f"Category '{new_cat.strip()}' added.")
        except sqlite3.IntegrityError:
            st.error("This category already exists.")

    cats = query("SELECT id, name FROM categories ORDER BY name")
    if cats.empty:
        st.info("No categories yet.")
        return

    st.subheader("Add subcategory")
    parent = st.selectbox("Parent category", cats["name"].tolist(), key="sub_parent")
    new_sub = st.text_input("Subcategory name")
    if st.button("Add subcategory") and new_sub.strip():
        cid = int(cats.loc[cats["name"] == parent, "id"].iloc[0])
        try:
            run("INSERT INTO subcategories(category_id, name) VALUES (?, ?)", (cid, new_sub.strip()))
            st.success(f"Subcategory '{new_sub.strip()}' added to {parent}.")
        except sqlite3.IntegrityError:
            st.error("This subcategory already exists in that category.")

    st.subheader("Monthly budget")
    b_cat = st.selectbox("Category", cats["name"].tolist(), key="budget_cat")
    limit = st.number_input(f"Monthly limit ({CURRENCY})", min_value=1.0, step=500.0)
    if st.button("Save budget"):
        cid = int(cats.loc[cats["name"] == b_cat, "id"].iloc[0])
        run(
            """INSERT INTO budgets(category_id, monthly_limit) VALUES (?, ?)
               ON CONFLICT(category_id) DO UPDATE SET monthly_limit = excluded.monthly_limit""",
            (cid, limit),
        )
        st.success(f"Budget for {b_cat} saved.")

    st.subheader("Current categories and subcategories")
    tree = query(
        """SELECT c.name AS category, COALESCE(s.name, '') AS subcategory
           FROM categories c LEFT JOIN subcategories s ON s.category_id = c.id
           ORDER BY c.name, s.name"""
    )
    st.dataframe(tree, hide_index=True)


# ---------- Navigation ----------

PAGES = {
    "home": st.Page(home_page, title="Home", icon=":material/home:", default=True),
    "add": st.Page(add_expense_page, title="Add expense", icon=":material/add_circle:"),
    "expenses": st.Page(expenses_page, title="Expenses", icon=":material/receipt_long:"),
    "dashboard": st.Page(dashboard_page, title="Dashboard", icon=":material/bar_chart:"),
    "categories": st.Page(categories_page, title="Categories & budgets", icon=":material/category:"),
}
st.navigation(list(PAGES.values())).run()