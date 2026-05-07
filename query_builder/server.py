# ─────────────────────────────────────────────────────────────────────────────
# QUERY BUILDER INTERNAL INFRASTRUCTURE — DO NOT MODIFY
# This module runs a local Flask server to power the web-based graph editor.
# Changes here will break the graph editor or cause it to lose saved data.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations
import os
import socket
import threading
import webbrowser
from typing import Callable

from query_builder.model import ScenarioSpec

# Flask is an optional dependency — the app works without it; the graph editor
# button is disabled if Flask is not installed.
try:
    from flask import Flask, jsonify, request, send_from_directory
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


# ── Shared state (module-level so the Flask routes can reach it) ──────────────

_spec: ScenarioSpec | None   = None
_on_save: Callable | None    = None
_server_port: int | None     = None
_server_running: bool        = False
_lock = threading.Lock()


# ── Port utilities ────────────────────────────────────────────────────────────

def _find_free_port(start: int = 7432, attempts: int = 10) -> int:
    """Return the first free TCP port in [start, start+attempts)."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"Could not find a free port in range {start}–{start + attempts - 1}. "
        "Close another application and try again."
    )


# ── Flask application ─────────────────────────────────────────────────────────

if FLASK_AVAILABLE:
    _app = Flask(__name__)
    _app.config['ENV']     = 'production'
    _app.config['DEBUG']   = False
    _static_dir = os.path.dirname(__file__)

    @_app.route('/')
    def _serve_ui():
        return send_from_directory(_static_dir, 'graph.html')

    @_app.route('/vis-network.min.js')
    def _serve_vis():
        return send_from_directory(_static_dir, 'vis-network.min.js')

    @_app.route('/api/graph', methods=['GET'])
    def _get_graph():
        with _lock:
            if _spec is None:
                return jsonify({}), 404
            return jsonify(_spec.to_dict())

    @_app.route('/api/graph', methods=['POST'])
    def _save_graph():
        """
        Receive an updated ScenarioSpec dict from the graph editor.
        The graph editor only modifies dependency edges (takes/gives) and
        query title/description — SQL blocks and parameters are form-only.
        """
        with _lock:
            global _spec
            data = request.get_json(force=True, silent=True)
            if not data:
                return jsonify({'error': 'Invalid JSON'}), 400
            try:
                updated = ScenarioSpec.from_dict(data)
            except Exception as exc:
                return jsonify({'error': str(exc)}), 400

            # Preserve SQL blocks and parameters from the in-memory spec —
            # the graph editor does not edit these, so we merge carefully.
            if _spec is not None:
                existing = {q.id: q for q in _spec.queries}
                for q in updated.queries:
                    if q.id in existing:
                        orig = existing[q.id]
                        q.sql_blocks            = orig.sql_blocks
                        q.parameters            = orig.parameters
                        q.creates_temp_tables   = orig.creates_temp_tables
                        q.reads_temp_tables     = orig.reads_temp_tables

            _spec = updated

        if _on_save is not None:
            # Schedule callback on the Flask thread — tkinter will schedule it
            # back onto the main thread via self.after() in the UI layer.
            _on_save(updated)

        return jsonify({'status': 'saved'})


# ── Public API ────────────────────────────────────────────────────────────────

def start(spec: ScenarioSpec, on_save: Callable[[ScenarioSpec], None]) -> int:
    """
    Start the Flask server in a daemon thread (if not already running) and
    open the graph editor in the default browser.

    Returns the port the server is listening on.
    Raises RuntimeError if Flask is not installed.
    """
    global _spec, _on_save, _server_port, _server_running

    if not FLASK_AVAILABLE:
        raise RuntimeError(
            "Flask is not installed. Run:  pip install flask"
        )

    with _lock:
        _spec    = spec
        _on_save = on_save

    if not _server_running:
        port = _find_free_port()
        _server_port    = port
        _server_running = True

        def _run():
            import logging
            # Suppress Flask's default request logging in the console —
            # it would flood the tkinter log panel with HTTP noise.
            log = logging.getLogger('werkzeug')
            log.setLevel(logging.ERROR)
            _app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

        threading.Thread(target=_run, daemon=True, name='QueryBuilderServer').start()

        # Give the server a moment to bind before opening the browser
        import time
        time.sleep(0.4)
    else:
        port = _server_port

    webbrowser.open(f'http://127.0.0.1:{port}')
    return port


def update_spec(spec: ScenarioSpec) -> None:
    """Push a new spec to the server without restarting it (e.g. after form edits)."""
    global _spec
    with _lock:
        _spec = spec


def is_available() -> bool:
    """Return True if Flask is installed and the graph editor can be launched."""
    return FLASK_AVAILABLE
