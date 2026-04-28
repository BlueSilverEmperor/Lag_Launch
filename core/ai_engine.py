import os
import abc
from typing import List, Optional

class AIProvider(abc.ABC):
    @abc.abstractmethod
    def extract_topics(self, content_name: str) -> List[str]:
        """Extract search topics from a content name or metadata."""
        pass

    @abc.abstractmethod
    def analyze_compliance(self, uploader_repo: str, matched_percentage: float) -> str:
        """Analyze uploader and match data to give a rights verdict."""
        pass

    @abc.abstractmethod
    def analyze_full_report(self, report_data: dict) -> str:
        """Provide a deep narrative analysis of the entire scan report."""
        pass

class GeminiProvider(AIProvider):
    """Google Gemini AI Provider."""
    def __init__(self, api_key: str):
        self.api_key = api_key
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('gemini-1.5-flash')
        except ImportError:
            print("WARNING: google-generativeai not installed. Falling back to Mock.")
            self.model = None

    def extract_topics(self, content_name: str) -> List[str]:
        prompt = f"Extract 2-3 precise search topics (teams, leagues, or events) from this video name: {content_name}. Return ONLY a comma-separated list."
        if self.model:
            try:
                res = self.model.generate_content(prompt)
                topics = [t.strip() for t in res.text.split(",") if t.strip()]
                return topics if topics else [content_name]
            except:
                pass
        return [content_name, f"{content_name} highlights"]

    def analyze_compliance(self, uploader_repo: str, matched_percentage: float) -> str:
        return f"Gemini Verdict: Potential Infringement ({matched_percentage}%)"

    def analyze_full_report(self, report_data: dict) -> str:
        """Actual Gemini implementation using the generativeai package."""
        prompt = f"""
        Act as a Digital Rights Enforcement expert. Analyze this Asset Protection report:
        - Suspect Video: {report_data.get('suspect_video')}
        - Similarity Score: {report_data.get('similarity_percentage')}%
        - Matched Frames: {report_data.get('matched_frames')} / {report_data.get('total_frames_checked')}
        - Logo/Watermark Detections: {report_data.get('logo_confirmations', 0)}
        - Publisher: {report_data.get('publisher')}
        
        Provide a concise, 3-paragraph executive summary:
        1. Infringement Verdict: Is this a clear case of piracy? Why?
        2. Visual Evidence: What are the key frames or logos that confirm the match?
        3. Action Recommendation: Should a DMCA be sent immediately or is further human review needed?
        """
        
        if self.model:
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except Exception as e:
                return f"Gemini Error: {str(e)}"
        
        # Fallback if model not initialized
        return f"**Gemini Analysis (Mock Mode)**\n\nThe scan confirms a {report_data.get('similarity_percentage')}% match. Specifically, logo detections provide near-certainty of unauthorized rebroadcasting. Recommend immediate DMCA notice."

class LocalFallbackProvider(AIProvider):
    """Local or Mock Provider when no Cloud AI is available."""
    def extract_topics(self, content_name: str) -> List[str]:
        # Fallback to simple split logic
        clean = content_name.split(".")[0].replace("_", " ").replace("-", " ")
        
        # Avoid generic terms that return millions of unrelated results
        GENERIC_NAMES = {"clip", "video", "output", "test", "movie", "recording", "stream"}
        if clean.lower() in GENERIC_NAMES or len(clean) < 3:
            return ["football highlights", "live soccer stream"] # Better default hunt
            
        return [clean, f"{clean} highlights", f"{clean} full match"]

    def analyze_compliance(self, uploader_repo: str, matched_percentage: float) -> str:
        if matched_percentage > 85:
            return "Local Verdict: HIGH RISK - Likely Piracy"
        return "Local Verdict: UNKNOWN - Proceed with caution"

    def analyze_full_report(self, report_data: dict) -> str:
        return "Local Fallback: Gemini API not configured. Based on similarity stats, this video shows significant overlap with protected assets. Manual review of frame-level data is recommended before issuing legal notice."

class AIEngine:
    def __init__(self):
        # Always maintain a fallback for resiliency
        self.fallback = LocalFallbackProvider()
        
        is_docker = os.getenv("RUN_MODE") == "DOCKER"
        google_key = os.getenv("GOOGLE_API_KEY")
        
        if is_docker and google_key and google_key != "MOCK":
            self.provider = GeminiProvider(google_key)
            self.mode = "Google Gemini (Docker-Ready)"
        else:
            self.provider = self.fallback
            self.mode = "Local Fallback (Host Mode)"

    def get_topics(self, name: str) -> List[str]:
        try:
            return self.provider.extract_topics(name)
        except Exception:
            return self.fallback.extract_topics(name)

    def get_verdict(self, repo: str, score: float) -> str:
        try:
            return self.provider.analyze_compliance(repo, score)
        except Exception:
            return self.fallback.analyze_compliance(repo, score)

    def analyze_report(self, report: dict) -> str:
        try:
            # If provider is Gemini, it might return an error string or raise
            res = self.provider.analyze_full_report(report)
            if "Gemini Error" in res or "Mock Mode" in res:
                return self.fallback.analyze_full_report(report)
            return res
        except Exception:
            return self.fallback.analyze_full_report(report)
