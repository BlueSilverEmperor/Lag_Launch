"""
core/visual_analyser.py
-----------------------
Multimodal Visual Analysis Engine for DAP.
Uses Llava (via Ollama) to describe video content from frames.
"""

import cv2
import base64
import numpy as np
from typing import List, Dict, Any, Optional
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage

class VisualAnalyser:
    def __init__(self, model: str = "llava"):
        self.llm = ChatOllama(model=model, temperature=0.2)

    def _encode_image(self, frame_bgr: np.ndarray) -> str:
        """Encodes an OpenCV BGR frame to base64 JPEG."""
        _, buffer = cv2.imencode('.jpg', frame_bgr)
        return base64.b64encode(buffer).decode('utf-8')

    def extract_visual_topics(self, frame_bgr: np.ndarray) -> str:
        """
        Sends a frame to Llava and asks for a description of the topics/content.
        """
        img_base64 = self._encode_image(frame_bgr)
        
        # Use LangChain Ollama multimodal format
        message = HumanMessage(
            content=[
                {"type": "text", "text": "Describe the main topics, people, and events occurring in this video frame. Be concise but specific about what the content actually is (e.g. sports, news, entertainment)."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
                },
            ]
        )
        
        try:
            response = self.llm.invoke([message])
            return response.content
        except Exception as e:
            print(f"Llava Inference failed: {e}")
            return "Visual analysis unavailable."

    def extract_batch_topics(self, frames: List[np.ndarray]) -> str:
        """
        Analyses multiple frames and synthesises a combined visual description.
        """
        descriptions = []
        for i, frame in enumerate(frames):
            desc = self.extract_visual_topics(frame)
            descriptions.append(f"Frame {i+1}: {desc}")
        
        return "\n".join(descriptions)

if __name__ == "__main__":
    # Quick test if a frame is provided (mock)
    import numpy as np
    analyser = VisualAnalyser()
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(mock_frame, "Test Sports Content", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    
    print("Testing Visual Analyser (Llava)...")
    result = analyser.extract_visual_topics(mock_frame)
    print(f"Result: {result}")
