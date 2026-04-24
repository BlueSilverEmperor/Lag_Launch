"""
core/rights_gateway.py
----------------------
Unified Rights Verification Gateway.
Supports Local Whitelist, Phyllo, and WebKyte.
"""

from typing import Dict, Any, List, Optional
import abc

class RightsProvider(abc.ABC):
    @abc.abstractmethod
    def verify_rights(self, publisher: str, platform: str) -> Dict[str, Any]:
        pass

class LocalWhitelistProvider(RightsProvider):
    def __init__(self, storage):
        self.storage = storage

    def verify_rights(self, publisher: str, platform: str) -> Dict[str, Any]:
        auth_list = self.storage.list_authorized_publishers()
        is_auth = any(
            p['name'].lower() == publisher.lower() and p['platform'].lower() == platform.lower()
            for p in auth_list
        )
        if is_auth:
            return {"status": "AUTHORIZED", "source": "Local Whitelist"}
        return {"status": "UNAUTHORIZED", "source": "Local Whitelist"}

class PhylloProvider(RightsProvider):
    """
    Placeholder for Phyllo Integration.
    Phyllo is used to verify creator identity and platform data.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def verify_rights(self, publisher: str, platform: str) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "PENDING", "reason": "Phyllo API Key missing", "source": "Phyllo"}
        
        # Real integration would call: https://api.getphyllo.com/v1/profiles
        return {"status": "UNVERIFIED", "reason": "Phyllo integration pending API configuration", "source": "Phyllo"}

class WebKyteProvider(RightsProvider):
    """
    Placeholder for WebKyte Integration.
    WebKyte is used for advanced asset protection and fingerprinting.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def verify_rights(self, publisher: str, platform: str) -> Dict[str, Any]:
        if not self.api_key:
            return {"status": "PENDING", "reason": "WebKyte API Key missing", "source": "WebKyte"}
            
        # Real integration would call WebKyte's asset/rights verification endpoints
        return {"status": "UNVERIFIED", "reason": "WebKyte integration pending API configuration", "source": "WebKyte"}

class RightsGateway:
    def __init__(self, storage, config: Optional[Dict[str, Any]] = None):
        self.storage = storage
        self.config = config or {}
        
        # Initialize providers
        self.providers = {
            "local": LocalWhitelistProvider(storage),
            "phyllo": PhylloProvider(self.config.get("PHYLLO_API_KEY")),
            "webkyte": WebKyteProvider(self.config.get("WEBKYTE_API_KEY"))
        }

    def check_all(self, publisher: str, platform: str) -> List[Dict[str, Any]]:
        """Check rights across all configured providers."""
        results = []
        for name, provider in self.providers.items():
            results.append(provider.verify_rights(publisher, platform))
        return results

    def is_authorized(self, publisher: str, platform: str) -> bool:
        """Simple boolean check for authorization (prioritizes local whitelist)."""
        res = self.providers["local"].verify_rights(publisher, platform)
        return res["status"] == "AUTHORIZED"

    def get_authorized_list_for_llm(self) -> List[Dict[str, Any]]:
        """Returns the list of authorized publishers for LLM context."""
        return self.storage.list_authorized_publishers()
