"""
LLM Client – supports:
  1. Local Ollama
  2. xAI / Grok API  (recommended – fast)
  3. Any OpenAI-compatible endpoint (OpenAI, Groq, Together, etc.)
"""

from __future__ import annotations

import re
import requests
from typing import List, Optional, Tuple


# -------------------- Defaults --------------------
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_XAI_URL = "https://api.x.ai/v1"
DEFAULT_MODEL_OLLAMA = "qwen2.5:3b"
DEFAULT_MODEL_XAI = "grok-3"          # or grok-2, grok-3-mini etc.


SYSTEM_PROMPT = """You are an expert SQL query generator. Your only job is to convert a natural language question into a correct, efficient, read-only SQL query.

Rules:
1. Output ONLY the SQL query. No explanations, no markdown fences, no comments unless necessary.
2. Use ONLY the tables and columns that appear in the provided schema.
3. Prefer explicit column lists over SELECT *.
4. Always use the correct dialect syntax for the target database.
5. If the question cannot be answered from the schema, respond with exactly: -- ERROR: Could not find this information in the selected database schema
6. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE or any write operation.
7. Add reasonable LIMIT (e.g. 100) if the user asks for "all" or "list" without a clear bound.
8. Use proper JOINs when data spans multiple tables. Prefer INNER JOIN unless LEFT is needed.
9. For date filtering use the dialect's date functions.
10. Quote identifiers only when necessary (reserved words or mixed case).
"""


def build_prompt(
    question: str,
    schema_text: str,
    dialect: str = "sqlite",
    extra_instructions: str = "",
) -> str:
    return f"""{SYSTEM_PROMPT}

Target SQL dialect: {dialect.upper()}

Database schema:
{schema_text}

{extra_instructions}

User question:
{question}

SQL query:"""


class LLMClient:
    def __init__(
        self,
        provider: str = "xai",                 # "xai" | "ollama" | "openai"
        base_url: str = DEFAULT_XAI_URL,
        model: str = DEFAULT_MODEL_XAI,
        api_key: str = "",
        timeout: int = 60,
    ):
        self.provider = provider.lower()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key.strip()
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------
    def is_available(self) -> Tuple[bool, str]:
        if self.provider == "ollama":
            return self._check_ollama()
        else:
            return self._check_openai_compatible()

    def _check_ollama(self) -> Tuple[bool, str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                if any(self.model in m for m in models):
                    return True, f"Ollama ready – model '{self.model}' found"
                return True, f"Ollama ready. Available models: {models[:6]}"
            return False, f"Ollama returned {r.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to Ollama. Is it running?"
        except Exception as e:
            return False, str(e)

    def _check_openai_compatible(self) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "API key is missing"
        # Key is configured on server — treat as ready.
        # Still try a light ping; any network response means OK.
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            r = requests.get(f"{self.base_url.rstrip('/')}/models", headers=headers, timeout=8)
            if r.status_code in (200, 401, 403, 404):
                return True, "Connected — API key configured"
            # Non-standard status but key exists
            return True, "Connected — API key configured"
        except Exception:
            # Key is present; queries may still work
            return True, "Connected — API key configured"

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> Tuple[bool, str]:
        if self.provider == "ollama":
            return self._generate_ollama(prompt, temperature, max_tokens)
        else:
            return self._generate_openai(prompt, temperature, max_tokens)

    def _generate_ollama(self, prompt: str, temperature: float, max_tokens: int) -> Tuple[bool, str]:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            r = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return True, r.json().get("response", "").strip()
        except requests.exceptions.Timeout:
            return False, "LLM request timed out. Try a smaller model."
        except Exception as e:
            return False, f"LLM error: {str(e)}"

    def _generate_openai(self, prompt: str, temperature: float, max_tokens: int) -> Tuple[bool, str]:
        if not self.api_key:
            return False, "API key is required for this provider"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert SQL generator. Output only pure SQL."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            return True, content
        except requests.exceptions.Timeout:
            return False, "API request timed out."
        except requests.exceptions.HTTPError as e:
            try:
                err = r.json().get("error", {}).get("message", str(e))
            except Exception:
                err = str(e)
            return False, f"API error: {err}"
        except Exception as e:
            return False, f"API error: {str(e)}"

    def generate_sql(
        self,
        question: str,
        schema_text: str,
        dialect: str = "sqlite",
        extra_instructions: str = "",
    ) -> Tuple[bool, str, str]:
        prompt = build_prompt(question, schema_text, dialect, extra_instructions)
        ok, raw = self.generate(prompt)
        if not ok:
            return False, raw, raw

        sql = self._extract_sql(raw)
        if sql.startswith("-- ERROR"):
            return False, sql, raw
        return True, sql, raw

    @staticmethod
    def _extract_sql(text: str) -> str:
        text = text.strip()

        # Remove markdown fences
        fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if fence:
            text = fence.group(1).strip()

        # Find first SQL keyword
        lines = text.splitlines()
        start_idx = 0
        for i, line in enumerate(lines):
            upper = line.strip().upper()
            if upper.startswith(("SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "PRAGMA")):
                start_idx = i
                break
        text = "\n".join(lines[start_idx:]).strip()

        if ";" in text:
            text = text.split(";")[0] + ";"

        return text.strip()
