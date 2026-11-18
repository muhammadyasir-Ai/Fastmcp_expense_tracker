💰 Fast Expense Tracker

A personal expense tracker built with Python. Log daily spending in seconds, organize it by category and subcategory, set monthly budgets, and see where your money goes. The same data is also available to AI assistants through a FastMCP server.

Currency is PKR by default, and all data is stored locally in SQLite.

✨ Features
Quick entry: add, edit, search and delete expenses (amount, category, subcategory, date and note)
Categories and subcategories: create, rename and delete your own, with sensible defaults (Food, Health, Education, Transport, Bills)
Monthly budgets: set a limit per category and track budget vs. spending
Insights: spending by category, monthly trend and monthly report
Streamlit dashboard: a clean, colorful web app to use every day
HTML dashboard: a standalone page with charts (pie, monthly bars, 6-month trend, budget vs. spending)
CSV export: download your expenses for Excel or other tools
AI assistant access: FastMCP tools (add, list, search, edit, delete, summary, monthly report, budgets, export) for use with Claude Desktop or any MCP client
🧰 Tech stack
Part	Technology
Web app	Streamlit
AI integration	FastMCP (Model Context Protocol)
Data	SQLite, pandas
Charts	Chart.js (HTML dashboard)
📁 Project structure
streamlit_app.py   Streamlit web app (main daily interface)
main.py            FastMCP server with expense tools for AI assistants
dashboard.py       Builds a standalone HTML dashboard with charts
pyproject.toml     Project metadata and dependencies
uv.lock            Locked dependency versions (for uv)
⚙️ Setup

Requirements: Python 3.10 or newer.

Clone the repository:
bash
git clone https://github.com/muhammadyasir-Ai/Fastmcp_expense_tracker.git
cd Fastmcp_expense_tracker
Create and activate a virtual environment:
bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux
Install the dependencies:
bash
pip install fastmcp pandas streamlit

If you use uv, run uv sync instead.

▶️ How to run

Streamlit app (daily use):

bash
streamlit run streamlit_app.py

Open http://localhost:8501 in your browser.

HTML dashboard:

bash
python dashboard.py

This creates expense_dashboard.html on your Desktop. Open it in any browser.

MCP server for AI assistants (local, stdio):

bash
python main.py

Example config for Claude Desktop (claude_desktop_config.json):

json
{
  "mcpServers": {
    "expense-tracker": {
      "command": "python",
      "args": ["C:/path/to/Fastmcp_expense_tracker/main.py"]
    }
  }
}

MCP server over HTTP (remote):

bash
set MCP_TRANSPORT=http
set PORT=8000
python main.py
🗄️ Data
Expenses, categories and budgets are stored in expenses.db in the project folder.
To use a different location, set the EXPENSE_DB_PATH environment variable.
expenses.db is ignored by Git, so your personal data is never uploaded.
🔒 Privacy

All data stays on your computer. No account or internet connection is needed to track expenses (only the Chart.js library loads from a CDN in the HTML dashboard).

🚀 Future ideas
Income tracking and savings goals
Recurring expenses (bills, subscriptions)
Charts and alerts inside the Streamlit app
👤 Author

Muhammad Yasir, Computer Science graduate (KUST)

GitHub: muhammadyasir-Ai
LinkedIn: muhammad-yasir-17211a423
Portfolio: muhammadyasir-ai.github.io/portfolio
