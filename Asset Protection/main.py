"""
main.py — Digital Asset Protection System (DAP)
================================================

Entry point for the DAP Web GUI.

Usage
-----
  python main.py
"""

from server import app

if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║  DAP Server  •  http://127.0.0.1:9000        ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    app.run(host="0.0.0.0", port=9000, debug=False, threaded=True)
