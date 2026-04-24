"""
core/compliance.py
------------------
LLM-powered Rights Compliance Engine for DAP.
Uses Gemma/Qwen (via Ollama) to analyze publishing rights.
"""

import json
from typing import Dict, Any, List, Optional
from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage

SYSTEM_PROMPT = (
    "You are the Advanced Rights Compliance Engine for the Digital Asset Protection (DAP) platform.\n\n"
    "INPUT SIGNALS:\n"
    "1. Metadata Topics: {topics}\n"
    "2. Visual Analysis (Llava): {visual_topics}\n"
    "3. Uploader Reputation: {reputation}\n"
    "4. Authorized List: {authorized_list}\n\n"
    "TASK:\n"
    "Evaluate if the publisher '{source_name}' on '{platform}' is the likely rightful owner or an authorized distributor of this content.\n\n"
    "CRITERIA:\n"
    "- If the publisher is in the Authorized List, mark as AUTHORIZED.\n"
    "- High uploader reputation (Verified, millions of subscribers) strongly suggests legitimate ownership or partnership, even if not explicitly whitelisted for this specific clip.\n"
    "- Visual topic mismatch (e.g., metadata says 'Gaming' but frames show 'Live Football') is a high-risk signal for piracy/re-uploading.\n\n"
    "OUTPUT FORMAT:\n"
    "Strictly output a JSON object:\n"
    "{{\n"
    "  \"status\": \"AUTHORIZED\" | \"FLAGGED\",\n"
    "  \"reason\": \"A concise 1-2 sentence explanation of your decision.\"\n"
    "}}\n"
    "Use your reasoning to weigh the signals carefully."
)

TOPIC_EXTRACTION_PROMPT = (
    "You are an expert metadata analyst for an anti-piracy system. Your goal is to extract "
    "highly accurate (>90%), specific, and real-world search queries based on the provided video info. "
    "Focus on exact entities: team names, sports, leagues, specific events, or brand names. "
    "Do NOT include generic terms like 'video', 'clip', 'mp4', or 'highlights'. "
    "Output EXCLUSIVELY a comma-separated list of 2-3 precise search topics. "
    "Return NOTHING ELSE (no explanation, no <think> tags).\n\n"
    "Title: {title}\nDescription: {description}"
)

class RightsComplianceEngine:
    def __init__(self, model: str = "deepseek-r1:7b"):
        self.llm = ChatOllama(model=model, temperature=0.1)

    def _strip_reasoning(self, text: str) -> str:
        """DeepSeek-R1 outputs its 'thoughts' in <think> tags. We strip them."""
        import re
        return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    def extract_topics(self, title: str, description: str = "") -> List[str]:
        """Uses LLM to extract key topics from metadata."""
        try:
            prompt = TOPIC_EXTRACTION_PROMPT.format(title=title, description=description)
            response = self.llm.invoke([HumanMessage(content=prompt)])
            clean_text = self._strip_reasoning(response.content)
            # Remove any unwanted dots from lists or ending punctuation that could mess up topics.
            clean_text = clean_text.replace(".", "")
            topics = [T.strip() for T in clean_text.split(",") if T.strip()]
            return topics[:3]

        except Exception as e:
            print(f"Error extracting topics: {e}")
            return ["Video Content"]

    def check_compliance(
        self, 
        topics: List[str], 
        visual_topics: str,
        reputation: Dict[str, Any],
        source_name: str, 
        platform: str, 
        authorized_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Runs the LLM reasoning to check if a publisher is authorized.
        """
        # Format the authorized list for the prompt
        list_str = "\n".join([f"- {p['name']} on {p['platform']}" for p in authorized_list])
        if not list_str:
            list_str = "No authorized publishers currently listed."

        topics_str = ", ".join(topics)
        
        # Format Reputation Stats
        rep_str = (
            f"Verified: {reputation.get('is_verified', False)}, "
            f"Subscribers: {reputation.get('subscriber_count', 'Unknown')}, "
            f"Total Views: {reputation.get('view_count', 0)}"
        )
        
        sys_msg = SYSTEM_PROMPT.format(
            topics=topics_str,
            visual_topics=visual_topics,
            reputation=rep_str,
            authorized_list=list_str,
            source_name=source_name,
            platform=platform
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=sys_msg),
                HumanMessage(content=f"Verify rights for publisher: {source_name}")
            ])
            
            # Extract JSON from response
            text = self._strip_reasoning(response.content)
            # Look for JSON block
            if "{" in text and "}" in text:
                json_part = text[text.find("{"):text.rfind("}")+1]
                data = json.loads(json_part)
                return data
            else:
                # Fallback heuristic if LLM didn't output clean JSON
                if "AUTHORIZED" in text.upper():
                    return {"status": "AUTHORIZED", "reason": "Explicitly found in authorized list."}
                return {"status": "FLAGGED", "reason": text[:200]}
                
        except Exception as e:
             return {"status": "ERROR", "reason": f"LLM Inference failed: {str(e)}"}

if __name__ == "__main__":
    # Quick test
    engine = RightsComplianceEngine(model="deepseek-r1:7b")
    test_topics = ["Sports", "Live Event"]
    test_auth = [{"name": "Official Real Madrid", "platform": "YouTube"}]
    
    # Test Authorized
    print("Testing Authorized...")
    res = engine.check_compliance(test_topics, "Official Real Madrid", "YouTube", test_auth)
    print(res)
    
    # Test Flagged
    print("\nTesting Flagged...")
    res = engine.check_compliance(test_topics, "PirateChannel", "YouTube", test_auth)
    print(res)
