import json
import os
import re

from google import genai


class GeminiNeedAnalyzer:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY is required. Set it before starting the app.")
        self.enabled = True
        self.client = genai.Client(api_key=self.api_key)

    def _strip_json_fence(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```json\\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\\s*", "", text)
        text = re.sub(r"\\s*```$", "", text)
        return text.strip()

    def analyze(self, raw_text: str, location: str) -> dict[str, object]:
        prompt = f"""
You are helping an NGO triage community field reports.
Return ONLY strict JSON with this schema:
{{
  "title": string,
  "description": string,
  "category": string,
  "urgency_score": number between 0 and 100,
  "required_skills": string[],
  "task_title": string,
  "task_description": string,
  "required_people": integer between 1 and 20
}}

Field report text:
{raw_text}

Location:
{location}
""".strip()
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            payload = self._strip_json_fence(response.text or "")
            data = json.loads(payload)
            data["urgency_score"] = max(0, min(100, float(data.get("urgency_score", 60))))
            data["required_people"] = max(1, min(20, int(data.get("required_people", 3))))
            if not isinstance(data.get("required_skills", []), list):
                data["required_skills"] = ["community_outreach"]
            return data
        except Exception as exc:
            raise RuntimeError(f"Gemini analysis failed: {exc}") from exc
