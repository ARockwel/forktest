"""
scenarios/scenario_query_builder.py

The Query Builder — lets users define SQL queries, declare parameters and
dependencies, and generate ready-to-use query_*.py + scenario_*.py files.

No database connection is required to build or save drafts.
A connection is only needed to test the generated scenario.

Two views:
  Form View  — primary editor (always available)
  Graph View — web-based DAG editor launched via a local Flask server
               (requires:  pip install flask)
"""

import json
import os
import re
import tkinter as tk
from tkinter import messagebox, scrolledtext
from tkinter import ttk

from common import (
    PALETTE, FONT_MONO, FONT_SMALL, FONT_TITLE, FONT_HEAD,
    styled_label, styled_entry, styled_button, separator,
    LogPanel,
)

from query_builder.model    import ScenarioSpec, QuerySpec, SqlBlock, ParameterSpec, DependencyEdge
from query_builder.analyzer import (
    detect_parameters, detect_output_columns,
    refresh_temp_table_detection, refresh_dataframe_detection,
)
from query_builder import server as qb_server
from query_builder import codegen as qb_codegen

# Directory where draft JSON files are saved
_SPECS_DIR = os.path.join(os.path.dirname(__file__), '..', 'query_builder', 'specs')

# Business units config — loaded once at import time
_BU_CONFIG   = os.path.join(os.path.dirname(__file__), '..', 'business_units.json')
_ICONS_CONFIG = os.path.join(os.path.dirname(__file__), '..', 'icons.json')

_DEFAULT_ICONS = ["◈","⚙","🔍","🔧","⚠","📦","🚚","🏭","📋","🔑","⬡","🗂","📊","🔗","⛓","🛠","🧩","📌","🔄","✅"]

def _load_business_units() -> list[str]:
    try:
        with open(_BU_CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return ["Beef/Pork", "Poultry", "Case-Ready"]

def _load_icons() -> list[str]:
    try:
        with open(_ICONS_CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return _DEFAULT_ICONS

_BUSINESS_UNITS = _load_business_units()


# ═══════════════════════════════════════════════════════════════════════════════
#  QUERY EDITOR MODAL
# ═══════════════════════════════════════════════════════════════════════════════

class QueryEditorModal(tk.Toplevel):
    """
    Modal window for editing a single QuerySpec.
    Sections: Title/Description, SQL Blocks, Parameters (auto-detected),
              Gives (extracted keys produced), Takes (upstream dependencies).
    """

    def __init__(self, parent, query: QuerySpec, all_queries: list[QuerySpec], on_save):
        super().__init__(parent)
        self.title("Edit Query")
        self.configure(bg=PALETTE["surface"])
        self.resizable(True, True)
        self.geometry("780x700")
        self.minsize(640, 500)

        # Make modal
        self.transient(parent)
        self.grab_set()

        self._query      = query
        self._all_queries = all_queries
        self._on_save    = on_save
        self._block_widgets:    list[dict] = []  # {frame, label_var, sql_text}
        self._gives_vars:       list[tk.StringVar] = []
        self._gives_comboboxes: list[ttk.Combobox] = []  # refreshed when SQL changes
        self._takes_rows:       list[dict] = []  # {frame, src_var, key_var, key_cb, param_var, title_to_id}
        self._df_var     = tk.BooleanVar()        # "Create DataFrame" checkbox
        self._df_key_var = tk.StringVar()         # DataFrame key name
        self._df_key_edited = False               # True once user manually edits the key

        self._build()
        self._populate()
        self.focus_set()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Scrollable main area
        outer = tk.Frame(self, bg=PALETTE["surface"])
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=PALETTE["surface"],
                           highlightthickness=0, bd=0)
        vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(canvas, bg=PALETTE["surface"])
        self._win_id = canvas.create_window((0, 0), window=self._inner,
                                             anchor="nw")

        def _on_resize(e):
            canvas.itemconfig(self._win_id, width=e.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self._inner.bind("<Configure>", _on_frame)

        def _scroll(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _scroll)

        self._canvas = canvas
        self._build_inner(self._inner)

        # Bottom button bar
        bar = tk.Frame(self, bg=PALETTE["surface2"], pady=8, padx=14)
        bar.pack(fill="x", side="bottom")
        styled_button(bar, "Save", self._save, width=12).pack(side="right", padx=(8, 0))
        styled_button(bar, "Cancel", self.destroy, accent=False, width=12).pack(side="right")

    def _build_inner(self, parent):
        p = parent
        pad = {"padx": 14, "pady": 6}

        # ── Title / Description ───────────────────────────────────────────────
        tk.Frame(p, bg=PALETTE["surface2"], pady=10, padx=14).pack(fill="x")
        sec = tk.Frame(p, bg=PALETTE["surface"], **pad)
        sec.pack(fill="x")

        styled_label(sec, "Title", font=FONT_HEAD,
                     color=PALETTE["text"]).pack(anchor="w", pady=(0, 3))
        self._title_var = tk.StringVar()
        styled_entry(sec).config(textvariable=self._title_var)
        e = styled_entry(sec, width=50)
        e.config(textvariable=self._title_var)
        e.pack(fill="x", ipady=4, pady=(0, 8))

        styled_label(sec, "Description", font=FONT_HEAD,
                     color=PALETTE["text"]).pack(anchor="w", pady=(0, 3))
        self._desc_text = tk.Text(sec, height=3, bg=PALETTE["entry_bg"],
                                   fg=PALETTE["text"], font=FONT_MONO,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=PALETTE["border"],
                                   highlightcolor=PALETTE["accent"],
                                   insertbackground=PALETTE["accent"])
        self._desc_text.pack(fill="x")

        separator(p).pack(fill="x", padx=10, pady=8)

        # ── SQL Blocks ────────────────────────────────────────────────────────
        sql_hdr = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        sql_hdr.pack(fill="x")
        styled_label(sql_hdr, "SQL Blocks", font=FONT_HEAD,
                     color=PALETTE["info"]).pack(side="left")
        styled_button(sql_hdr, "+ Add Block", self._add_block,
                      accent=False, width=12).pack(side="right")

        self._blocks_frame = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        self._blocks_frame.pack(fill="x", pady=(6, 0))

        separator(p).pack(fill="x", padx=10, pady=8)

        # ── Parameters (auto-detected) ────────────────────────────────────────
        styled_label(p, "  Parameters  (auto-detected from SQL @variables)",
                     font=FONT_HEAD, color=PALETTE["info"]).pack(
                     anchor="w", padx=14, pady=(0, 4))
        styled_label(p, "  Set a label for each parameter — this is what users see in the scenario UI.",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(
                     anchor="w", padx=14, pady=(0, 6))

        self._params_frame = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        self._params_frame.pack(fill="x")

        separator(p).pack(fill="x", padx=10, pady=8)

        # ── DataFrame ─────────────────────────────────────────────────────────
        df_sec = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        df_sec.pack(fill="x")
        df_row = tk.Frame(df_sec, bg=PALETTE["surface"])
        df_row.pack(fill="x", pady=(0, 4))

        tk.Checkbutton(
            df_row, text="Create DataFrame from this query's result",
            variable=self._df_var,
            bg=PALETTE["surface"], fg=PALETTE["text"],
            selectcolor=PALETTE["entry_bg"],
            activebackground=PALETTE["surface"],
            activeforeground=PALETTE["accent_text"],
            font=FONT_SMALL,
            command=self._on_df_toggle,
        ).pack(side="left")

        self._df_key_frame = tk.Frame(df_sec, bg=PALETTE["surface"])
        self._df_key_frame.pack(fill="x", pady=(0, 6))
        styled_label(self._df_key_frame, "Key name", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))
        e_df_key = styled_entry(self._df_key_frame, width=22)
        e_df_key.config(textvariable=self._df_key_var)
        e_df_key.pack(side="left", ipady=4)
        styled_label(self._df_key_frame,
                     "— use this name as a table in child queries",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(side="left", padx=(8, 0))
        e_df_key.bind("<Key>", lambda _: setattr(self, '_df_key_edited', True))

        # Auto-populate key from query title
        def _on_title_change_df(*_):
            if not self._df_key_edited:
                slug = re.sub(r'[^a-zA-Z0-9]+', '_',
                              self._title_var.get().strip()).strip('_')
                self._df_key_var.set(slug)
        self._title_var.trace_add("write", _on_title_change_df)

        self._on_df_toggle()  # set initial visibility

        separator(p).pack(fill="x", padx=10, pady=8)

        # ── Gives ─────────────────────────────────────────────────────────────
        gives_hdr = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        gives_hdr.pack(fill="x")
        styled_label(gives_hdr, "Gives  (extracted keys this query produces)",
                     font=FONT_HEAD, color=PALETTE["info"]).pack(side="left")
        styled_button(gives_hdr, "+ Add Key", self._add_give,
                      accent=False, width=12).pack(side="right")
        styled_label(p, "  Declare each key your run() function writes to result.extracted.",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(
                     anchor="w", padx=14, pady=(4, 6))

        self._gives_frame = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        self._gives_frame.pack(fill="x")

        separator(p).pack(fill="x", padx=10, pady=8)

        # ── Takes ─────────────────────────────────────────────────────────────
        takes_hdr = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        takes_hdr.pack(fill="x")
        styled_label(takes_hdr, "Takes  (values received from upstream queries)",
                     font=FONT_HEAD, color=PALETTE["info"]).pack(side="left")
        styled_button(takes_hdr, "+ Add Dep", self._add_take,
                      accent=False, width=12).pack(side="right")
        styled_label(p,
                     "  For each dependency: pick the upstream query, the key it puts in "
                     "result.extracted,\n  and the @variable in this query's SQL that receives it.",
                     font=FONT_SMALL, color=PALETTE["text_dim"], justify="left").pack(
                     anchor="w", padx=14, pady=(4, 6))

        self._takes_frame = tk.Frame(p, bg=PALETTE["surface"], padx=14)
        self._takes_frame.pack(fill="x", pady=(0, 14))

    # ── Populate from query ───────────────────────────────────────────────────

    def _populate(self):
        q = self._query
        self._title_var.set(q.title)
        self._desc_text.insert("1.0", q.description)

        for block in q.sql_blocks:
            self._add_block(label=block.label, sql=block.sql)

        if not q.sql_blocks:
            self._add_block()

        self._refresh_params()

        self._df_var.set(q.creates_dataframe)
        self._df_key_var.set(q.dataframe_key)
        self._df_key_edited = bool(q.dataframe_key)
        self._on_df_toggle()

        for key in q.gives:
            self._add_give(key=key)

        for edge in q.takes:
            self._add_take(edge=edge)

    def _on_df_toggle(self):
        if self._df_var.get():
            self._df_key_frame.pack(fill="x", pady=(0, 6))
        else:
            self._df_key_frame.pack_forget()

    # ── SQL blocks ────────────────────────────────────────────────────────────

    def _add_block(self, label: str = "", sql: str = ""):
        idx = len(self._block_widgets)
        frame = tk.Frame(self._blocks_frame, bg=PALETTE["surface2"],
                         padx=10, pady=8, bd=1, relief="flat",
                         highlightthickness=1,
                         highlightbackground=PALETTE["border"])
        frame.pack(fill="x", pady=(0, 8))

        hdr = tk.Frame(frame, bg=PALETTE["surface2"])
        hdr.pack(fill="x")
        styled_label(hdr, f"Block {idx + 1}",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(side="left")

        label_var = tk.StringVar(value=label or f"Block {idx + 1}")
        lbl_entry = styled_entry(hdr, width=28)
        lbl_entry.config(textvariable=label_var)
        lbl_entry.pack(side="left", padx=(8, 0), ipady=3)

        def _remove(f=frame, data=None):
            f.destroy()
            self._block_widgets = [w for w in self._block_widgets if w["frame"] != f]
            self._refresh_params()

        styled_button(hdr, "×", _remove, accent=False, width=3).pack(side="right")

        sql_text = tk.Text(frame, height=10, bg=PALETTE["entry_bg"],
                           fg=PALETTE["text"], font=FONT_MONO,
                           relief="flat", highlightthickness=1,
                           highlightbackground=PALETTE["border"],
                           highlightcolor=PALETTE["accent"],
                           insertbackground=PALETTE["accent"],
                           tabs="4")
        sql_text.pack(fill="x", pady=(6, 0))
        if sql:
            sql_text.insert("1.0", sql)

        # Refresh param detection whenever SQL changes
        sql_text.bind("<KeyRelease>", lambda e: self.after(300, self._refresh_params))

        widget_data = {"frame": frame, "label_var": label_var, "sql_text": sql_text}
        self._block_widgets.append(widget_data)

    # ── Column detection helpers ──────────────────────────────────────────────

    def _current_output_columns(self) -> list[str]:
        """Return column names detected from the current SQL blocks."""
        combined = "\n".join(
            w["sql_text"].get("1.0", "end") for w in self._block_widgets
        )
        return detect_output_columns(combined)

    @staticmethod
    def _query_output_columns(query: QuerySpec) -> list[str]:
        """Return column names detected from a saved QuerySpec's SQL."""
        return detect_output_columns(query.combined_sql())

    # ── Parameter detection ───────────────────────────────────────────────────

    def _refresh_params(self):
        """Re-detect @variables from all SQL blocks and rebuild the params UI."""
        # Collect SQL from all blocks
        combined = "\n".join(
            w["sql_text"].get("1.0", "end") for w in self._block_widgets
        )
        detected = detect_parameters(combined)

        # Preserve existing label/default for known params
        existing = {p.name: p for p in self._query.parameters}

        for widget in self._params_frame.winfo_children():
            widget.destroy()
        self._param_widgets = {}

        if not detected:
            styled_label(self._params_frame,
                         "(no @variables detected in SQL)",
                         font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w")
            return

        # Header row
        hdr = tk.Frame(self._params_frame, bg=PALETTE["surface"])
        hdr.pack(fill="x", pady=(0, 4))
        for col, w in [("@variable", 18), ("Label (shown in UI)", 24), ("Default value", 18)]:
            styled_label(hdr, col, font=FONT_SMALL,
                         color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))

        for name in detected:
            prev = existing.get(name)
            row  = tk.Frame(self._params_frame, bg=PALETTE["surface"])
            row.pack(fill="x", pady=2)

            styled_label(row, f"@{name}", font=FONT_MONO,
                         color=PALETTE["accent_text"]).pack(side="left", padx=(0, 8))

            label_var   = tk.StringVar(value=prev.label   if prev else name)
            default_var = tk.StringVar(value=prev.default if prev else "")

            lbl_e = styled_entry(row, width=22)
            lbl_e.config(textvariable=label_var)
            lbl_e.pack(side="left", padx=(0, 8), ipady=3)

            def_e = styled_entry(row, width=16)
            def_e.config(textvariable=default_var)
            def_e.pack(side="left", ipady=3)

            self._param_widgets[name] = (label_var, default_var)

        # Refresh Gives combobox values to match updated SQL
        cols = self._current_output_columns()
        for cb in self._gives_comboboxes:
            cb['values'] = cols

    # ── Gives ─────────────────────────────────────────────────────────────────

    def _add_give(self, key: str = ""):
        row = tk.Frame(self._gives_frame, bg=PALETTE["surface"])
        row.pack(fill="x", pady=2)

        var  = tk.StringVar(value=key)
        cols = self._current_output_columns()
        cb   = ttk.Combobox(row, textvariable=var, values=cols,
                            width=26, font=FONT_MONO)
        cb.pack(side="left", ipady=3, padx=(0, 8))

        def _remove(f=row, v=var, c=cb):
            f.destroy()
            if v in self._gives_vars:
                self._gives_vars.remove(v)
            if c in self._gives_comboboxes:
                self._gives_comboboxes.remove(c)

        styled_button(row, "×", _remove, accent=False, width=3).pack(side="left")
        self._gives_vars.append(var)
        self._gives_comboboxes.append(cb)

    # ── Takes ─────────────────────────────────────────────────────────────────

    def _add_take(self, edge: DependencyEdge | None = None):
        row = tk.Frame(self._takes_frame, bg=PALETTE["surface2"],
                       padx=8, pady=6, highlightthickness=1,
                       highlightbackground=PALETTE["border"])
        row.pack(fill="x", pady=(0, 6))

        # Source query dropdown — display titles, store IDs via mapping
        other_queries  = [q for q in self._all_queries if q.id != self._query.id]
        id_to_title    = {q.id: (q.title or q.id) for q in other_queries}
        title_to_id    = {(q.title or q.id): q.id  for q in other_queries}
        display_opts   = [q.title or q.id for q in other_queries]
        init_display   = id_to_title.get(edge.source_query_id, display_opts[0] if display_opts else "") if edge else (display_opts[0] if display_opts else "")
        src_var = tk.StringVar(value=init_display)

        styled_label(row, "From query", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).grid(row=0, column=0, sticky="w", padx=(0, 6))
        src_menu = tk.OptionMenu(row, src_var, *display_opts if display_opts else [""])
        src_menu.config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                        activebackground=PALETTE["surface2"],
                        activeforeground=PALETTE["accent_text"],
                        relief="flat", bd=0, font=FONT_SMALL,
                        highlightthickness=1,
                        highlightbackground=PALETTE["border"])
        src_menu["menu"].config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                 activebackground=PALETTE["accent"],
                                 activeforeground="#0f1117")
        src_menu.grid(row=0, column=1, sticky="w", padx=(0, 12))

        styled_label(row, "Key", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).grid(row=0, column=2, sticky="w", padx=(0, 6))
        key_var = tk.StringVar(value=edge.extracted_key if edge else "")

        # Key combobox — populated with detected columns from the source query's SQL
        def _get_src_cols(src_title: str) -> list[str]:
            src_id = title_to_id.get(src_title, src_title)
            src_q  = next((q for q in other_queries if q.id == src_id), None)
            return self._query_output_columns(src_q) if src_q else []

        init_key_cols = _get_src_cols(init_display)
        key_cb = ttk.Combobox(row, textvariable=key_var, values=init_key_cols,
                              width=14, font=FONT_MONO)
        key_cb.grid(row=0, column=3, padx=(0, 12), ipady=3)

        # When source query changes, refresh key combobox values
        def _on_src_change(*_):
            key_cb['values'] = _get_src_cols(src_var.get())
        src_var.trace_add("write", _on_src_change)

        styled_label(row, "→ @param", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).grid(row=0, column=4, sticky="w", padx=(0, 6))
        param_var = tk.StringVar(value=edge.target_param if edge else "")
        param_e   = styled_entry(row, width=16)
        param_e.config(textvariable=param_var)
        param_e.grid(row=0, column=5, padx=(0, 8), ipady=3)

        gate_var = tk.BooleanVar(value=edge.gate if edge else False)
        gate_cb  = tk.Checkbutton(
            row, text="Gate", variable=gate_var,
            bg=PALETTE["surface2"], fg=PALETTE["text_dim"],
            selectcolor=PALETTE["surface"], activebackground=PALETTE["surface2"],
            activeforeground=PALETTE["text"], font=FONT_SMALL,
            relief="flat", bd=0,
        )
        gate_cb.grid(row=0, column=6, padx=(0, 4))

        data = {
            "frame": row, "src_var": src_var, "key_var": key_var,
            "key_cb": key_cb, "param_var": param_var, "gate_var": gate_var,
            "title_to_id": title_to_id,
        }

        def _remove(f=row, d=data):
            f.destroy()
            if d in self._takes_rows:
                self._takes_rows.remove(d)

        styled_button(row, "×", _remove, accent=False, width=3).grid(row=0, column=7)
        self._takes_rows.append(data)

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self):
        title = self._title_var.get().strip()
        if not title:
            messagebox.showwarning("Missing Title", "Query must have a title.", parent=self)
            return

        # Validate at least one SQL block has content
        has_sql = any(
            w["sql_text"].get("1.0", "end").strip()
            for w in self._block_widgets
        )
        if not has_sql:
            messagebox.showwarning("No SQL", "At least one SQL block must have content.", parent=self)
            return

        q = self._query
        q.title       = title
        q.description = self._desc_text.get("1.0", "end").strip()

        q.sql_blocks = [
            SqlBlock(
                label=w["label_var"].get().strip() or f"Block {i+1}",
                sql=w["sql_text"].get("1.0", "end").strip(),
            )
            for i, w in enumerate(self._block_widgets)
            if w["sql_text"].get("1.0", "end").strip()
        ]

        q.parameters = [
            ParameterSpec(
                name=name,
                label=label_var.get().strip(),
                default=default_var.get().strip(),
            )
            for name, (label_var, default_var) in getattr(self, '_param_widgets', {}).items()
        ]

        q.gives = [v.get().strip() for v in self._gives_vars if v.get().strip()]

        q.takes = [
            DependencyEdge(
                source_query_id=row["title_to_id"].get(row["src_var"].get().strip(), row["src_var"].get().strip()),
                extracted_key=row["key_var"].get().strip(),
                target_param=row["param_var"].get().strip(),
                gate=row.get("gate_var", tk.BooleanVar()).get(),
            )
            for row in self._takes_rows
            if row["src_var"].get().strip() and row["key_var"].get().strip()
        ]

        q.creates_dataframe = self._df_var.get()
        q.dataframe_key     = self._df_key_var.get().strip() if q.creates_dataframe else ""

        # Re-detect temp tables and DataFrame key refs from final SQL
        refresh_temp_table_detection(q)
        refresh_dataframe_detection(q, self._all_queries)

        self._on_save(q)
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN BUILDER SCENARIO
# ═══════════════════════════════════════════════════════════════════════════════

class ScenarioQueryBuilder(tk.Frame):

    TITLE = "Query Builder"
    ICON  = "⚙"

    # No ENVIRONMENTS — this scenario is special-cased as always-visible in the
    # sidebar and is never filtered by environment or connection state.

    def __init__(self, parent, log: LogPanel, db=None, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._log  = log
        self._db   = db
        self._spec = self._empty_spec()
        self._build()
        self._load_drafts()

    # ── Default spec ──────────────────────────────────────────────────────────

    @staticmethod
    def _empty_spec() -> ScenarioSpec:
        return ScenarioSpec(
            title="",
            icon="◈",
            environments=[],
            business_units=[],
            queries=[],
            file_prefix="",
        )

    # ── UI construction ───────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=10, padx=14)
        hdr.pack(fill="x")
        styled_label(hdr, f"{self.ICON}  {self.TITLE}",
                     font=FONT_TITLE, color=PALETTE["accent_text"]).pack(side="left")

        # Draft picker row
        draft_bar = tk.Frame(self, bg=PALETTE["surface"], padx=14, pady=8)
        draft_bar.pack(fill="x")
        styled_label(draft_bar, "Draft", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))
        self._draft_var = tk.StringVar()
        self._draft_menu = tk.OptionMenu(draft_bar, self._draft_var, "")
        self._draft_menu.config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                 activebackground=PALETTE["surface2"],
                                 activeforeground=PALETTE["accent_text"],
                                 relief="flat", bd=0, font=FONT_SMALL,
                                 highlightthickness=1,
                                 highlightbackground=PALETTE["border"],
                                 width=22)
        self._draft_menu["menu"].config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                         activebackground=PALETTE["accent"],
                                         activeforeground="#0f1117")
        self._draft_menu.pack(side="left", padx=(0, 8))
        styled_button(draft_bar, "Load", self._load_selected_draft,
                      accent=False, width=8).pack(side="left", padx=(0, 4))
        styled_button(draft_bar, "New", self._new_spec,
                      accent=False, width=8).pack(side="left", padx=(0, 4))
        styled_button(draft_bar, "Delete Draft", self._delete_draft,
                      accent=False, width=12).pack(side="left")

        separator(self).pack(fill="x", padx=10, pady=6)

        # Scenario metadata
        meta = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        meta.pack(fill="x")
        styled_label(meta, "Scenario Metadata",
                     font=FONT_HEAD, color=PALETTE["info"]).pack(anchor="w", pady=(0, 8))

        row1 = tk.Frame(meta, bg=PALETTE["surface"])
        row1.pack(fill="x", pady=(0, 6))
        styled_label(row1, "Title", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 6))
        self._title_var      = tk.StringVar()
        self._prefix_edited  = False   # True once user manually changes the prefix
        e_title = styled_entry(row1, width=30)
        e_title.config(textvariable=self._title_var)
        e_title.pack(side="left", ipady=4, padx=(0, 16))

        styled_label(row1, "Icon", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 6))
        self._icon_var = tk.StringVar(value="")
        style = ttk.Style()
        style.configure("Icon.TCombobox",
                         fieldbackground=PALETTE["entry_bg"],
                         background=PALETTE["entry_bg"],
                         foreground=PALETTE["text"],
                         selectbackground=PALETTE["accent"],
                         selectforeground="#0f1117")
        icon_cb = ttk.Combobox(row1, textvariable=self._icon_var,
                               values=_load_icons(),
                               width=4, font=("Segoe UI", 13),
                               style="Icon.TCombobox")
        icon_cb.pack(side="left", padx=(0, 16), ipady=2)

        styled_label(row1, "File prefix", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 6))
        self._prefix_var = tk.StringVar()
        e_prefix = styled_entry(row1, width=20)
        e_prefix.config(textvariable=self._prefix_var)
        e_prefix.pack(side="left", ipady=4)

        # Auto-populate prefix from title unless user has manually edited it
        def _on_title_change(*_):
            if not self._prefix_edited:
                slug = re.sub(r'[^a-z0-9]+', '_',
                              self._title_var.get().strip().lower()).strip('_')
                self._prefix_var.set(slug)

        def _on_prefix_edited(*_):
            # Mark as manually edited only when the user types (not programmatic sets)
            self._prefix_edited = True

        self._title_var.trace_add("write", _on_title_change)
        e_prefix.bind("<Key>", lambda _: setattr(self, '_prefix_edited', True))

        row2 = tk.Frame(meta, bg=PALETTE["surface"])
        row2.pack(fill="x", pady=(0, 4))
        styled_label(row2, "Environments", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))
        self._env_vars = {}
        for env in ["PROD", "QA", "IWS"]:
            v = tk.BooleanVar()
            self._env_vars[env] = v
            tk.Checkbutton(
                row2, text=env, variable=v,
                bg=PALETTE["surface"], fg=PALETTE["text"],
                selectcolor=PALETTE["entry_bg"],
                activebackground=PALETTE["surface"],
                activeforeground=PALETTE["accent_text"],
                font=FONT_SMALL,
            ).pack(side="left", padx=(0, 12))

        row3 = tk.Frame(meta, bg=PALETTE["surface"])
        row3.pack(fill="x", pady=(0, 4))
        styled_label(row3, "Business Units", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))
        self._bu_vars = {}
        for bu in _BUSINESS_UNITS:
            v = tk.BooleanVar()
            self._bu_vars[bu] = v
            tk.Checkbutton(
                row3, text=bu, variable=v,
                bg=PALETTE["surface"], fg=PALETTE["text"],
                selectcolor=PALETTE["entry_bg"],
                activebackground=PALETTE["surface"],
                activeforeground=PALETTE["accent_text"],
                font=FONT_SMALL,
            ).pack(side="left", padx=(0, 12))

        separator(self).pack(fill="x", padx=10, pady=6)

        # Query list
        ql_hdr = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        ql_hdr.pack(fill="x")
        styled_label(ql_hdr, "Queries", font=FONT_HEAD,
                     color=PALETTE["info"]).pack(side="left")
        styled_button(ql_hdr, "+ Add Query", self._add_query,
                      accent=False, width=14).pack(side="right")

        self._queries_frame = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        self._queries_frame.pack(fill="x", pady=(6, 0))

        separator(self).pack(fill="x", padx=10, pady=8)

        # Action bar
        actions = tk.Frame(self, bg=PALETTE["surface"], padx=14, pady=4)
        actions.pack(fill="x")
        styled_button(actions, "💾  Save Draft",
                      self._save_draft, accent=False, width=16).pack(side="left", padx=(0, 8))

        if qb_server.is_available():
            styled_button(actions, "◉  Graph Editor",
                          self._open_graph, accent=False, width=16).pack(side="left", padx=(0, 8))
        else:
            flask_lbl = styled_label(actions, "◉ Graph Editor requires flask (pip install flask)",
                                     font=FONT_SMALL, color=PALETTE["text_dim"])
            flask_lbl.pack(side="left", padx=(0, 8))

        styled_button(actions, "▶  Generate Files",
                      self._generate, width=18).pack(side="right")

        # Status label
        self._status_lbl = tk.Label(
            self, text="", bg=PALETTE["surface"],
            fg=PALETTE["text_dim"], font=FONT_SMALL, anchor="w",
        )
        self._status_lbl.pack(anchor="w", padx=14, pady=(6, 0))

    # ── Draft management ──────────────────────────────────────────────────────

    def _specs_dir(self) -> str:
        os.makedirs(_SPECS_DIR, exist_ok=True)
        return _SPECS_DIR

    def _load_drafts(self):
        drafts = self._list_drafts()
        menu   = self._draft_menu["menu"]
        menu.delete(0, "end")
        if drafts:
            for name in drafts:
                menu.add_command(label=name,
                                 command=lambda n=name: self._draft_var.set(n))
            self._draft_var.set(drafts[0])
        else:
            menu.add_command(label="(no drafts)", command=lambda: None)
            self._draft_var.set("")

    def _list_drafts(self) -> list[str]:
        d = self._specs_dir()
        return sorted(
            f[:-5] for f in os.listdir(d)
            if f.endswith('.json')
        )

    def _load_selected_draft(self):
        name = self._draft_var.get().strip()
        if not name:
            return
        path = os.path.join(self._specs_dir(), f"{name}.json")
        if not os.path.exists(path):
            messagebox.showwarning("Not Found", f"Draft '{name}' not found.", parent=self)
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self._spec = ScenarioSpec.from_dict(json.load(f))
            self._apply_spec_to_ui()
            self._set_status(f"Loaded draft: {name}", "info")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc), parent=self)

    def _save_draft(self):
        self._sync_spec_from_ui()
        prefix = self._spec.file_prefix.strip()
        if not prefix:
            messagebox.showwarning("Missing Prefix",
                                   "Set a file prefix before saving.", parent=self)
            return
        self._write_draft(prefix)
        self._set_status(f"Draft saved: {prefix}.json", "success")

    def _write_draft(self, prefix: str) -> None:
        """Write the draft JSON silently — called by both Save Draft and Generate."""
        path = os.path.join(self._specs_dir(), f"{prefix}.json")
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._spec.to_dict(), f, indent=2)
        self._load_drafts()
        self._draft_var.set(prefix)

    def _delete_draft(self):
        name = self._draft_var.get().strip()
        if not name:
            return

        draft_path = os.path.join(self._specs_dir(), f"{name}.json")

        # Load spec so we know query IDs → file names
        spec = None
        if os.path.exists(draft_path):
            try:
                with open(draft_path, 'r', encoding='utf-8') as f:
                    spec = ScenarioSpec.from_dict(json.load(f))
            except Exception:
                pass

        root          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        queries_dir   = os.path.join(root, 'queries')
        scenarios_dir = os.path.join(root, 'scenarios')

        gen_files = []
        if spec:
            for q in spec.queries:
                p = os.path.join(queries_dir, f"query_{spec.file_prefix}_{q.id}.py")
                if os.path.exists(p):
                    gen_files.append(p)
            sp = os.path.join(scenarios_dir, f"scenario_{spec.file_prefix}.py")
            if os.path.exists(sp):
                gen_files.append(sp)

        # Build confirmation message
        lines = [f"Delete draft  '{name}'.json?"]
        if gen_files:
            lines.append("")
            lines.append(f"Also delete {len(gen_files)} generated file(s):")
            for p in gen_files:
                lines.append(f"  • {os.path.basename(p)}")
        lines.append("")
        wdpy    = os.path.join(root, 'warehouse_diagnostics.py')
        cls_name = qb_codegen.scenario_class_name(spec) if spec else None
        wd_has_entry = False
        if cls_name and os.path.exists(wdpy):
            with open(wdpy, 'r', encoding='utf-8') as f:
                wd_text = f.read()
            wd_has_entry = cls_name in wd_text
        if wd_has_entry:
            lines.append(f"Remove import + SCENARIOS entry for {cls_name} from warehouse_diagnostics.py?")
            lines.append("(only if it was auto-added by Generate Files)")

        if not messagebox.askyesno("Delete Draft", "\n".join(lines), parent=self):
            return

        # Delete draft JSON
        if os.path.exists(draft_path):
            os.remove(draft_path)

        # Delete generated files
        for p in gen_files:
            try:
                os.remove(p)
            except Exception:
                pass

        # Strip import + SCENARIOS entry from warehouse_diagnostics.py
        if wd_has_entry:
            try:
                mod_name = f"scenario_{spec.file_prefix}"
                new_lines = []
                with open(wdpy, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.rstrip('\n')
                        if (f"from scenarios.{mod_name} import {cls_name}" in stripped or
                                f"    {cls_name}," in stripped):
                            continue
                        new_lines.append(line)
                with open(wdpy, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
            except Exception as e:
                self._set_status(f"Could not update warehouse_diagnostics.py: {e}", "error")

        self._load_drafts()
        total = 1 + len(gen_files)
        self._set_status(f"Deleted {total} file(s) for '{name}'", "info")

    def _new_spec(self):
        if not messagebox.askyesno("New Scenario",
                                    "Discard current spec and start fresh?",
                                    parent=self):
            return
        self._spec = self._empty_spec()
        self._apply_spec_to_ui()

    # ── Spec ↔ UI sync ────────────────────────────────────────────────────────

    def _sync_spec_from_ui(self):
        self._spec.title          = self._title_var.get().strip()
        self._spec.icon           = self._icon_var.get().strip()
        self._spec.file_prefix    = re.sub(r'[^a-z0-9_]', '_',
                                            self._prefix_var.get().strip().lower())
        self._spec.environments   = [e for e, v in self._env_vars.items() if v.get()]
        self._spec.business_units = [b for b, v in self._bu_vars.items() if v.get()]
        # queries are kept on self._spec.queries — edited via modal

    def _apply_spec_to_ui(self):
        self._prefix_edited = bool(self._spec.file_prefix)  # existing prefix → keep it
        self._title_var.set(self._spec.title)
        self._icon_var.set(self._spec.icon)
        self._prefix_var.set(self._spec.file_prefix)
        for env, var in self._env_vars.items():
            var.set(env in self._spec.environments)
        for bu, var in self._bu_vars.items():
            var.set(bu in self._spec.business_units)
        self._rebuild_query_list()

    # ── Query list ────────────────────────────────────────────────────────────

    def _rebuild_query_list(self):
        for w in self._queries_frame.winfo_children():
            w.destroy()

        if not self._spec.queries:
            styled_label(self._queries_frame,
                         "(no queries yet — click + Add Query)",
                         font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w")
            return

        for i, q in enumerate(self._spec.queries):
            self._add_query_row(i, q)

    def _add_query_row(self, idx: int, q: QuerySpec):
        row = tk.Frame(self._queries_frame, bg=PALETTE["surface2"],
                       padx=8, pady=6, highlightthickness=1,
                       highlightbackground=PALETTE["border"])
        row.pack(fill="x", pady=(0, 4))

        styled_label(row, f"{idx + 1}.", font=FONT_MONO,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))
        styled_label(row, q.title or q.id, font=FONT_SMALL,
                     color=PALETTE["text"]).pack(side="left", expand=True, anchor="w")

        # Temp table indicators
        if q.creates_temp_tables:
            styled_label(row, "creates: " + ", ".join(q.creates_temp_tables),
                         font=FONT_SMALL, color=PALETTE["info"]).pack(side="left", padx=(8, 0))

        def _edit(query=q):
            self._open_query_editor(query)

        def _move_up(i=idx):
            if i > 0:
                self._spec.queries[i], self._spec.queries[i - 1] = \
                    self._spec.queries[i - 1], self._spec.queries[i]
                self._rebuild_query_list()

        def _move_down(i=idx):
            if i < len(self._spec.queries) - 1:
                self._spec.queries[i], self._spec.queries[i + 1] = \
                    self._spec.queries[i + 1], self._spec.queries[i]
                self._rebuild_query_list()

        def _delete(query=q):
            if messagebox.askyesno("Remove Query",
                                    f"Remove query '{query.title or query.id}'?",
                                    parent=self):
                self._spec.queries.remove(query)
                self._rebuild_query_list()

        for text, cmd in [("Edit", _edit), ("↑", _move_up), ("↓", _move_down), ("×", _delete)]:
            styled_button(row, text, cmd, accent=(text == "Edit"), width=4).pack(
                side="right", padx=(2, 0))

    def _add_query(self):
        idx = len(self._spec.queries) + 1
        q   = QuerySpec(
            id=f"query_{idx}",
            title=f"Query {idx}",
            description="",
            sql_blocks=[SqlBlock(label="Block 1", sql="")],
        )
        self._spec.queries.append(q)
        self._open_query_editor(q)

    def _open_query_editor(self, query: QuerySpec):
        def _on_save(updated_q):
            # Query already updated in-place via the modal
            self._rebuild_query_list()
            # Push updated spec to graph server if running
            self._sync_spec_from_ui()
            if qb_server._server_running:
                qb_server.update_spec(self._spec)

        QueryEditorModal(self, query, self._spec.queries, on_save=_on_save)

    # ── Graph editor ──────────────────────────────────────────────────────────

    def _open_graph(self):
        self._sync_spec_from_ui()
        try:
            port = qb_server.start(self._spec, on_save=self._on_graph_save)
            self._set_status(f"Graph editor opened on port {port}.", "info")
        except RuntimeError as exc:
            messagebox.showerror("Graph Editor", str(exc), parent=self)

    def _on_graph_save(self, updated_spec: ScenarioSpec):
        """Called by the Flask server when the browser saves the graph."""
        # Update queries' takes/gives/title/description from graph editor changes.
        # SQL blocks and parameters are preserved (form-only).
        id_to_local = {q.id: q for q in self._spec.queries}
        for updated_q in updated_spec.queries:
            local = id_to_local.get(updated_q.id)
            if local:
                local.title       = updated_q.title
                local.description = updated_q.description
                local.gives       = updated_q.gives
                local.takes       = updated_q.takes
        # Rebuild list on the main thread
        self.after(0, self._rebuild_query_list)
        self.after(0, lambda: self._set_status("Graph editor saved — form view updated.", "success"))

    # ── Generate files ────────────────────────────────────────────────────────

    def _generate(self):
        self._sync_spec_from_ui()

        # Validate
        errors = []
        if not self._spec.title:
            errors.append("Scenario title is required.")
        if not self._spec.file_prefix:
            errors.append("File prefix is required.")
        if not self._spec.environments:
            errors.append("Select at least one environment.")
        if not self._spec.queries:
            errors.append("Add at least one query.")
        for q in self._spec.queries:
            if not any(b.sql.strip() for b in q.sql_blocks):
                errors.append(f"Query '{q.title or q.id}' has no SQL.")

        if not self._spec.business_units:
            errors.append("Select at least one business unit.")

        if errors:
            messagebox.showwarning("Validation",
                                    "\n".join(f"• {e}" for e in errors), parent=self)
            return

        # Always persist the draft before writing .py files so the spec can
        # be reloaded into the builder later — even if the user never clicked Save Draft.
        try:
            self._write_draft(self._spec.file_prefix)
        except Exception as exc:
            messagebox.showerror("Draft Save Error",
                                  f"Could not save draft: {exc}\n\nGeneration aborted.",
                                  parent=self)
            return

        # Determine output directories
        base         = os.path.dirname(os.path.dirname(__file__))
        queries_dir  = os.path.join(base, 'queries')
        scenarios_dir = os.path.join(base, 'scenarios')

        # Check for overwrites
        would_write = []
        for q in self._spec.queries:
            name = f"query_{self._spec.file_prefix}_{q.id}.py"
            would_write.append(os.path.join(queries_dir, name))
        would_write.append(os.path.join(
            scenarios_dir,
            f"scenario_{self._spec.file_prefix}.py",
        ))
        existing = [p for p in would_write if os.path.exists(p)]
        if existing:
            names = "\n".join(os.path.basename(p) for p in existing)
            if not messagebox.askyesno(
                "Overwrite?",
                f"These files already exist and will be overwritten:\n\n{names}\n\nContinue?",
                parent=self,
            ):
                return

        try:
            written = qb_codegen.write_files(self._spec, queries_dir, scenarios_dir)
        except Exception as exc:
            messagebox.showerror("Generation Error", str(exc), parent=self)
            return

        # Class name for the user's import instructions
        class_name = qb_codegen.scenario_class_name(self._spec)
        mod_name   = qb_codegen.scenario_module_name(self._spec)
        paths_str  = "\n".join(f"  • {os.path.relpath(p, base)}" for p in written)

        msg = (
            f"Generated {len(written)} file(s):\n\n{paths_str}\n\n"
            f"To add this scenario to the app, add to warehouse_diagnostics.py:\n\n"
            f"  from scenarios.{mod_name} import {class_name}\n\n"
            f"  SCENARIOS = [\n"
            f"      ...existing...\n"
            f"      {class_name},\n"
            f"  ]\n\n"
            f"Then restart the app."
        )

        # Offer to auto-add
        if messagebox.askyesno(
            "Files Generated",
            msg + "\n\nAuto-add the import and SCENARIOS entry now?",
            parent=self,
        ):
            self._auto_add_to_main(mod_name, class_name)
        else:
            messagebox.showinfo("Done", msg, parent=self)

        self._set_status(f"Generated {len(written)} file(s) for '{self._spec.title}'.", "success")
        self._log.success(f"[Query Builder] Generated: {', '.join(os.path.basename(p) for p in written)}")

    def _auto_add_to_main(self, mod_name: str, class_name: str):
        """Append import and SCENARIOS entry to warehouse_diagnostics.py."""
        main_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  'warehouse_diagnostics.py')
        try:
            with open(main_path, 'r', encoding='utf-8') as f:
                src = f.read()

            # Check not already present
            if class_name in src:
                messagebox.showinfo("Already Added",
                                     f"{class_name} is already in warehouse_diagnostics.py.",
                                     parent=self)
                return

            # Insert import after last "from scenarios..." import
            import_line = f"from scenarios.{mod_name} import {class_name}\n"
            # Find the last scenario import line
            lines = src.splitlines(keepends=True)
            last_import_idx = -1
            for i, line in enumerate(lines):
                if line.startswith("from scenarios."):
                    last_import_idx = i
            if last_import_idx == -1:
                messagebox.showerror("Auto-Add Failed",
                                      "Could not find scenario import block.",
                                      parent=self)
                return
            lines.insert(last_import_idx + 1, import_line)

            # Insert class name into SCENARIOS list before the closing comment/bracket
            src2 = ''.join(lines)
            src2 = src2.replace(
                "    # Add future scenario classes here",
                f"    {class_name},\n    # Add future scenario classes here",
            )

            with open(main_path, 'w', encoding='utf-8') as f:
                f.write(src2)

            messagebox.showinfo(
                "Auto-Add Complete",
                f"Added {class_name} to warehouse_diagnostics.py.\n\nRestart the app to load the new scenario.",
                parent=self,
            )
            self._log.success(f"[Query Builder] Auto-added {class_name} to warehouse_diagnostics.py.")

        except Exception as exc:
            messagebox.showerror("Auto-Add Error", str(exc), parent=self)

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, level: str = "info"):
        colours = {
            "info":    PALETTE["text_dim"],
            "success": PALETTE["success"],
            "warning": PALETTE["warning"],
            "error":   PALETTE["error"],
        }
        self._status_lbl.config(text=msg, fg=colours.get(level, PALETTE["text_dim"]))
