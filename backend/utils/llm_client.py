"""
LLM Client – supports:
  1. Local Ollama
  2. xAI / Grok API  (recommended – fast)
  3. Any OpenAI-compatible endpoint (OpenAI, Groq, Gemini OpenAI-compat, Together, etc.)
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


SYSTEM_PROMPT = """You are an expert SQL query generator specialized in telecom BSS and streaming/OTT platforms.

Your ONLY job is to convert a natural language question into a correct, efficient, read-only SQL query.

STRICT RULES:
1. Output ONLY the SQL query. No explanations, no markdown fences, no comments, no preamble.
2. Use ONLY tables and columns that appear in the provided schema. Never invent columns or tables.
3. Prefer explicit column lists over SELECT *.
4. Use correct dialect syntax for the target database (especially date functions).
5. If the question cannot be answered from the schema, respond with exactly:
   -- ERROR: Cannot answer from available schema
6. NEVER generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE or any write/DDL operation.
7. Add a reasonable LIMIT (e.g. 50 or 100) when the user asks for "list", "show all", "top" without a clear bound. For pure aggregates (COUNT, SUM, AVG) do not add LIMIT.
8. Use proper JOINs when data spans multiple tables. Prefer INNER JOIN unless LEFT is needed for "never did X" / anti-join patterns.
9. For date filtering:
   - SQLite: date('now'), datetime('now'), date(column), strftime('%Y-%m', column)
   - Prefer comparing date columns with date literals 'YYYY-MM-DD'
10. Quote identifiers only when necessary (reserved words or mixed case).
11. For "last N days / months" use relative date expressions appropriate to the dialect.
12. When counting distinct entities after a join, use COUNT(DISTINCT id_column).
13. Status / type columns are usually lowercase strings (e.g. 'active', 'paid', 'success', 'open').
14. Boolean-like flags are often INTEGER 0/1 (is_active, auto_renew, is_premium, is_registered).

DOMAIN HINTS (telecom + streaming):
- customers ↔ subscriptions ↔ plans
- customers ↔ devices
- customers ↔ watch_history ↔ content_catalog
- customers ↔ invoices ↔ payments
- customers ↔ support_tickets
- customers ↔ data_usage
- series / episodes link to content_catalog for series-type content
- "active subscribers" usually means subscriptions.status = 'active'
- "churned" / "cancelled" → status IN ('cancelled','expired')
- "ARPU" / revenue → SUM of invoice or payment amounts (usually successful/paid)
- "most watched" → GROUP BY content, ORDER BY COUNT(*) or SUM(watch_seconds)
- "data usage" is in MB in data_usage.data_mb
- plan_type values: mobile_prepaid, mobile_postpaid, broadband, streaming_only, bundle

FEW-SHOT EXAMPLES (follow this style closely):

Question: How many active customers do we have?
SQL: SELECT COUNT(*) AS active_customers FROM customers WHERE is_active = 1;

Question: Show the top 10 most watched titles by number of views.
SQL: SELECT c.title, c.content_type, COUNT(*) AS view_count
FROM watch_history w
JOIN content_catalog c ON c.content_id = w.content_id
GROUP BY c.content_id, c.title, c.content_type
ORDER BY view_count DESC
LIMIT 10;

Question: How many active subscriptions are on broadband plans?
SQL: SELECT COUNT(*) AS active_broadband_subs
FROM subscriptions s
JOIN plans p ON p.plan_id = s.plan_id
WHERE s.status = 'active' AND p.plan_type = 'broadband';

Question: List customers who have never placed a support ticket.
SQL: SELECT c.customer_id, c.full_name, c.email
FROM customers c
LEFT JOIN support_tickets t ON t.customer_id = c.customer_id
WHERE t.ticket_id IS NULL
LIMIT 100;

Question: Total successful payment amount in the last 90 days.
SQL: SELECT ROUND(SUM(amount), 2) AS total_paid
FROM payments
WHERE status = 'success'
  AND payment_date >= date('now', '-90 days');

Question: Which cities have the most active subscribers?
SQL: SELECT c.city, COUNT(DISTINCT s.customer_id) AS active_subscribers
FROM customers c
JOIN subscriptions s ON s.customer_id = c.customer_id
WHERE s.status = 'active'
GROUP BY c.city
ORDER BY active_subscribers DESC
LIMIT 20;
"""


def build_prompt(
    question: str,
    schema_text: str,
    dialect: str = "sqlite",
    extra_instructions: str = "",
) -> str:
    extra = ""
    if extra_instructions.strip():
        extra = f"\nAdditional instructions from user:\n{extra_instructions.strip()}\n"

    return f"""{SYSTEM_PROMPT}

Target SQL dialect: {dialect.upper()}

Database schema:
{schema_text}
{extra}
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
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            r = requests.get(f"{self.base_url}/models", headers=headers, timeout=8)
            if r.status_code in (200, 401, 403):
                return True, f"API endpoint reachable ({self.provider})"
            return False, f"API returned {r.status_code}"
        except Exception as e:
            return False, f"Cannot reach API: {e}"

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: str,
        temperature: float = 0.05,
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
        # Put the full system rules in the system message for better compliance
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an expert SQL generator for telecom and streaming databases. "
                        "Output ONLY pure SQL. No markdown, no explanation. "
                        "Never produce write/DDL statements."
                    ),
                },
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
            if upper.startswith("-- ERROR"):
                return line.strip()
        text = "\n".join(lines[start_idx:]).strip()

        if ";" in text:
            text = text.split(";")[0] + ";"

        return text.strip()
