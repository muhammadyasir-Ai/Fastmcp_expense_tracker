import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "expenses.db"
OUT_PATH = Path.home() / "Desktop" / "expense_dashboard.html"

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Expense Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f6f8;color:#222}
header{padding:20px 24px;background:#1f2937;color:#fff}
h1{margin:0;font-size:22px}
.cards{display:flex;gap:16px;flex-wrap:wrap;padding:16px 24px}
.card{background:#fff;border-radius:10px;padding:16px 20px;flex:1;min-width:180px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card h3{margin:0 0 6px;font-size:13px;color:#666;font-weight:500}
.card p{margin:0;font-size:22px;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;padding:0 24px 24px}
.panel{background:#fff;border-radius:10px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.panel h2{font-size:15px;margin:0 0 10px}
</style></head>
<body>
<header><h1>Expense Dashboard</h1><div id="sub" style="font-size:13px;opacity:.8;margin-top:4px"></div></header>
<section class="cards">
  <div class="card"><h3>Is mahine ka kharch</h3><p id="spent"></p></div>
  <div class="card"><h3>Is mahine ka credit</h3><p id="credited"></p></div>
  <div class="card"><h3>Net</h3><p id="net"></p></div>
</section>
<section class="grid">
  <div class="panel"><h2>Category-wise kharch (is mahine)</h2><canvas id="pie"></canvas></div>
  <div class="panel"><h2>Mahinay ke hisaab se kharch aur credit</h2><canvas id="bars"></canvas></div>
  <div class="panel"><h2>Category trend (pichle 6 mahine)</h2><canvas id="trend"></canvas></div>
  <div class="panel"><h2>Budget vs kharch (is mahine)</h2><canvas id="budget"></canvas></div>
</section>
<script>
const DATA = __DATA__;
const fmt = n => "Rs. " + Number(n).toLocaleString(undefined, {maximumFractionDigits: 0});
document.getElementById("sub").textContent = "Generated: " + DATA.generated + " | Current month: " + DATA.current;
document.getElementById("spent").textContent = fmt(DATA.totals.spent);
document.getElementById("credited").textContent = fmt(DATA.totals.credited);
document.getElementById("net").textContent = fmt(DATA.totals.spent - DATA.totals.credited);

new Chart(document.getElementById("pie"), {
  type: "doughnut",
  data: {labels: DATA.pie.labels, datasets: [{data: DATA.pie.values}]},
  options: {plugins: {legend: {position: "bottom"}}}
});
new Chart(document.getElementById("bars"), {
  type: "bar",
  data: {labels: DATA.months, datasets: [
    {label: "Kharch", data: DATA.monthly.spent, backgroundColor: "#ef4444"},
    {label: "Credit", data: DATA.monthly.credited, backgroundColor: "#22c55e"}
  ]},
  options: {scales: {y: {beginAtZero: true}}}
});
new Chart(document.getElementById("trend"), {
  type: "line",
  data: {labels: DATA.months, datasets: DATA.trend.map(t => ({label: t.name, data: t.values, tension: 0.3}))},
  options: {scales: {y: {beginAtZero: true}}}
});
new Chart(document.getElementById("budget"), {
  type: "bar",
  data: {labels: DATA.budget.map(b => b.name), datasets: [
    {label: "Budget", data: DATA.budget.map(b => b.limit), backgroundColor: "#93c5fd"},
    {label: "Kharch", data: DATA.budget.map(b => b.spent), backgroundColor: "#f97316"}
  ]},
  options: {indexAxis: "y", scales: {x: {beginAtZero: true}}}
});
</script>
</body></html>
"""


def last_months(n):
    today = date.today()
    y, m = today.year, today.month
    out = []
    for i in range(n - 1, -1, -1):
        mm, yy = m - i, y
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy}-{mm:02d}")
    return out


def main():
    months = last_months(6)
    current = months[-1]
    start = months[0] + "-01"
    idx = {m: i for i, m in enumerate(months)}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    now_rows = conn.execute(
        "SELECT entry_type, ROUND(SUM(amount), 2) AS total FROM expenses "
        "WHERE substr(entry_date, 1, 7) = ? GROUP BY entry_type",
        (current,),
    ).fetchall()
    now_totals = {r["entry_type"]: r["total"] for r in now_rows}

    monthly = {"spent": [0] * len(months), "credited": [0] * len(months)}
    for r in conn.execute(
        "SELECT substr(entry_date, 1, 7) AS m, entry_type, ROUND(SUM(amount), 2) AS total "
        "FROM expenses WHERE entry_date >= ? GROUP BY m, entry_type",
        (start,),
    ).fetchall():
        if r["m"] in idx:
            key = "spent" if r["entry_type"] == "debit" else "credited"
            monthly[key][idx[r["m"]]] = r["total"]

    series = {}
    for r in conn.execute(
        """SELECT substr(e.entry_date, 1, 7) AS m, c.name, ROUND(SUM(e.amount), 2) AS total
           FROM expenses e JOIN categories c ON c.id = e.category_id
           WHERE e.entry_type = 'debit' AND e.entry_date >= ?
           GROUP BY m, c.name""",
        (start,),
    ).fetchall():
        if r["m"] in idx:
            series.setdefault(r["name"], [0] * len(months))[idx[r["m"]]] = r["total"]

    pie = [(name, vals[-1]) for name, vals in sorted(series.items()) if vals[-1] > 0]

    budget_rows = conn.execute(
        """SELECT c.name, b.monthly_limit AS limit_amt,
                  COALESCE((SELECT SUM(e.amount) FROM expenses e
                            WHERE e.category_id = b.category_id AND e.entry_type = 'debit'
                            AND substr(e.entry_date, 1, 7) = ?), 0) AS spent
           FROM budgets b JOIN categories c ON c.id = b.category_id
           ORDER BY c.name""",
        (current,),
    ).fetchall()
    conn.close()

    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "current": current,
        "months": months,
        "totals": {
            "spent": now_totals.get("debit", 0) or 0,
            "credited": now_totals.get("credit", 0) or 0,
        },
        "pie": {"labels": [n for n, _ in pie], "values": [v for _, v in pie]},
        "monthly": monthly,
        "trend": [{"name": n, "values": v} for n, v in sorted(series.items())],
        "budget": [
            {"name": r["name"], "limit": r["limit_amt"], "spent": round(r["spent"], 2)}
            for r in budget_rows
        ],
    }

    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard ban gaya: {OUT_PATH}")


if __name__ == "__main__":
    main()