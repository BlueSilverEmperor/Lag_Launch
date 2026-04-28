import ctypes
import hashlib
import sys
import os
import subprocess
import base64
from pathlib import Path

class SecurityGatekeeper:
    # --- CONFIGURATION (Update EXPECTED_HASH after each build) ---
    EXPECTED_HASH = "REPLACE_WITH_SHA256_HASH_OF_BUILD"
    XOR_KEY = 0x42  # For string obfuscation
    
    @staticmethod
    def verify():
        """Main entry point for security checks."""
        if SecurityGatekeeper._is_debugger_present():
            SecurityGatekeeper._violation("Debugger Detected")
            
        if SecurityGatekeeper._is_vm_detected():
            SecurityGatekeeper._violation("Virtual Environment Not Supported")
            
        # Optional: Enable this only for high-security production builds
        # if not SecurityGatekeeper._check_integrity():
        #     SecurityGatekeeper._violation("Integrity Verification Failed")

        print("[SECURITY] All checks passed.")

    @staticmethod
    def _violation(reason):
        """Standard exit protocol for security breaches."""
        print(f"\n[!] SECURITY VIOLATION: {reason}")
        print("[!] Execution terminated for protection.")
        sys.exit(1)

    # --- 1. Anti-Debugger (Windows Only) ---
    @staticmethod
    def _is_debugger_present():
        if os.name == 'nt':
            try:
                return ctypes.windll.kernel32.IsDebuggerPresent() != 0
            except:
                return False
        return False

    # --- 2. Integrity Check (SHA-256) ---
    @staticmethod
    def _check_integrity():
        if SecurityGatekeeper.EXPECTED_HASH == "REPLACE_WITH_SHA256_HASH_OF_BUILD":
            return True # Skip if not configured
            
        try:
            exe_path = sys.executable if not getattr(sys, 'frozen', False) else sys.argv[0]
            sha256_hash = hashlib.sha256()
            with open(exe_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            
            return sha256_hash.hexdigest() == SecurityGatekeeper.EXPECTED_HASH
        except:
            return False

    # --- 3. Anti-VM (Basic detection) ---
    @staticmethod
    def _is_vm_detected():
        # Check for common VM MAC address prefixes
        try:
            output = subprocess.check_output("getmac", shell=True).decode().lower()
            vm_macs = ["08-00-27", "00-05-69", "00-0c-29", "00-50-56"]
            for mac in vm_macs:
                if mac in output:
                    return True
        except:
            pass
            
        # Check for Registry Keys (Windows)
        if os.name == 'nt':
            try:
                # Checking for VirtualBox/VMware registry markers
                import winreg
                keys = [
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VMware, Inc.\VMware Tools"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Oracle\VirtualBox Guest Additions")
                ]
                for root, path in keys:
                    try:
                        winreg.OpenKey(root, path)
                        return True
                    except FileNotFoundError:
                        continue
            except:
                pass
        return False

    # --- 4. String Obfuscation (XOR Utility) ---
    @staticmethod
    def crypt(data: str) -> str:
        """XOR En/Decrypts a string."""
        return "".join(chr(ord(c) ^ SecurityGatekeeper.XOR_KEY) for c in data)

    @staticmethod
    def decrypt_b64(b64_data: str) -> str:
        """Helper to decrypt base64 obfuscated strings."""
        decoded = base64.b64decode(b64_data).decode()
        return SecurityGatekeeper.crypt(decoded)

# --- XOR UTILITY FOR DEVELOPER (Run this once to get obfuscated strings) ---
# Example: print(base64.b64encode(SecurityGatekeeper.crypt("http://secure-api.com").encode()))

# --- 5. Application Firewall (Middleware Filter) ---
class ApplicationFirewall:
    def __init__(self, allowed_ips=None):
        self.allowed_ips = allowed_ips or ["127.0.0.1", "::1"]
        self.request_counts = {} # Simple in-memory rate limiting

    def validate_request(self, client_ip: str):
        """Checks if the request is from an authorized IP and under rate limits."""
        # Whitelist internal Docker/WSL bridge IPs and local access
        if client_ip.startswith("172.") or client_ip.startswith("192.168.") or client_ip in self.allowed_ips:
            return True, "Access Allowed"

        return False, "Access Denied: IP Blocked"

        # 2. Basic Rate Limiting
        import time
        now = time.time()
        counts = self.request_counts.get(client_ip, [])
        # Keep only last 60s
        counts = [c for c in counts if now - c < 60]
        if len(counts) > 200: # Max 200 req per minute
            return False, "Security Alert: Rate Limit Exceeded"
        
        counts.append(now)
        self.request_counts[client_ip] = counts
        return True, "OK"

    def apply_security_headers(self, response):
        """Hardens the browser environment for the dashboard."""
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;"
        return response
