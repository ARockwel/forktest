# Warehouse Diagnostic Tool

A desktop troubleshooting utility for warehouse management systems. Connects to SQL Server databases and runs targeted diagnostic queries to surface common operational issues — with copy-ready remediation scripts where applicable.

---

## Prerequisites

Before using the batch launcher, ensure you have these installed from the Software Portal:

- **Git for Windows** — Required for cloning and updating the repository
- **Python 3.10+** — Required to run the application
- **ODBC Driver 17 for SQL Server** — (likely already installed if you have SSMS or VSCode database extensions)

> If any of these are missing, install them from the Software Portal and restart your computer before running `run_wdt.bat`.

---

## Quick Start — One-Click Launcher

1. **Download `run_wdt.bat`** from the repository [HERE](https://github.com/SF-jbs/WDT/releases/tag/1.00.00_installer)
2. **Save it to your Desktop** (or anywhere convenient)
3. **Double-click `run_wdt.bat`**

The batch script will automatically:
- Clone the WDT repository (if not already present)
- Create a Python virtual environment
- Install all dependencies
- Launch the application

**To pin to taskbar:**
- Right-click `run_wdt.bat` → **Send to** → **Desktop (create shortcut)**
- Right-click the shortcut → **Pin to taskbar**

---

## Manual Setup — VS Code Development

If you prefer to develop in VS Code instead of using the batch launcher:

1. **Clone the repository:**

   ```bash
   mkdir C:\Users\<your username>\Workspace
   cd C:\Users\<your username>\Workspace
   git clone https://github.com/SF-jbs/WDT.git
   cd WDT
   ```

3. **Opens new window in VS Code for the project:**
   ```bash
   code .
   ```

4. **Set up Python environment (recommended):**
   - Open the Command Palette (`Ctrl+Shift+P`)
   - Search for **Python: Create Environment** and select **Venv**
   - Select the Python 3.10+ interpreter
      - if python is not available, locate it in Software Portal and install.
      - reboot pc after install
   - Wait for the virtual environment to initialize

5. **Install dependencies:**
   - Open Terminal in VS Code (`Ctrl+``)
   - Run:
    ```bash
    pip install -r Requirements.txt
    ```

6. **Run the application:**
   - In VS Code Terminal, run: `python warehouse_diagnostics.py`
   - Or use the Run button (▶) if you have a Python extension configured

---

## Contributing — Fork & Pull Request

Org members have read access to `SF-jbs/WDT`. To contribute changes, fork the repo and submit a PR.

1. **Fork the repository:**
   - Go to [github.com/SF-jbs/WDT](https://github.com/SF-jbs/WDT)
   - Click **Fork** (top-right) — this creates `your-username/WDT` under your own GitHub account

2. **Clone your fork:**
   ```bash
   mkdir C:\Users\<your username>\Workspace
   cd C:\Users\<your username>\Workspace
   git clone https://github.com/<your-username>/WDT.git
   cd WDT
   ```

3. **Configure your Git identity (one-time setup):**
   ```bash
   git config --local user.name "Your Name"
   git config --local user.email "your.email@company.com"
   ```

4. **Authenticate with GitHub:**
   - Use a Personal Access Token (PAT)
   - Go to [GitHub Settings → Developer Settings → Personal Access Tokens](https://github.com/settings/tokens)
   - Create a token with `repo` scope
   - VS Code will prompt for credentials on first push — paste the token when asked

5. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

6. **Make your changes and commit:**
   - Edit files as needed
   - Open the Source Control panel in VS Code (`Ctrl+Shift+G`)
   - Stage changes and write a clear commit message
   - Click **Commit**

7. **Push your branch to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

8. **Open a Pull Request:**
   - Go to [github.com/SF-jbs/WDT](https://github.com/SF-jbs/WDT)
   - Click **Pull requests** → **New pull request**
   - Click **compare across forks**, select your fork and branch as the source
   - Add a description and submit

9. **Keep your fork up to date:**
   ```bash
   git remote add upstream https://github.com/SF-jbs/WDT.git
   git fetch upstream
   git merge upstream/main
   ```

---

> **Graph Editor** (optional): the Query Builder's web-based DAG editor requires Flask, which is included in `Requirements.txt`. If you skip it, the Graph Editor button will be hidden but everything else works.

---

## Setup

1. Run the application:

```bash
python warehouse_diagnostics.py
```

2. Use **⚙ Settings** in the sidebar to add your plant connections and configure business units — no manual JSON editing required.

Alternatively, edit `plants.json` directly (see [Configuration](#configuration)).

---

## Configuration

### plants.json

Plant connections live in `plants.json` in the root directory. You can edit this file directly or use the Settings screen inside the app.

```json
{
  "plants": [
    {
      "name":        "Springfield Plant",
      "code":        "SPF",
      "server":      "SPRFLD-SQL01",
      "database":    "WarehouseDB",
      "environment": "PROD",
      "notes":       "Main production facility. Use with caution."
    }
  ]
}
```
|     Field     |                            Description                                    |
|---------------|---------------------------------------------------------------------------|
|     `name`    | Display name shown in the plant picker                                    |
|     `code`    | Short identifier (e.g. `SPF`)                                             |
|    `server`   | SQL Server hostname or IP                                                 |
|   `database`  | Database name                                                             |
| `environment` | `PROD`, `QA`, or `IWS` — controls which scenarios appear after connecting |
|    `notes`    | Optional reminder shown in the connection panel                           |

All connections use Windows Authentication. No passwords are stored or required.

### business_units.json

Controls the Business Unit filter in the sidebar. Edit via **⚙ Settings** or directly:

```json
["Beef/Pork", "Poultry", "Case-Ready"]
```

---

## Sidebar Filters

Two filters above the scenario list control what is visible:

- **Environment filter** — shows only scenarios compatible with the connected plant's environment (`PROD`, `QA`, `IWS`)
- **Business Unit filter** — further filters by business unit (`Beef/Pork`, `Poultry`, `Case-Ready`, or `All`)

---

## Utilities

These buttons are always visible in the sidebar regardless of connection state.

### ⚙ Query Builder

Build custom diagnostic scenarios without writing Python code.

**Form editor:**
- Define queries with multi-block SQL, `@variable` parameters, and labels
- Declare extracted value chains (output of query A feeds input of query B)
- Temp table dependencies (`#table`) are auto-detected from SQL
- Parameters are auto-detected as you type

**Graph editor** (requires Flask):
- Opens a web-based DAG view in your browser showing the execution graph
- Drag between nodes to add extracted-value dependencies
- Blue dashed edges = temp table deps (auto-detected, read-only)
- Orange solid edges = extracted value chains (editable)

**Generate Files:**
- Writes `queries/query_<prefix>_<id>.py` and `scenarios/scenario_<prefix>.py`
- Generated scenario uses the correct parallel/sequential topology automatically:
  - Independent queries → parallel threads
  - Temp table chains → single shared cursor, sequential
  - Extracted value chains → sequential within the chain, parallel across independent chains
- Saves a draft JSON automatically so you can reopen and modify later
- Offers to add the import and `SCENARIOS` entry to `warehouse_diagnostics.py`

**Drafts** are saved to `query_builder/specs/<prefix>.json`. Delete Draft removes the JSON and all associated generated files in one step.

### ⚙ Settings

Edit configuration without touching JSON files:

- **Plants** — add, edit, or remove plant connections. Changes take effect immediately after saving (no restart required).
- **Business Units** — manage the list used by the sidebar BU filter.

---

## Result Cards

Each query result is displayed as a card showing:

- **Status line** — green on pass, red on issue found
- **Scrollable data box** — IDs, values, or script lines (drag the grip bar to resize)
- **Copy Data** — copies results as plain text, one entry per line
- **Copy Formatted Data** — copies results as a SQL `IN` clause: `('id1', 'id2', ...)`

---

## Activity Log

Records all connection events and query results with timestamps. Use **Clear** to reset. The divider between content and log is draggable.

---

## Adding a New Scenario

### Option A — Query Builder (recommended)

Use the **⚙ Query Builder** in the sidebar. No Python required. Define your SQL, parameters, and dependencies in the form editor, then click **Generate Files**. The generated files slot directly into the existing tool.

### Option B — Manual

**1. Create a query module — `queries/your_query.py`**

```python
from common import QueryResult
from db import db

TITLE       = "My Check"
DESCRIPTION = "What this check looks for."

SQL = "SELECT ... FROM ..."

def run() -> QueryResult:
    result = QueryResult()
    result.add_message("info", f"[{TITLE}] Running...")
    try:
        cursor = db.conn.cursor()
        cursor.execute(SQL)
        rows = cursor.fetchall()
    except Exception as exc:
        result.success  = False
        result.status   = "error"
        result.headline = f"{TITLE}: Query error — {exc}"
        result.add_message("error", result.headline)
        return result

    if rows:
        result.status   = "issues_found"
        result.headline = f"{len(rows)} issue(s) found."
        result.data     = [str(row[0]) for row in rows]
        result.add_message("error", f"  ✘ {result.headline}")
    else:
        result.status   = "ok"
        result.headline = "No issues found."
        result.add_message("success", f"  ✔ {TITLE}: {result.headline}")

    return result
```

**2. Create a scenario module — `scenarios/your_scenario.py`**

```python
class ScenarioMyCheck(tk.Frame):
    TITLE          = "My Check"
    ICON           = "◈"
    ENVIRONMENTS   = ["PROD", "QA"]
    BUSINESS_UNITS = ["Beef/Pork"]
```

**3. Register in `warehouse_diagnostics.py`**

```python
from scenarios.your_scenario import ScenarioMyCheck

SCENARIOS = [
    ...
    ScenarioMyCheck,
]
```

---

## Project Structure

```
warehouse_diagnostics.py        Main entry point and application window
common.py                       Palette, fonts, shared widgets, QueryResult, LogPanel
db.py                           Database singleton, Plant dataclass, plants.json loader
plants.json                     Plant connection config (edit via Settings or directly)
business_units.json             Business unit list (edit via Settings or directly)
Requirements.txt

queries/                        One file per SQL check (query_*.py)
scenarios/                      One file per scenario panel (scenario_*.py)

query_builder/                  Query Builder internals — do not modify
    __init__.py
    model.py                    ScenarioSpec / QuerySpec dataclasses + JSON serialisation
    analyzer.py                 SQL analysis: @variable detection, temp table detection, topology
    codegen.py                  Python source generation from ScenarioSpec
    server.py                   Flask daemon for the web-based graph editor
    graph.html                  vis.js DAG editor single-page app
    vis-network.min.js          Bundled vis-network (no CDN dependency)
    specs/                      Draft JSON files (one per in-progress scenario)
```
