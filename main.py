"""
main.py — Digital Asset Protection System (DAP)
================================================

Entry point for the DAP Web GUI.

Usage
-----
  python main.py
"""

from core.security import SecurityGatekeeper
from server_reloaded import app

if __name__ == "__main__":
    # 1. Standard Security Verification
    SecurityGatekeeper.verify()
    
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║  DAP Server v3.5m • http://127.0.0.1:9000    ║")
    print("  ╚══════════════════════════════════════════════╝\n")
    app.run(host="127.0.0.1", port=9000, debug=False, threaded=True)
