"""
scenarios/scenario_settings.py

Application settings editor — always-visible sidebar button, no DB required.
Edits plants.json (plant connections) and business_units.json in-place.
Pass on_settings_saved= callback; called after a successful save so the
main app can reload its plant list and BU filter.
"""

import json
import os
import tkinter as tk
from tkinter import messagebox

from common import (
    PALETTE, FONT_MONO, FONT_SMALL, FONT_TITLE, FONT_HEAD,
    styled_label, styled_entry, styled_button, separator,
)

_ROOT          = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PLANTS_PATH   = os.path.join(_ROOT, "plants.json")
_BU_PATH       = os.path.join(_ROOT, "business_units.json")
_ICONS_PATH    = os.path.join(_ROOT, "icons.json")
_SETTINGS_PATH = os.path.join(_ROOT, "settings.json")

_DEFAULT_SETTINGS = {
    "version_check_repo": "https://github.com/ARockwel/Warehouse-Diagnostic-Tool",
}

_ENVIRONMENTS = ["PROD", "QA", "IWS"]


def load_settings() -> dict:
    try:
        with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
            return {**_DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        return dict(_DEFAULT_SETTINGS)


# ═══════════════════════════════════════════════════════════════════════════════
#  PLANT EDITOR MODAL
# ═══════════════════════════════════════════════════════════════════════════════

class PlantEditorModal(tk.Toplevel):
    def __init__(self, parent, plant: dict | None, on_save):
        super().__init__(parent)
        self.title("Add Plant" if plant is None else "Edit Plant")
        self.configure(bg=PALETTE["surface"])
        self.resizable(False, False)
        self.geometry("480x380")
        self.transient(parent)
        self.grab_set()

        self._on_save = on_save
        self._build(plant or {})
        self.focus_force()

    def _field(self, parent, label: str, var: tk.StringVar, width=38, multiline=False):
        row = tk.Frame(parent, bg=PALETTE["surface"])
        row.pack(fill="x", pady=(0, 8))
        styled_label(row, label, font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(anchor="w")
        if multiline:
            t = tk.Text(row, height=3, width=width,
                        bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                        insertbackground=PALETTE["accent"],
                        relief="flat", highlightthickness=1,
                        highlightbackground=PALETTE["border"],
                        font=FONT_MONO, wrap="word")
            t.insert("1.0", var.get())
            t.pack(fill="x", ipady=2)
            var._text_widget = t
        else:
            e = styled_entry(row, width=width)
            e.config(textvariable=var)
            e.pack(fill="x", ipady=4)
        return row

    def _build(self, plant: dict):
        body = tk.Frame(self, bg=PALETTE["surface"], padx=18, pady=14)
        body.pack(fill="both", expand=True)

        self._name_var  = tk.StringVar(value=plant.get("name",        ""))
        self._code_var  = tk.StringVar(value=plant.get("code",        ""))
        self._srv_var   = tk.StringVar(value=plant.get("server",      ""))
        self._db_var    = tk.StringVar(value=plant.get("database",    ""))
        self._env_var   = tk.StringVar(value=plant.get("environment", "PROD"))
        self._notes_var = tk.StringVar(value=plant.get("notes",       ""))

        self._field(body, "Name",        self._name_var)
        self._field(body, "Code",        self._code_var, width=14)

        # Server + Database side by side
        sd = tk.Frame(body, bg=PALETTE["surface"])
        sd.pack(fill="x", pady=(0, 8))
        srv_col = tk.Frame(sd, bg=PALETTE["surface"])
        srv_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        styled_label(srv_col, "Server", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(anchor="w")
        e_srv = styled_entry(srv_col)
        e_srv.config(textvariable=self._srv_var)
        e_srv.pack(fill="x", ipady=4)

        db_col = tk.Frame(sd, bg=PALETTE["surface"])
        db_col.pack(side="left", fill="x", expand=True)
        styled_label(db_col, "Database", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(anchor="w")
        e_db = styled_entry(db_col)
        e_db.config(textvariable=self._db_var)
        e_db.pack(fill="x", ipady=4)

        # Environment dropdown
        env_row = tk.Frame(body, bg=PALETTE["surface"])
        env_row.pack(fill="x", pady=(0, 8))
        styled_label(env_row, "Environment", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left", padx=(0, 8))
        env_menu = tk.OptionMenu(env_row, self._env_var, *_ENVIRONMENTS)
        env_menu.config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                        activebackground=PALETTE["surface2"],
                        activeforeground=PALETTE["accent_text"],
                        relief="flat", bd=0, font=FONT_SMALL,
                        highlightthickness=1, highlightbackground=PALETTE["border"])
        env_menu["menu"].config(bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                activebackground=PALETTE["accent"],
                                activeforeground="#0f1117")
        env_menu.pack(side="left")

        # Notes
        notes_row = tk.Frame(body, bg=PALETTE["surface"])
        notes_row.pack(fill="x", pady=(0, 8))
        styled_label(notes_row, "Notes", font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(anchor="w")
        self._notes_text = tk.Text(notes_row, height=3,
                                   bg=PALETTE["entry_bg"], fg=PALETTE["text"],
                                   insertbackground=PALETTE["accent"],
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=PALETTE["border"],
                                   font=FONT_SMALL, wrap="word")
        self._notes_text.insert("1.0", plant.get("notes", ""))
        self._notes_text.pack(fill="x", ipady=2)

        # Buttons
        btn_row = tk.Frame(body, bg=PALETTE["surface"])
        btn_row.pack(fill="x", pady=(10, 0))
        styled_button(btn_row, "Save", self._save).pack(side="right", padx=(8, 0))
        styled_button(btn_row, "Cancel", self.destroy,
                      accent=False).pack(side="right")

    def _save(self):
        name = self._name_var.get().strip()
        code = self._code_var.get().strip()
        srv  = self._srv_var.get().strip()
        db   = self._db_var.get().strip()
        if not name or not code or not srv or not db:
            messagebox.showwarning("Missing Fields",
                                   "Name, Code, Server, and Database are required.",
                                   parent=self)
            return
        self._on_save({
            "name":        name,
            "code":        code,
            "server":      srv,
            "database":    db,
            "environment": self._env_var.get(),
            "notes":       self._notes_text.get("1.0", "end-1c").strip(),
        })
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS FRAME
# ═══════════════════════════════════════════════════════════════════════════════

class ScenarioSettings(tk.Frame):
    TITLE = "Settings"
    ICON  = "⚙"

    def __init__(self, parent, *, log, on_settings_saved=None, **kw):
        kw.setdefault("bg", PALETTE["surface"])
        super().__init__(parent, **kw)
        self._log              = log
        self._on_settings_saved = on_settings_saved
        self._plants:   list[dict] = []
        self._bus:      list[str]  = []
        self._icons:    list[str]  = []
        self._settings: dict       = dict(_DEFAULT_SETTINGS)
        self._build()
        self._load()

    # ── Data I/O ───────────────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(_PLANTS_PATH, 'r', encoding='utf-8') as f:
                self._plants = json.load(f).get("plants", [])
        except Exception:
            self._plants = []
        try:
            with open(_BU_PATH, 'r', encoding='utf-8') as f:
                self._bus = json.load(f)
        except Exception:
            self._bus = ["Beef/Pork", "Poultry", "Case-Ready"]
        try:
            with open(_ICONS_PATH, 'r', encoding='utf-8') as f:
                self._icons = json.load(f)
        except Exception:
            self._icons = ["◈","⚙","🔍","🔧","⚠","📦","🚚","🏭","📋","🔑","⬡","🗂","📊","🔗","⛓","🛠","🧩","📌","🔄","✅"]
        try:
            with open(_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                self._settings = {**_DEFAULT_SETTINGS, **json.load(f)}
        except Exception:
            self._settings = dict(_DEFAULT_SETTINGS)
        self._refresh_plants_list()
        self._refresh_bu_list()
        self._refresh_icons_list()
        self._refresh_settings()

    def _save(self):
        try:
            with open(_PLANTS_PATH, 'w', encoding='utf-8') as f:
                json.dump({"plants": self._plants}, f, indent=2)
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not write plants.json:\n{e}", parent=self)
            return

        try:
            with open(_BU_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._bus, f, indent=2)
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not write business_units.json:\n{e}", parent=self)
            return

        try:
            with open(_ICONS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._icons, f, indent=2, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not write icons.json:\n{e}", parent=self)
            return

        self._settings["version_check_repo"] = self._repo_var.get().strip()
        try:
            with open(_SETTINGS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, indent=2)
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not write settings.json:\n{e}", parent=self)
            return

        self._log.info("Settings saved — plants.json + business_units.json + icons.json + settings.json updated.")
        if self._on_settings_saved:
            self._on_settings_saved()
        messagebox.showinfo("Saved", "Settings saved successfully.", parent=self)

    # ── Layout ─────────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=PALETTE["surface2"], pady=10, padx=14)
        hdr.pack(fill="x")
        styled_label(hdr, f"{self.ICON}  {self.TITLE}",
                     font=FONT_TITLE, color=PALETTE["accent_text"]).pack(side="left")

        body = tk.Frame(self, bg=PALETTE["surface"], padx=16, pady=12)
        body.pack(fill="both", expand=True)

        # ── Plants section ────────────────────────────────────────────────────
        plants_hdr = tk.Frame(body, bg=PALETTE["surface"])
        plants_hdr.pack(fill="x", pady=(0, 6))
        styled_label(plants_hdr, "Plants",
                     font=FONT_HEAD, color=PALETTE["accent_text"]).pack(side="left")
        styled_button(plants_hdr, "+ Add Plant", self._add_plant,
                      width=14).pack(side="right")

        styled_label(body,
                     "Each plant entry maps a display name to a SQL Server connection.",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w", pady=(0, 6))

        self._plants_frame = tk.Frame(body, bg=PALETTE["surface"])
        self._plants_frame.pack(fill="x", pady=(0, 16))

        separator(body).pack(fill="x", pady=(0, 12))

        # ── Business Units section ────────────────────────────────────────────
        bu_hdr = tk.Frame(body, bg=PALETTE["surface"])
        bu_hdr.pack(fill="x", pady=(0, 6))
        styled_label(bu_hdr, "Business Units",
                     font=FONT_HEAD, color=PALETTE["accent_text"]).pack(side="left")
        styled_button(bu_hdr, "+ Add", self._add_bu,
                      width=10).pack(side="right")

        styled_label(body,
                     "Business units used to filter scenarios in the sidebar.",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w", pady=(0, 6))

        self._bu_frame = tk.Frame(body, bg=PALETTE["surface"])
        self._bu_frame.pack(fill="x", pady=(0, 16))

        separator(body).pack(fill="x", pady=(0, 12))

        # ── Icons section ─────────────────────────────────────────────────────
        icons_hdr = tk.Frame(body, bg=PALETTE["surface"])
        icons_hdr.pack(fill="x", pady=(0, 6))
        styled_label(icons_hdr, "Query Builder Icons",
                     font=FONT_HEAD, color=PALETTE["accent_text"]).pack(side="left")
        styled_button(icons_hdr, "+ Add", self._add_icon,
                      width=10).pack(side="right")

        styled_label(body,
                     "Icons available in the Query Builder scenario icon dropdown.",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w", pady=(0, 6))

        self._icons_frame = tk.Frame(body, bg=PALETTE["surface"])
        self._icons_frame.pack(fill="x", pady=(0, 16))

        separator(body).pack(fill="x", pady=(0, 12))

        # ── Version Check Repo section ────────────────────────────────────
        repo_hdr = tk.Frame(body, bg=PALETTE["surface"])
        repo_hdr.pack(fill="x", pady=(0, 6))
        styled_label(repo_hdr, "Version Check",
                     font=FONT_HEAD, color=PALETTE["accent_text"]).pack(side="left")

        styled_label(body,
                     "Full URL of the GitHub repo to check for updates. "
                     "Set this to your team's fork.",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w", pady=(0, 6))

        repo_row = tk.Frame(body, bg=PALETTE["surface"])
        repo_row.pack(fill="x", pady=(0, 16))
        self._repo_var = tk.StringVar()
        repo_entry = styled_entry(repo_row, width=40)
        repo_entry.config(textvariable=self._repo_var)
        repo_entry.pack(fill="x", ipady=4)

        separator(body).pack(fill="x", pady=(0, 12))

        # ── Save ──────────────────────────────────────────────────────────────
        save_row = tk.Frame(body, bg=PALETTE["surface"])
        save_row.pack(fill="x")
        styled_button(save_row, "💾  Save Changes", self._save, width=20).pack(side="right")

    # ── Plants list ────────────────────────────────────────────────────────────

    def _refresh_plants_list(self):
        for w in self._plants_frame.winfo_children():
            w.destroy()
        for i, plant in enumerate(self._plants):
            self._plant_row(i, plant)

    def _plant_row(self, idx: int, plant: dict):
        env     = plant.get("environment", "PROD").upper()
        env_colours = {"PROD": "#ef4444", "QA": "#f59e0b", "IWS": "#60a5fa"}
        env_col = env_colours.get(env, PALETTE["text_dim"])

        row = tk.Frame(self._plants_frame, bg=PALETTE["surface2"],
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        row.pack(fill="x", pady=(0, 4))

        inner = tk.Frame(row, bg=PALETTE["surface2"], padx=10, pady=7)
        inner.pack(fill="x")

        # Env badge
        tk.Label(inner, text=env, bg=env_col, fg="#0f1117",
                 font=("Segoe UI Semibold", 8), padx=5, pady=1,
                 relief="flat").pack(side="left", padx=(0, 10))

        # Code + Name
        styled_label(inner, plant.get("code", ""), font=FONT_MONO,
                     color=PALETTE["accent_text"]).pack(side="left", padx=(0, 6))
        styled_label(inner, plant.get("name", ""), font=FONT_SMALL,
                     color=PALETTE["text"]).pack(side="left", padx=(0, 10))
        styled_label(inner, plant.get("server", ""), font=FONT_SMALL,
                     color=PALETTE["text_dim"]).pack(side="left")

        # Buttons
        btn_frame = tk.Frame(inner, bg=PALETTE["surface2"])
        btn_frame.pack(side="right")
        styled_button(btn_frame, "Edit",
                      lambda i=idx: self._edit_plant(i), width=6).pack(side="left", padx=(0, 4))
        styled_button(btn_frame, "×",
                      lambda i=idx: self._remove_plant(i),
                      accent=False, width=3).pack(side="left")

    def _add_plant(self):
        PlantEditorModal(self, None, self._on_plant_added)

    def _on_plant_added(self, plant: dict):
        self._plants.append(plant)
        self._refresh_plants_list()

    def _edit_plant(self, idx: int):
        PlantEditorModal(self, self._plants[idx],
                         lambda p, i=idx: self._on_plant_edited(i, p))

    def _on_plant_edited(self, idx: int, plant: dict):
        self._plants[idx] = plant
        self._refresh_plants_list()

    def _remove_plant(self, idx: int):
        name = self._plants[idx].get("name", "this plant")
        if not messagebox.askyesno("Remove Plant",
                                   f"Remove '{name}'?", parent=self):
            return
        del self._plants[idx]
        self._refresh_plants_list()

    # ── Business Units list ────────────────────────────────────────────────────

    def _refresh_bu_list(self):
        for w in self._bu_frame.winfo_children():
            w.destroy()
        for i, bu in enumerate(self._bus):
            self._bu_row(i, bu)

    def _bu_row(self, idx: int, name: str):
        row = tk.Frame(self._bu_frame, bg=PALETTE["surface2"],
                       highlightthickness=1, highlightbackground=PALETTE["border"])
        row.pack(fill="x", pady=(0, 4))

        inner = tk.Frame(row, bg=PALETTE["surface2"], padx=10, pady=6)
        inner.pack(fill="x")

        self._bu_vars = getattr(self, '_bu_vars', {})
        var = tk.StringVar(value=name)
        self._bu_vars[idx] = var

        e = styled_entry(inner, width=28)
        e.config(textvariable=var)
        e.pack(side="left", ipady=3, padx=(0, 8))
        e.bind("<FocusOut>", lambda _, i=idx, v=var: self._commit_bu(i, v))
        e.bind("<Return>",   lambda _, i=idx, v=var: self._commit_bu(i, v))

        styled_button(inner, "×",
                      lambda i=idx: self._remove_bu(i),
                      accent=False, width=3).pack(side="left")

    def _commit_bu(self, idx: int, var: tk.StringVar):
        val = var.get().strip()
        if val and idx < len(self._bus):
            self._bus[idx] = val

    def _add_bu(self):
        self._bus.append("New Business Unit")
        self._refresh_bu_list()
        # Focus the new entry
        children = self._bu_frame.winfo_children()
        if children:
            last = children[-1]
            for w in last.winfo_children():
                for ww in w.winfo_children():
                    if isinstance(ww, tk.Entry):
                        ww.focus_set()
                        ww.select_range(0, "end")
                        return

    def _remove_bu(self, idx: int):
        del self._bus[idx]
        self._refresh_bu_list()

    # ── Icons list ─────────────────────────────────────────────────────────────

    def _refresh_icons_list(self):
        for w in self._icons_frame.winfo_children():
            w.destroy()
        # Render in a wrapping grid — 8 icons per row
        row_frame = None
        for i, icon in enumerate(self._icons):
            if i % 8 == 0:
                row_frame = tk.Frame(self._icons_frame, bg=PALETTE["surface"])
                row_frame.pack(anchor="w", pady=(0, 4))
            cell = tk.Frame(row_frame, bg=PALETTE["surface2"],
                            highlightthickness=1, highlightbackground=PALETTE["border"])
            cell.pack(side="left", padx=(0, 4))
            inner = tk.Frame(cell, bg=PALETTE["surface2"], padx=6, pady=4)
            inner.pack()
            tk.Label(inner, text=icon, bg=PALETTE["surface2"], fg=PALETTE["text"],
                     font=("Segoe UI", 14)).pack(side="left", padx=(0, 4))
            styled_button(inner, "×", lambda i=i: self._remove_icon(i),
                          accent=False, width=2).pack(side="left")

    def _add_icon(self):
        top = tk.Toplevel(self)
        top.title("Add Icon")
        top.configure(bg=PALETTE["surface"])
        top.resizable(False, False)
        top.geometry("260x120")
        top.transient(self)
        top.grab_set()

        body = tk.Frame(top, bg=PALETTE["surface"], padx=16, pady=14)
        body.pack(fill="both", expand=True)
        styled_label(body, "Icon (emoji or Unicode character)",
                     font=FONT_SMALL, color=PALETTE["text_dim"]).pack(anchor="w")
        var = tk.StringVar()
        e = styled_entry(body, width=10)
        e.config(textvariable=var, font=("Segoe UI", 16))
        e.pack(anchor="w", ipady=4, pady=(4, 10))
        e.focus_set()

        def _confirm():
            val = var.get().strip()
            if val:
                self._icons.append(val)
                self._refresh_icons_list()
            top.destroy()

        e.bind("<Return>", lambda _: _confirm())
        styled_button(body, "Add", _confirm, width=10).pack(side="right")

    def _remove_icon(self, idx: int):
        del self._icons[idx]
        self._refresh_icons_list()

    # ── Settings (version check repo) ─────────────────────────────────────

    def _refresh_settings(self):
        self._repo_var.set(self._settings.get("version_check_repo", ""))
