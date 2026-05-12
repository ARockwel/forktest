"""
common.py — Palette, shared widget helpers, QueryResult, and LogPanel.
"""

import tkinter as tk
from tkinter import scrolledtext, ttk
import datetime

# ═══════════════════════════════════════════════════════════════════════════════
#  PALETTE & FONTS
# ═══════════════════════════════════════════════════════════════════════════════
PALETTE = {
    "bg":          "#0f1117",
    "surface":     "#1a1d27",
    "surface2":    "#22263a",
    "border":      "#2e3352",
    "accent":      "#f59e0b",
    "accent_text": "#fcd34d",
    "text":        "#e2e8f0",
    "text_dim":    "#8892aa",
    "error":       "#ef4444",
    "success":     "#22c55e",
    "warning":     "#f59e0b",
    "info":        "#60a5fa",
    "entry_bg":    "#0d1021",
}

FONT_MONO  = ("Consolas", 10)
FONT_SMALL = ("Segoe UI", 9)
FONT_TITLE = ("Segoe UI Semibold", 13)
FONT_HEAD  = ("Segoe UI Semibold", 11)
FONT_LABEL = ("Segoe UI", 10)


# ═══════════════════════════════════════════════════════════════════════════════
#  WIDGET HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def styled_label(parent, text: str, font=FONT_LABEL, color=None, **kw) -> tk.Label:
    kw.setdefault("bg", parent["bg"])
    kw["fg"] = color or PALETTE["text"]
    return tk.Label(parent, text=text, font=font, **kw)


def styled_entry(parent, width: int = 30, **kw) -> tk.Entry:
    kw.setdefault("bg", PALETTE["entry_bg"])
    kw.setdefault("fg", PALETTE["text"])
    kw.setdefault("insertbackground", PALETTE["accent"])
    kw.setdefault("relief", "flat")
    kw.setdefault("highlightthickness", 1)
    kw.setdefault("highlightcolor", PALETTE["accent"])
    kw.setdefault("highlightbackground", PALETTE["border"])
    kw.setdefault("font", FONT_MONO)
    return tk.Entry(parent, width=width, **kw)


def styled_button(parent, text: str, command, accent: bool = True,
                  width: int = 14, **kw) -> tk.Button:
    bg = PALETTE["accent"]      if accent else PALETTE["surface2"]
    fg = "#0f1117"              if accent else PALETTE["text"]
    ab = PALETTE["accent_text"] if accent else PALETTE["border"]
    btn = tk.Button(
        parent, text=text, command=command,
        bg=bg, fg=fg, activebackground=ab, activeforeground="#0f1117",
        relief="flat", bd=0, cursor="hand2",
        font=("Segoe UI Semibold", 10), width=width,
        padx=8, pady=6, **kw
    )
    def on_enter(e): btn.config(bg=PALETTE["accent_text"] if accent else PALETTE["border"])
    def on_leave(e): btn.config(bg=bg)
    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


def separator(parent, horizontal: bool = True) -> tk.Frame:
    if horizontal:
        return tk.Frame(parent, bg=PALETTE["border"], height=1)
    return tk.Frame(parent, bg=PALETTE["border"], width=1)


# ═══════════════════════════════════════════════════════════════════════════════
#  QUERY RESULT  — standard object every query module returns
# ═══════════════════════════════════════════════════════════════════════════════
class QueryResult:
    """
    Standardised result returned by every module in queries/.

    Attributes
    ----------
    success  : bool  — False only on a hard DB / query error
    status   : str   — "ok" | "issues_found" | "error"
    headline : str   — single-line summary shown in the UI status label
    messages : list  — (level, text) tuples written to the log panel
                       level: "info" | "success" | "warning" | "error" | "accent"
    data     : list  — raw rows returned by the query (strings)
    """
    def __init__(self):
        self.success   : bool        = True
        self.status    : str         = "ok"
        self.headline  : str         = ""
        self.messages  : list[tuple] = []
        self.data      : list[str]   = []
        self.cols      : list[str]   = []   # column names from cursor.description
        self.extracted : dict        = {}   # intermediate values for chained queries
        self.sql       : str         = ""   # SQL executed; surfaced via Copy Query
        self.dataframe : dict | None = None # {TBL_KEY: pd.DataFrame} from temp table parents

    def add_message(self, level: str, text: str):
        self.messages.append((level, text))


def build_values_cte(df, cte_name: str) -> str:
    """
    Build a SQL VALUES CTE from a pandas DataFrame so child queries can use it
    instead of a session-scoped #temp table, enabling parallel execution.

    Returns: WITH <cte_name> AS (SELECT * FROM (VALUES ...) AS _t(col1, col2))
    """
    import math
    import datetime
    import decimal
    cols     = list(df.columns)
    col_list = ', '.join(f'[{c}]' for c in cols)

    rows = []
    for _, row_data in df.iterrows():
        vals = []
        for v in row_data:
            if v is None:
                vals.append('NULL')
            elif isinstance(v, float) and math.isnan(v):
                vals.append('NULL')
            elif isinstance(v, str):
                vals.append("'" + v.replace("'", "''") + "'")
            elif isinstance(v, (datetime.datetime, datetime.date)):
                vals.append("'" + str(v) + "'")
            elif isinstance(v, (int, float, decimal.Decimal)):
                vals.append(str(v))
            else:
                vals.append("'" + str(v).replace("'", "''") + "'")
        rows.append('(' + ', '.join(vals) + ')')

    if not rows:
        null_vals = ', '.join(['NULL'] * len(cols))
        return (
            f'WITH {cte_name} AS (\n'
            f'  SELECT * FROM (VALUES ({null_vals})) AS _t({col_list})\n'
            f'  WHERE 1=0\n'
            f')'
        )

    values = ',\n      '.join(rows)
    return (
        f'WITH {cte_name} AS (\n'
        f'  SELECT * FROM (\n'
        f'    VALUES\n'
        f'      {values}\n'
        f'  ) AS _t({col_list})\n'
        f')'
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  LOG PANEL
# ═══════════════════════════════════════════════════════════════════════════════
class LogPanel(tk.Frame):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)

        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=6, padx=10)
        hdr.pack(fill="x")
        styled_label(hdr, "▸  Activity Log", font=FONT_HEAD,
                     color=PALETTE["text_dim"]).pack(side="left")
        tk.Button(
            hdr, text="Clear", bg=PALETTE["surface2"], fg=PALETTE["text_dim"],
            relief="flat", bd=0, cursor="hand2", font=FONT_SMALL,
            command=self.clear
        ).pack(side="right")

        self.text = scrolledtext.ScrolledText(
            self, wrap="word", state="disabled",
            bg=PALETTE["bg"], fg=PALETTE["text"],
            font=FONT_MONO, relief="flat", bd=0,
            insertbackground=PALETTE["accent"],
            selectbackground=PALETTE["border"],
        )
        self.text.pack(fill="both", expand=True)

        self.text.tag_config("ts",      foreground=PALETTE["text_dim"])
        self.text.tag_config("info",    foreground=PALETTE["info"])
        self.text.tag_config("success", foreground=PALETTE["success"])
        self.text.tag_config("error",   foreground=PALETTE["error"])
        self.text.tag_config("warning", foreground=PALETTE["warning"])
        self.text.tag_config("accent",  foreground=PALETTE["accent_text"])
        self.text.tag_config("result",  foreground=PALETTE["text"])

    def _append(self, level: str, message: str):
        self.text.config(state="normal")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.text.insert("end", f"[{ts}] ", "ts")
        self.text.insert("end", f"{message}\n", level)
        self.text.see("end")
        self.text.config(state="disabled")

    def info(self, msg):    self._append("info",    msg)
    def success(self, msg): self._append("success", msg)
    def error(self, msg):   self._append("error",   msg)
    def warning(self, msg): self._append("warning", msg)
    def accent(self, msg):  self._append("accent",  msg)
    def result(self, msg):  self._append("result",  msg)

    def flush_query_result(self, result: QueryResult):
        """Write all messages stored in a QueryResult into the log."""
        for level, text in result.messages:
            self._append(level, text)

    def clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

    def banner(self, text: str):
        line = "─" * 56
        self.result(line)
        self.accent(f"  {text}")
        self.result(line)


# ═══════════════════════════════════════════════════════════════════════════════
#  SCROLLABLE FRAME  — wraps any content in a canvas with a vertical scrollbar
# ═══════════════════════════════════════════════════════════════════════════════
class ScrollableFrame(tk.Frame):
    """
    Drop-in container whose .inner attribute is where you place child widgets.
    The frame scrolls vertically; mouse-wheel works while the cursor is inside.
    """
    def __init__(self, parent, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)

        self._canvas = tk.Canvas(self, bg=PALETTE["surface"],
                                 highlightthickness=0, bd=0)
        self._sb = ttk.Scrollbar(self, orient="vertical",
                                 command=self._canvas.yview)
        self.inner = tk.Frame(self._canvas, bg=PALETTE["surface"])

        self._win_id = self._canvas.create_window(
            (0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        self._canvas.configure(yscrollcommand=self._sb.set)
        self._sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        # Bind mouse wheel when cursor enters/leaves
        self._canvas.bind("<Enter>", self._bind_wheel)
        self._canvas.bind("<Leave>", self._unbind_wheel)
        self.inner.bind("<Enter>", self._bind_wheel)
        self.inner.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _e=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, e):
        self._canvas.itemconfig(self._win_id, width=e.width)

    def _bind_wheel(self, _e=None):
        self._canvas.bind_all("<MouseWheel>",   self._on_wheel)
        self._canvas.bind_all("<Button-4>",     self._on_wheel)
        self._canvas.bind_all("<Button-5>",     self._on_wheel)

    def _unbind_wheel(self, _e=None):
        self._canvas.unbind_all("<MouseWheel>")
        self._canvas.unbind_all("<Button-4>")
        self._canvas.unbind_all("<Button-5>")

    def _on_wheel(self, e):
        if e.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif e.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")


# ═══════════════════════════════════════════════════════════════════════════════
#  RESULT CARD  — reusable card used by all scenario files
# ═══════════════════════════════════════════════════════════════════════════════
class ResultCard(tk.Frame):
    """
    Displays the outcome of a single query module inside a scenario.
    Shows title, description, status, a scrollable data box, and copy buttons:
      - Copy Data           -> one entry per line, plain text
      - Copy Formatted Data -> ('id1', 'id2', ...) formatted for SQL IN clauses
      - Copy Query          -> the SQL that was executed (shown when result.sql is set)
    """
    def __init__(self, parent, title: str, description: str, **kw):
        kw.setdefault("bg", PALETTE["surface2"])
        super().__init__(parent, relief="flat", **kw)
        self._build(title, description)

    def _build(self, title, description):
        # Card header
        hdr = tk.Frame(self, bg=PALETTE["surface2"], padx=10, pady=6)
        hdr.pack(fill="x")

        self._status_icon = tk.Label(
            hdr, text="○", bg=PALETTE["surface2"],
            fg=PALETTE["text_dim"], font=("Consolas", 11))
        self._status_icon.pack(side="left", padx=(0, 6))

        tk.Label(hdr, text=title, bg=PALETTE["surface2"],
                 fg=PALETTE["text"], font=FONT_HEAD).pack(side="left")

        # Copy buttons — right-aligned, hidden until results arrive
        self._copy_sql_btn = styled_button(
            hdr, "Copy Formatted Data", self._copy_sql, accent=False, width=14)
        self._copy_sql_btn.pack(side="right", padx=(4, 0))
        self._copy_sql_btn.pack_forget()

        self._copy_btn = styled_button(
            hdr, "Copy Data", self._copy_ids, accent=False, width=10)
        self._copy_btn.pack(side="right")
        self._copy_btn.pack_forget()

        self._copy_query_btn = styled_button(
            hdr, "Copy Query", self._copy_query, accent=False, width=10)
        self._copy_query_btn.pack(side="right", padx=(0, 4))
        self._copy_query_btn.pack_forget()
        self._sql:  str       = ""
        self._cols: list[str] = []

        # Description
        tk.Label(self, text=description, bg=PALETTE["surface2"],
                 fg=PALETTE["text_dim"], font=FONT_SMALL,
                 justify="left", anchor="w", wraplength=560,
                 padx=10).pack(anchor="w", pady=(0, 4))

        separator(self).pack(fill="x")

        # Status line
        self._status_lbl = tk.Label(
            self, text="Waiting...",
            bg=PALETTE["surface2"], fg=PALETTE["text_dim"],
            font=FONT_SMALL, anchor="w", padx=10, pady=4)
        self._status_lbl.pack(fill="x")

        # Data box + resize grip
        self._data_box = scrolledtext.ScrolledText(
            self, height=4, state="disabled",
            bg=PALETTE["entry_bg"], fg=PALETTE["accent_text"],
            font=FONT_MONO, relief="flat", bd=0, wrap="word",
        )

        # Resize grip — drag to change data box height
        self._grip = tk.Frame(self, bg=PALETTE["border"], height=5, cursor="sb_v_double_arrow")
        self._grip_active = False
        self._grip_start_y = 0
        self._grip_start_h = 4

        def _grip_press(e):
            self._grip_active = True
            self._grip_start_y = e.y_root
            self._grip_start_h = self._data_box.cget("height")
            self._grip.bind_all("<Motion>",          _grip_drag)
            self._grip.bind_all("<ButtonRelease-1>", _grip_release)

        def _grip_drag(e):
            if not self._grip_active:
                return
            delta_px  = e.y_root - self._grip_start_y
            line_px   = self._data_box.tk.call("font", "metrics",
                            str(self._data_box.cget("font")), "-linespace")
            delta_lines = int(delta_px / max(int(line_px), 14))
            new_h = max(2, self._grip_start_h + delta_lines)
            self._data_box.config(height=new_h)

        def _grip_release(e):
            self._grip_active = False
            self._grip.unbind_all("<Motion>")
            self._grip.unbind_all("<ButtonRelease-1>")

        self._grip.bind("<ButtonPress-1>", _grip_press)
        self._grip.bind("<Enter>", lambda e: self._grip.config(bg=PALETTE["accent"]))
        self._grip.bind("<Leave>", lambda e: self._grip.config(bg=PALETTE["border"]))

    def _show_query_btn(self, sql: str):
        """Store the SQL and show the Copy Query button."""
        self._sql = sql
        if sql:
            self._copy_query_btn.pack(side="right", padx=(0, 4))

    def set_running(self):
        self._status_icon.config(text="○", fg=PALETTE["text_dim"])
        self._status_lbl.config(text="Running...", fg=PALETTE["text_dim"])
        self._data_box.pack_forget()
        self._grip.pack_forget()
        self._copy_btn.pack_forget()
        self._copy_sql_btn.pack_forget()
        self._copy_query_btn.pack_forget()

    def set_skipped(self, reason: str = "Skipped"):
        """Show a neutral skipped state — used when a prerequisite query failed."""
        self._status_icon.config(text="—", fg=PALETTE["text_dim"])
        self._status_lbl.config(text=f"—  {reason}", fg=PALETTE["text_dim"])
        self._data_box.pack_forget()
        self._grip.pack_forget()
        self._copy_btn.pack_forget()
        self._copy_sql_btn.pack_forget()
        self._copy_query_btn.pack_forget()

    def set_result(self, result):
        if result.sql:
            self._show_query_btn(result.sql)

        self._cols = result.cols

        if result.status == "error":
            self._status_icon.config(text="✘", fg=PALETTE["error"])
            self._status_lbl.config(text=result.headline, fg=PALETTE["error"])
            self._data_box.pack_forget()
            self._grip.pack_forget()
            self._copy_btn.pack_forget()
            self._copy_sql_btn.pack_forget()
        elif result.status == "issues_found":
            self._status_icon.config(text="✘", fg=PALETTE["error"])
            self._status_lbl.config(text=f"✘  {result.headline}", fg=PALETTE["error"])
            self._data_box.config(state="normal")
            self._data_box.delete("1.0", "end")
            self._data_box.insert("end", "\n".join(result.data))
            self._data_box.config(state="disabled")
            self._data_box.pack(fill="x", padx=10, pady=(4, 0))
            self._grip.pack(fill="x", padx=10, pady=(0, 6))
            self._copy_btn.pack(side="right")
            self._copy_sql_btn.pack(side="right", padx=(4, 0))
        else:
            self._status_icon.config(text="✔", fg=PALETTE["success"])
            self._status_lbl.config(text=f"✔  {result.headline}", fg=PALETTE["success"])
            if result.data:
                self._data_box.config(state="normal")
                self._data_box.delete("1.0", "end")
                self._data_box.insert("end", "\n".join(result.data))
                self._data_box.config(state="disabled")
                self._data_box.pack(fill="x", padx=10, pady=(4, 0))
                self._grip.pack(fill="x", padx=10, pady=(0, 6))
                self._copy_btn.pack(side="right")
                self._copy_sql_btn.pack(side="right", padx=(4, 0))
            else:
                self._data_box.pack_forget()
                self._grip.pack_forget()
                self._copy_btn.pack_forget()
                self._copy_sql_btn.pack_forget()

    def _get_ids(self) -> list:
        self._data_box.config(state="normal")
        raw = self._data_box.get("1.0", "end").strip()
        self._data_box.config(state="disabled")
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _copy_ids(self):
        ids = self._get_ids()
        lines = []
        if self._cols:
            lines.append(" | ".join(self._cols))
        lines.extend(ids)
        self.clipboard_clear()
        self.clipboard_append("\n".join(lines))
        self._copy_btn.config(text="Copied!")
        self.after(1800, lambda: self._copy_btn.config(text="Copy Data"))

    def _copy_query(self):
        self.clipboard_clear()
        self.clipboard_append(self._sql)
        self._copy_query_btn.config(text="Copied!")
        self.after(1800, lambda: self._copy_query_btn.config(text="Copy Query"))

    def _copy_sql(self):
        ids = self._get_ids()
        formatted = "(" + ", ".join(f"'{i}'" for i in ids) + ")"
        self.clipboard_clear()
        self.clipboard_append(formatted)
        self._copy_sql_btn.config(text="Copied!")
        self.after(1800, lambda: self._copy_sql_btn.config(text="Copy Formatted Data"))
