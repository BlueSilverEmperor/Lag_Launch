"""
main.py — Digital Asset Protection System (DAP)
================================================

Entry point for the DAP Web GUI.

Usage
-----
  python main.py
"""

from server_reloaded import app, init_app

if __name__ == "__main__":
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║  DAP Server v3.5m • http://127.0.0.1:9000    ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    init_app()
    app.run(host="0.0.0.0", port=9000, debug=False, threaded=True)
