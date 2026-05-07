"""
warehouse_diagnostics.py — Main entry point.

To add a new scenario
─────────────────────
1. Create  queries/your_query.py        (SQL + run() → QueryResult)
2. Create  scenarios/your_scenario.py   (UI panel, calls your query)
3. Add one import and one entry to SCENARIOS below.
"""

import json
import os
import tkinter as tk
from tkinter import messagebox
import threading
import inspect

from common import (
    PALETTE, FONT_MONO, FONT_SMALL, FONT_TITLE, FONT_HEAD,
    styled_label, styled_entry, styled_button, separator,
    LogPanel, ScrollableFrame,
)
from db import db, load_plants, PYODBC_AVAILABLE


def _load_business_units() -> list[str]:
    path = os.path.join(os.path.dirname(__file__), 'business_units.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return ["Beef/Pork", "Poultry", "Case-Ready"]

BUSINESS_UNITS = _load_business_units()

# ── Register scenarios here ───────────────────────────────────────────────────
from scenarios.scenario_load_wont_close import ScenarioLoadWontClose
from scenarios.scenario_inventory_cant_release import ScenarioInventoryCantRelease
from scenarios.scenario_iws_delay import ScenarioIWSDelay
from scenarios.scenario_replenishment_check import ScenarioReplenishmentIneligible
from scenarios.scenario_duplicate_inventory import ScenarioDuplicateInventory
from scenarios.scenario_missing_carcasses import ScenarioMissingCarcasses
from scenarios.scenario_failed_transactions import ScenarioFailedTransactions
from scenarios.scenario_carcass_lookup import ScenarioCarcassLookup
from scenarios.scenario_pronto_order_builder import ScenarioProntoOrderBuilder

# Always-visible utilities — not part of the SCENARIOS list
from scenarios.scenario_query_builder import ScenarioQueryBuilder
from scenarios.scenario_settings      import ScenarioSettings
from scenarios.scenario_carcass import ScenarioBeefCarcassLookup

SCENARIOS = [
    ScenarioLoadWontClose,
    ScenarioInventoryCantRelease,
    ScenarioIWSDelay,
    ScenarioReplenishmentIneligible,
    ScenarioDuplicateInventory,
    ScenarioMissingCarcasses,
    ScenarioFailedTransactions,
    ScenarioCarcassLookup,
    ScenarioProntoOrderBuilder,
    ScenarioBeefCarcassLookup,
    # Add future scenario classes here
]

ENV_COLOURS = {
    "PROD": ("#ef4444", "#0f1117"),
    "QA":   ("#f59e0b", "#0f1117"),
    "IWS":  ("#60a5fa", "#0f1117"),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  CONNECTION PANEL
# ═══════════════════════════════════════════════════════════════════════════════
class ConnectionPanel(tk.Frame):
    def __init__(self, parent, log: LogPanel, on_status_change, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._log              = log
        self._on_status_change = on_status_change
        self._plants           = []
        self._build()
        self._load_plants()

    def _build(self):
        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=8, padx=14)
        hdr.pack(fill="x")
        styled_label(hdr, "⬡  Plant Connection",
                     font=FONT_TITLE, color=PALETTE["accent_text"]).pack(side="left")
        self._status_dot = tk.Label(
            hdr, text="●  Disconnected",
            bg=PALETTE["surface2"], fg=PALETTE["error"], font=FONT_SMALL)
        self._status_dot.pack(side="right")

        pick = tk.Frame(self, bg=PALETTE["surface"], padx=14, pady=10)
        pick.pack(fill="x")
        styled_label(pick, "Plant", color=PALETTE["text_dim"],
                     font=FONT_SMALL).pack(anchor="w")

        self._plant_var = tk.StringVar()
        self._plant_var.trace_add("write", self._on_plant_search)
        self._plant_cb = tk.Entry(pick, textvariable=self._plant_var,
                                   bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                   insertbackground=PALETTE["accent"],
                                   relief="flat", highlightthickness=1,
                                   highlightcolor=PALETTE["accent"],
                                   highlightbackground=PALETTE["border"],
                                   font=FONT_MONO)
        self._plant_cb.pack(fill="x", pady=(4, 0), ipady=4)
        self._plant_cb.bind("<FocusOut>", self._on_plant_focus_out)
        self._plant_cb.bind("<Return>",   self._on_plant_return)
        self._plant_cb.bind("<Escape>",   lambda e: self._close_dropdown())
        self._plant_cb.bind("<Down>",     self._dropdown_focus_list)
        self._dropdown_win  = None
        self._dropdown_list = None

        self._detail_frame = tk.Frame(self, bg=PALETTE["surface2"], padx=12, pady=8)
        self._detail_frame.pack(fill="x", padx=10, pady=(8, 0))
        self._lbl_server = styled_label(self._detail_frame, "", font=FONT_SMALL,
                                         color=PALETTE["text_dim"])
        self._lbl_server.pack(anchor="w")
        self._lbl_db = styled_label(self._detail_frame, "", font=FONT_SMALL,
                                     color=PALETTE["text_dim"])
        self._lbl_db.pack(anchor="w")
        self._lbl_env = tk.Label(self._detail_frame, text="",
                                  bg=PALETTE["surface2"],
                                  font=("Segoe UI Semibold", 8), padx=6, pady=2)
        self._lbl_env.pack(anchor="w", pady=(4, 0))
        self._lbl_notes = styled_label(self._detail_frame, "", font=FONT_SMALL,
                                        color=PALETTE["text_dim"],
                                        wraplength=220, justify="left")
        self._lbl_notes.pack(anchor="w", pady=(4, 0))
        self._detail_frame.pack_forget()

        btn_row = tk.Frame(self, bg=PALETTE["surface"], padx=14, pady=10)
        btn_row.pack(fill="x")
        self._connect_btn = styled_button(btn_row, "Connect", self._connect, width=12)
        self._connect_btn.pack(side="left", padx=(0, 8))
        self._disconnect_btn = styled_button(btn_row, "Disconnect", self._disconnect,
                                              accent=False, width=12)
        self._disconnect_btn.pack(side="left")
        self._disconnect_btn.config(state="disabled")

        reload_row = tk.Frame(self, bg=PALETTE["surface"], padx=14)
        reload_row.pack(fill="x")
        tk.Button(reload_row, text="↺  Reload plants.json",
                  bg=PALETTE["surface"], fg=PALETTE["text_dim"],
                  activebackground=PALETTE["surface"],
                  activeforeground=PALETTE["accent_text"],
                  relief="flat", bd=0, cursor="hand2", font=FONT_SMALL,
                  command=self._load_plants).pack(anchor="w")

    def _load_plants(self):
        plants, err = load_plants()
        if err:
            self._log.error(f"plants.json: {err}")
            messagebox.showerror("Configuration Error", err)
            self._plants = []
            self._plant_var.set("")
            return
        self._plants = sorted(plants, key=lambda p: p.code)
        self._plant_var.set("")
        self._detail_frame.pack_forget()
        self._log.info(f"Loaded {len(plants)} plant(s) from plants.json.")

    def _on_plant_selected(self, _=None):
        plant = self._selected_plant()
        if not plant:
            self._detail_frame.pack_forget()
            return
        self._lbl_server.config(text=f"Server:    {plant.server}")
        self._lbl_db.config(    text=f"Database:  {plant.database}")
        env = plant.environment.upper()
        env_bg, env_fg = ENV_COLOURS.get(env, (PALETTE["border"], PALETTE["text"]))
        label = "  ⚠  PRODUCTION  " if env == "PROD" else f"  {env}  "
        self._lbl_env.config(text=label, bg=env_bg, fg=env_fg)
        if plant.notes:
            self._lbl_notes.config(text=f"ℹ  {plant.notes}")
            self._lbl_notes.pack(anchor="w", pady=(4, 0))
        else:
            self._lbl_notes.pack_forget()
        self._detail_frame.pack(fill="x", padx=10, pady=(8, 0))

    def _on_plant_search(self, *_):
        """Filter and show floating dropdown as user types."""
        typed = self._plant_var.get().strip().lower()
        filtered = [
            p for p in self._plants
            if not typed or typed in p.code.lower() or typed in p.name.lower()
        ]
        if filtered:
            self._show_dropdown(filtered)
        else:
            self._close_dropdown()
        self._detail_frame.pack_forget()

    def _show_dropdown(self, plants):
        """Create or update the floating listbox below the entry."""
        if self._dropdown_win is None:
            self._dropdown_win = tk.Toplevel(self)
            self._dropdown_win.wm_overrideredirect(True)
            self._dropdown_win.wm_attributes("-topmost", True)
            frame = tk.Frame(self._dropdown_win,
                             bg=PALETTE["border"], bd=1, relief="flat")
            frame.pack(fill="both", expand=True)
            sb = tk.Scrollbar(frame, orient="vertical")
            self._dropdown_list = tk.Listbox(
                frame, bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                selectbackground=PALETTE["accent"], selectforeground="#0f1117",
                font=FONT_MONO, relief="flat", bd=0, highlightthickness=0,
                activestyle="none", yscrollcommand=sb.set)
            sb.config(command=self._dropdown_list.yview)
            sb.pack(side="right", fill="y")
            self._dropdown_list.pack(side="left", fill="both", expand=True)
            self._dropdown_list.bind("<ButtonRelease-1>", self._on_dropdown_pick)
            self._dropdown_list.bind("<Return>",          self._on_dropdown_pick)
            self._dropdown_list.bind("<FocusOut>",
                lambda e: self.after(100, self._maybe_close_dropdown))

        # Populate
        self._dropdown_list.delete(0, "end")
        self._dropdown_plants = plants
        for p in plants:
            self._dropdown_list.insert("end", f"  [{p.code}]  {p.name}")

        # Position below the entry widget
        self._plant_cb.update_idletasks()
        x = self._plant_cb.winfo_rootx()
        y = self._plant_cb.winfo_rooty() + self._plant_cb.winfo_height()
        w = self._plant_cb.winfo_width()
        h = min(len(plants), 8) * 20 + 6
        self._dropdown_win.geometry(f"{w}x{h}+{x}+{y}")
        self._dropdown_win.deiconify()

    def _close_dropdown(self):
        if self._dropdown_win:
            self._dropdown_win.withdraw()

    def _maybe_close_dropdown(self):
        try:
            focused = self.focus_get()
        except KeyError:
            return  # ttk Combobox popdown isn't in the widget tree — ignore
        if focused not in (self._plant_cb, self._dropdown_list):
            self._close_dropdown()

    def _on_plant_focus_out(self, _=None):
        self.after(150, self._maybe_close_dropdown)

    def _on_dropdown_pick(self, _=None):
        idx = self._dropdown_list.curselection()
        if not idx:
            return
        plant = self._dropdown_plants[idx[0]]
        self._plant_var.set(f"[{plant.code}]  {plant.name}")
        self._close_dropdown()
        self._on_plant_selected()

    def _dropdown_focus_list(self, _=None):
        if self._dropdown_list and self._dropdown_win.winfo_ismapped():
            self._dropdown_list.focus_set()
            self._dropdown_list.selection_set(0)

    def _on_plant_return(self, _=None):
        if self._dropdown_list and self._dropdown_win.winfo_ismapped():
            self._on_dropdown_pick()

    def _selected_plant(self):
        """Return plant matching current entry text exactly."""
        current = self._plant_var.get().strip()
        for p in self._plants:
            if current == f"[{p.code}]  {p.name}":
                return p
        return None

    def _connect(self):
        plant = self._selected_plant()
        if not plant:
            messagebox.showwarning("No Plant Selected", "Please select a plant first.")
            return
        if plant.environment.upper() == "PROD":
            if not messagebox.askyesno(
                "Production Database",
                f"You are connecting to a PRODUCTION database:\n\n"
                f"  {plant.name}  ({plant.server})\n\nContinue?",
                icon="warning",
            ):
                return
        self._connect_btn.config(state="disabled", text="Connecting…")
        self.update_idletasks()
        def do():
            ok, msg = db.connect(plant)
            self.after(0, lambda: self._post_connect(ok, msg, plant))
        threading.Thread(target=do, daemon=True).start()

    def _post_connect(self, ok, msg, plant):
        if ok:
            self._status_dot.config(text=f"●  {plant.code}", fg=PALETTE["success"])
            self._connect_btn.config(state="disabled", text="Connect")
            self._disconnect_btn.config(state="normal")
            self._plant_cb.config(state="disabled", disabledbackground=PALETTE["surface2"], disabledforeground=PALETTE["text_dim"])
            self._log.success(
                f"Connected → [{plant.code}] {plant.name}  "
                f"({plant.server} / {plant.database})")
        else:
            self._status_dot.config(text="●  Error", fg=PALETTE["error"])
            self._connect_btn.config(state="normal", text="Connect")
            self._log.error(f"Connection failed: {msg}")
            messagebox.showerror("Connection Error", msg)
        self._on_status_change(ok)

    def _disconnect(self):
        plant = db.active_plant
        db.disconnect()
        self._status_dot.config(text="●  Disconnected", fg=PALETTE["error"])
        self._connect_btn.config(state="normal")
        self._disconnect_btn.config(state="disabled")
        self._plant_cb.config(state="normal")
        self._plant_cb.delete(0, "end")
        if plant:
            self._log.warning(f"Disconnected from [{plant.code}] {plant.name}.")
        self._on_status_change(False)


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOM TAB BAR
# ═══════════════════════════════════════════════════════════════════════════════
class TabBar(tk.Frame):
    """
    Horizontal strip of browser-style tabs with × close buttons.
    Tabs are created/destroyed dynamically via open_tab() / close_tab().
    """

    def __init__(self, parent, on_select, on_close, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._on_select  = on_select   # callback(key)
        self._on_close   = on_close    # callback(key)
        self._tabs       = {}          # key → {"frame", "label", "active"}
        self._active_key = None

    def open_tab(self, key, title: str, icon: str):
        if key in self._tabs:
            self._set_active(key)
            return
        tab = tk.Frame(self, bg=PALETTE["surface2"],
                       padx=2, pady=0, cursor="hand2")
        tab.pack(side="left", padx=(0, 2), pady=0)

        inner = tk.Frame(tab, bg=PALETTE["surface2"])
        inner.pack(fill="both", expand=True, padx=6, pady=5)

        lbl = tk.Label(inner, text=f"{icon}  {title}",
                       bg=PALETTE["surface2"], fg=PALETTE["text_dim"],
                       font=FONT_SMALL, cursor="hand2")
        lbl.pack(side="left", padx=(0, 6))

        close = tk.Label(inner, text="×",
                         bg=PALETTE["surface2"], fg=PALETTE["text_dim"],
                         font=("Segoe UI", 11), cursor="hand2")
        close.pack(side="left")

        # Bind clicks
        for widget in (tab, inner, lbl):
            widget.bind("<Button-1>", lambda e, k=key: self._on_select(k))
        close.bind("<Button-1>", lambda e, k=key: self._on_close(k))

        # Hover effects on close button
        close.bind("<Enter>", lambda e: close.config(fg=PALETTE["error"]))
        close.bind("<Leave>", lambda e: close.config(
            fg=PALETTE["accent_text"] if self._active_key == key
            else PALETTE["text_dim"]))

        self._tabs[key] = {"frame": tab, "inner": inner,
                           "label": lbl, "close": close}
        self._set_active(key)

    def close_tab(self, key):
        if key not in self._tabs:
            return
        self._tabs[key]["frame"].destroy()
        del self._tabs[key]
        if self._active_key == key:
            self._active_key = None
            # Switch to last remaining tab if any
            if self._tabs:
                last = list(self._tabs.keys())[-1]
                self._set_active(last)
                self._on_select(last)

    def _set_active(self, key):
        # Deactivate old
        if self._active_key and self._active_key in self._tabs:
            t = self._tabs[self._active_key]
            t["frame"].config(bg=PALETTE["surface"])
            t["inner"].config(bg=PALETTE["surface"])
            t["label"].config(bg=PALETTE["surface"], fg=PALETTE["text_dim"])
            t["close"].config(bg=PALETTE["surface"], fg=PALETTE["text_dim"])
        # Activate new
        self._active_key = key
        if key and key in self._tabs:
            t = self._tabs[key]
            t["frame"].config(bg=PALETTE["surface2"])
            t["inner"].config(bg=PALETTE["surface2"])
            t["label"].config(bg=PALETTE["surface2"], fg=PALETTE["accent_text"])
            t["close"].config(bg=PALETTE["surface2"], fg=PALETTE["accent_text"])

    def set_active(self, key):
        self._set_active(key)

    @property
    def active_key(self):
        return self._active_key

    def has_tab(self, key):
        return key in self._tabs


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════
class WarehouseDiagnosticsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Warehouse Diagnostics")
        self.geometry("1060x740")
        self.minsize(860, 600)
        self.configure(bg=PALETTE["bg"])
        # key → ScrollableFrame (instantiated on first open)
        self._open_frames   = {}
        self._sidebar_btns  = {}   # ScenarioClass → button widget
        self._build_ui()

    def _build_ui(self):
        # ── Top bar ───────────────────────────────────────────────────────────
        topbar = tk.Frame(self, bg=PALETTE["surface2"], pady=10, padx=18)
        topbar.pack(fill="x", side="top")
        tk.Label(topbar, text="◈ WAREHOUSE DIAGNOSTICS",
                 bg=PALETTE["surface2"], fg=PALETTE["accent_text"],
                 font=("Consolas", 14, "bold")).pack(side="left")
        tk.Label(topbar, text="v1.0",
                 bg=PALETTE["surface2"], fg=PALETTE["text_dim"],
                 font=FONT_SMALL).pack(side="left", padx=(8, 0), pady=(3, 0))
        self._topbar_plant = tk.Label(topbar, text="",
                                       bg=PALETTE["surface2"],
                                       fg=PALETTE["text_dim"], font=FONT_SMALL)
        self._topbar_plant.pack(side="right")
        if not PYODBC_AVAILABLE:
            tk.Label(topbar,
                     text="⚠ pyodbc not installed — run: pip install pyodbc",
                     bg=PALETTE["surface2"], fg=PALETTE["error"],
                     font=FONT_SMALL).pack(side="right", padx=(0, 16))
        separator(self).pack(fill="x")

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=PALETTE["bg"])
        body.pack(fill="both", expand=True)

        left = tk.Frame(body, bg=PALETTE["surface"], width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        separator(body, horizontal=False).pack(side="left", fill="y")

        right = tk.Frame(body, bg=PALETTE["bg"])
        right.pack(side="left", fill="both", expand=True)

        # PanedWindow — resizable log at bottom
        self._paned = tk.PanedWindow(right, orient=tk.VERTICAL,
                                      bg=PALETTE["border"],
                                      sashwidth=5, sashpad=0,
                                      sashrelief="flat", opaqueresize=True)
        self._paned.pack(fill="both", expand=True)

        # ── Top pane: tab bar + content area ─────────────────────────────────
        top_pane = tk.Frame(self._paned, bg=PALETTE["bg"])
        self._paned.add(top_pane, stretch="always", minsize=200)

        # Tab bar strip
        tab_bar_row = tk.Frame(top_pane, bg=PALETTE["surface"], pady=4, padx=4)
        tab_bar_row.pack(fill="x", side="top")
        self._tab_bar = TabBar(tab_bar_row,
                                on_select=self._on_tab_select,
                                on_close=self._on_tab_close)
        self._tab_bar.pack(fill="x")
        separator(top_pane).pack(fill="x", side="top")

        # Content area — scenario frames stacked here, shown/hidden
        self._content = tk.Frame(top_pane, bg=PALETTE["bg"])
        self._content.pack(fill="both", expand=True)

        # Overlay — shown when no tab is open
        self._overlay = tk.Frame(self._content, bg=PALETTE["bg"])
        tk.Label(self._overlay, text="⬡",
                 bg=PALETTE["bg"], fg=PALETTE["border"],
                 font=("Consolas", 48)).pack(expand=True, pady=(80, 8))
        self._overlay_msg = tk.Label(self._overlay, text="",
                                      bg=PALETTE["bg"], fg=PALETTE["text_dim"],
                                      font=FONT_SMALL)
        self._overlay_msg.pack()
        self._overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

        # ── Bottom pane: log ──────────────────────────────────────────────────
        log_pane = tk.Frame(self._paned, bg=PALETTE["surface"])
        self._paned.add(log_pane, stretch="never", minsize=80)
        self._log = LogPanel(log_pane)
        self._log.pack(fill="both", expand=True)
        self.after(100, lambda: self._paned.sash_place(0, 0, 540))

        # ── Left sidebar ──────────────────────────────────────────────────────
        self._conn_panel = ConnectionPanel(left, self._log,
                                            self._on_connection_change)
        self._conn_panel.pack(fill="x")
        separator(left).pack(fill="x", pady=4)
        styled_label(left, "  SCENARIOS", font=("Consolas", 9),
                     color=PALETTE["text_dim"]).pack(anchor="w", padx=10, pady=(4, 4))

        # Business unit filter
        bu_frame = tk.Frame(left, bg=PALETTE["surface"], padx=10)
        bu_frame.pack(fill="x", pady=(0, 4))
        styled_label(bu_frame, "Business Unit", font=("Consolas", 8),
                     color=PALETTE["text_dim"]).pack(anchor="w", pady=(0, 3))
        self._bu_filter_var = tk.StringVar(value="All")
        bu_options = ["All"] + BUSINESS_UNITS
        self._bu_menu = tk.OptionMenu(bu_frame, self._bu_filter_var, *bu_options)
        bu_menu = self._bu_menu
        bu_menu.config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                       activebackground=PALETTE["surface2"],
                       activeforeground=PALETTE["accent_text"],
                       relief="flat", bd=0, font=FONT_SMALL,
                       highlightthickness=1,
                       highlightbackground=PALETTE["border"],
                       width=18)
        bu_menu["menu"].config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                activebackground=PALETTE["accent"],
                                activeforeground="#0f1117")
        bu_menu.pack(fill="x")
        self._bu_filter_var.trace_add("write", self._on_bu_filter_change)

        # Search box
        search_frame = tk.Frame(left, bg=PALETTE["surface"], padx=10)
        search_frame.pack(fill="x", pady=(0, 4))
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", self._on_search_change)
        search_entry = styled_entry(search_frame, width=20)
        search_entry.config(textvariable=self._search_var)
        search_entry.pack(fill="x", ipady=3)

        # Build search index: ScenarioClass → list of searchable terms
        self._search_index = {}
        for ScenarioClass in SCENARIOS:
            module = inspect.getmodule(ScenarioClass)
            query_titles = [
                qry.TITLE.lower()
                for qry in getattr(module, "QUERIES", [])
            ]
            self._search_index[ScenarioClass] = (
                [ScenarioClass.TITLE.lower()] + query_titles
            )

        # ── Always-visible utility buttons (packed bottom-up before scroll area) ─
        self._settings_btn = tk.Button(
            left,
            text=f"  {ScenarioSettings.ICON}  {ScenarioSettings.TITLE}",
            bg=PALETTE["surface"], fg=PALETTE["text_dim"],
            activebackground=PALETTE["surface2"],
            activeforeground=PALETTE["accent_text"],
            relief="flat", bd=0, cursor="hand2",
            font=FONT_SMALL, anchor="w",
            command=self._open_settings,
        )
        self._settings_btn.pack(fill="x", side="bottom")
        self._qb_btn = tk.Button(
            left,
            text=f"  {ScenarioQueryBuilder.ICON}  {ScenarioQueryBuilder.TITLE}",
            bg=PALETTE["surface"], fg=PALETTE["text_dim"],
            activebackground=PALETTE["surface2"],
            activeforeground=PALETTE["accent_text"],
            relief="flat", bd=0, cursor="hand2",
            font=FONT_SMALL, anchor="w",
            command=self._open_query_builder,
        )
        self._qb_btn.pack(fill="x", side="bottom")
        separator(left).pack(fill="x", pady=4, side="bottom")

        # ── Scrollable scenario list ──────────────────────────────────────────
        scroll_wrap = tk.Frame(left, bg=PALETTE["surface"])
        scroll_wrap.pack(fill="both", expand=True)

        _sb = tk.Scrollbar(scroll_wrap, orient="vertical")
        _sb.pack(side="right", fill="y")

        self._nav_canvas = tk.Canvas(
            scroll_wrap, bg=PALETTE["surface"],
            highlightthickness=0, bd=0,
            yscrollcommand=_sb.set,
        )
        self._nav_canvas.pack(side="left", fill="both", expand=True)
        _sb.config(command=self._nav_canvas.yview)

        self._scenario_list_frame = tk.Frame(self._nav_canvas, bg=PALETTE["surface"])
        self._nav_win = self._nav_canvas.create_window(
            (0, 0), window=self._scenario_list_frame, anchor="nw")

        def _on_nav_frame_configure(_e=None):
            self._nav_canvas.configure(
                scrollregion=self._nav_canvas.bbox("all"))

        def _on_nav_canvas_configure(e):
            self._nav_canvas.itemconfig(self._nav_win, width=e.width)

        self._scenario_list_frame.bind("<Configure>", _on_nav_frame_configure)
        self._nav_canvas.bind("<Configure>", _on_nav_canvas_configure)

        def _bind_nav_wheel(_e=None):
            self._nav_canvas.bind_all("<MouseWheel>",   _nav_scroll)
            self._nav_canvas.bind_all("<Button-4>",     _nav_scroll)
            self._nav_canvas.bind_all("<Button-5>",     _nav_scroll)

        def _unbind_nav_wheel(_e=None):
            self._nav_canvas.unbind_all("<MouseWheel>")
            self._nav_canvas.unbind_all("<Button-4>")
            self._nav_canvas.unbind_all("<Button-5>")

        def _nav_scroll(e):
            if e.num == 4:
                self._nav_canvas.yview_scroll(-1, "units")
            elif e.num == 5:
                self._nav_canvas.yview_scroll(1, "units")
            else:
                self._nav_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self._nav_canvas.bind("<Enter>", _bind_nav_wheel)
        self._nav_canvas.bind("<Leave>", _unbind_nav_wheel)
        self._scenario_list_frame.bind("<Enter>", _bind_nav_wheel)
        self._scenario_list_frame.bind("<Leave>", _unbind_nav_wheel)

        for ScenarioClass in SCENARIOS:
            btn = tk.Button(
                self._scenario_list_frame,
                text=f"  {ScenarioClass.ICON}  {ScenarioClass.TITLE}",
                bg=PALETTE["surface"], fg=PALETTE["text"],
                activebackground=PALETTE["surface2"],
                activeforeground=PALETTE["accent_text"],
                relief="flat", bd=0, cursor="hand2",
                font=FONT_SMALL, anchor="w",
                command=lambda sc=ScenarioClass: self._toggle_scenario(sc),
            )
            # Do NOT pack here — _refresh_sidebar_visibility controls visibility
            self._sidebar_btns[ScenarioClass] = btn

        # Boot — hide all scenario buttons until a plant is connected
        self._refresh_sidebar_visibility(None)
        self._update_overlay()
        self._log.banner("Warehouse Diagnostics — Ready")
        self._log.info("Select a plant and connect using the left panel.")
        if not PYODBC_AVAILABLE:
            self._log.warning("pyodbc is not installed.  Run:  pip install pyodbc")

    # ── Query Builder ─────────────────────────────────────────────────────────
    def _open_query_builder(self):
        """Open (or focus) the Query Builder tab. No DB connection required."""
        key = ScenarioQueryBuilder
        if self._tab_bar.has_tab(key):
            if self._tab_bar.active_key == key:
                self._close_tab(key)
            else:
                self._tab_bar.set_active(key)
                self._show_frame(key)
            return

        if key not in self._open_frames:
            wrapper  = ScrollableFrame(self._content)
            builder  = ScenarioQueryBuilder(wrapper.inner, log=self._log, db=db)
            builder.pack(fill="both", expand=True)
            self._open_frames[key] = wrapper

        self._tab_bar.open_tab(key, ScenarioQueryBuilder.TITLE, ScenarioQueryBuilder.ICON)
        self._show_frame(key)
        self._set_sidebar_active(key)
        self._update_overlay()

    def _open_settings(self):
        """Open (or focus) the Settings tab. No DB connection required."""
        key = ScenarioSettings
        if self._tab_bar.has_tab(key):
            if self._tab_bar.active_key == key:
                self._close_tab(key)
            else:
                self._tab_bar.set_active(key)
                self._show_frame(key)
            return

        if key not in self._open_frames:
            wrapper  = ScrollableFrame(self._content)
            settings = ScenarioSettings(wrapper.inner, log=self._log,
                                        on_settings_saved=self._on_settings_saved)
            settings.pack(fill="both", expand=True)
            self._open_frames[key] = wrapper

        self._tab_bar.open_tab(key, ScenarioSettings.TITLE, ScenarioSettings.ICON)
        self._show_frame(key)
        self._set_sidebar_active(key)
        self._update_overlay()

    def _on_settings_saved(self):
        """Called after settings are saved — reload plant list and BU filter."""
        self._conn_panel._load_plants()
        global BUSINESS_UNITS
        BUSINESS_UNITS = _load_business_units()
        # Rebuild the BU filter menu to reflect any new/removed BUs
        menu = self._bu_menu["menu"]
        menu.delete(0, "end")
        menu.add_command(label="All", command=lambda: self._on_bu_filter_change("All"))
        for bu in BUSINESS_UNITS:
            menu.add_command(label=bu, command=lambda b=bu: self._on_bu_filter_change(b))
        # If the selected BU was removed, reset to All
        if self._bu_filter_var.get() not in ("All",) + tuple(BUSINESS_UNITS):
            self._bu_filter_var.set("All")
            self._on_bu_filter_change("All")

    # ── Tab management ────────────────────────────────────────────────────────
    def _toggle_scenario(self, ScenarioClass):
        """Open tab if closed; close tab if already open."""
        if not db.connected:
            messagebox.showwarning("Not Connected",
                                   "Connect to a plant before opening a scenario.")
            return

        key = ScenarioClass

        if self._tab_bar.has_tab(key):
            # Already open — if it's active, close it; otherwise just switch to it
            if self._tab_bar.active_key == key:
                self._close_tab(key)
            else:
                self._tab_bar.set_active(key)
                self._show_frame(key)
        else:
            self._open_tab(key, ScenarioClass)

    def _open_tab(self, key, ScenarioClass):
        # Instantiate scenario frame only on first open
        if key not in self._open_frames:
            wrapper  = ScrollableFrame(self._content)
            scenario = ScenarioClass(wrapper.inner, log=self._log, db=db)
            scenario.pack(fill="both", expand=True)
            self._open_frames[key] = wrapper

        self._tab_bar.open_tab(key, ScenarioClass.TITLE, ScenarioClass.ICON)
        self._show_frame(key)
        self._set_sidebar_active(key)
        self._update_overlay()

    def _close_tab(self, key):
        self._tab_bar.close_tab(key)
        if key in self._open_frames:
            self._open_frames[key].destroy()
            del self._open_frames[key]
        # Show whichever tab is now active, if any
        active = self._tab_bar.active_key
        if active:
            self._show_frame(active)
        self._set_sidebar_active(self._tab_bar.active_key)
        self._update_overlay()

    def _show_frame(self, key):
        # Hide all frames, show the selected one
        for k, frame in self._open_frames.items():
            frame.pack_forget()
        if key and key in self._open_frames:
            self._open_frames[key].pack(fill="both", expand=True)

    def _set_sidebar_active(self, active_key):
        for sc, btn in self._sidebar_btns.items():
            if sc == active_key:
                btn.config(bg=PALETTE["surface2"], fg=PALETTE["accent_text"])
            else:
                btn.config(bg=PALETTE["surface"], fg=PALETTE["text"])
        if active_key == ScenarioQueryBuilder:
            self._qb_btn.config(bg=PALETTE["surface2"], fg=PALETTE["accent_text"])
        else:
            self._qb_btn.config(bg=PALETTE["surface"], fg=PALETTE["text_dim"])
        if active_key == ScenarioSettings:
            self._settings_btn.config(bg=PALETTE["surface2"], fg=PALETTE["accent_text"])
        else:
            self._settings_btn.config(bg=PALETTE["surface"], fg=PALETTE["text_dim"])

    # ── Tab bar callbacks ─────────────────────────────────────────────────────
    def _on_tab_select(self, key):
        self._tab_bar.set_active(key)
        self._show_frame(key)
        self._set_sidebar_active(key)

    def _on_tab_close(self, key):
        self._close_tab(key)

    # ── Overlay ───────────────────────────────────────────────────────────────
    def _update_overlay(self):
        active = self._tab_bar.active_key
        # These utilities need no connection — never show the overlay for them
        if active in (ScenarioQueryBuilder, ScenarioSettings):
            self._overlay.lower()
        elif not db.connected:
            self._overlay_msg.config(
                text="Connect to a plant using the left panel to get started.")
            self._overlay.lift()
        elif not active:
            self._overlay_msg.config(
                text="Select a scenario from the left panel.")
            self._overlay.lift()
        else:
            self._overlay.lower()

    # ── Connection change ─────────────────────────────────────────────────────
    def _on_connection_change(self, connected: bool):
        if connected and db.active_plant:
            p = db.active_plant
            self._topbar_plant.config(
                text=f"Connected to:  [{p.code}]  {p.name}  [{p.environment}]",
                fg=PALETTE["success"])
            self._refresh_sidebar_visibility(p.environment.upper())
        else:
            self._topbar_plant.config(text="", fg=PALETTE["text_dim"])
            # Close all open tabs and destroy their frames on disconnect
            for key in list(self._open_frames.keys()):
                self._tab_bar.close_tab(key)
                self._open_frames[key].destroy()
            self._open_frames.clear()
            self._set_sidebar_active(None)
            # Hide all scenario buttons when disconnected
            self._refresh_sidebar_visibility(None)
        self._update_overlay()

    def _refresh_sidebar_visibility(self, environment: str | None):
        """Show only scenarios matching connected environment, BU filter, and search term."""
        term       = self._search_var.get().strip().lower() if hasattr(self, "_search_var") else ""
        bu_filter  = self._bu_filter_var.get() if hasattr(self, "_bu_filter_var") else "All"

        for sc, btn in self._sidebar_btns.items():
            env_match    = environment and environment in sc.ENVIRONMENTS
            search_terms = self._search_index.get(sc, [sc.TITLE.lower()])
            search_match = not term or any(term in t for t in search_terms)
            # BU filter: "All" shows everything; otherwise must be in scenario's BUSINESS_UNITS
            sc_bus   = getattr(sc, 'BUSINESS_UNITS', [])
            bu_match = bu_filter == "All" or bu_filter in sc_bus

            if env_match and search_match and bu_match:
                btn.pack(fill="x")
            else:
                btn.pack_forget()
                if sc in self._open_frames:
                    self._tab_bar.close_tab(sc)
                    self._open_frames[sc].pack_forget()
        self._update_overlay()

    def _on_search_change(self, *_):
        env = db.active_plant.environment.upper() if db.connected and db.active_plant else None
        self._refresh_sidebar_visibility(env)

    def _on_bu_filter_change(self, *_):
        env = db.active_plant.environment.upper() if db.connected and db.active_plant else None
        self._refresh_sidebar_visibility(env)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = WarehouseDiagnosticsApp()
    app.mainloop()
