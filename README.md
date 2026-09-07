# AI Database Query Assistant – Proper Product

**Backend:** FastAPI (REST APIs)  
**Frontend:** HTML + CSS + JavaScript  
**LLM:** Groq / Gemini / DeepSeek / xAI / Ollama

This is a complete product you can present to your team lead.

---

## Features

- Connect multiple databases (PostgreSQL, MySQL, SQLite, SQL Server)
- Automatic schema scanning
- Natural language → SQL
- Results table + CSV download
- Full REST API with Swagger docs at `/docs`
- Clean modern frontend

---

## Quick Start

```bash
cd ai-db-query-pro
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate

pip install -r requirements.txt

# Set your LLM API key (server-side only — see "LLM Setup" below)
cp .env.example .env
# then edit .env and paste your real key into LLM_API_KEY

# Start the server
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open in browser: **http://localhost:8000**

API documentation: **http://localhost:8000/docs**

---

## API Endpoints (for your team lead)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/connections` | List connected DBs |
| POST | `/api/connections` | Add new DB |
| POST | `/api/connections/test` | Test connection |
| DELETE | `/api/connections/{name}` | Remove DB |
| POST | `/api/connections/{name}/refresh-schema` | Re-scan schema |
| GET | `/api/schema/{name}` | Full schema JSON |
| POST | `/api/query` | Natural language → SQL + results |
| POST | `/api/execute` | Run raw SQL |
| POST | `/api/llm/config` | Configure LLM |
| GET | `/api/llm/status` | LLM status |
| GET | `/docs` | Swagger UI |

---

## LLM Setup (server-side only, via `.env`)

The API key is **never entered in the browser**. It lives only in the
`.env` file on the server, is loaded by `backend/main.py`, and is not
returned by any API response — end users of the app can't see it or
change it. To change provider/model/key, edit `.env` and restart the
server.

```
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-20b
LLM_API_KEY=your-api-key-here
```

**Groq (fast & free tier)**
- Base URL: `https://api.groq.com/openai/v1`
- Model: `openai/gpt-oss-20b`
- Key from: https://console.groq.com/keys

**Gemini (free)**
- Base URL: `https://generativelanguage.googleapis.com/v1beta/openai`
- Model: `gemini-2.0-flash`
- Key from: https://aistudio.google.com

**DeepSeek**
- Base URL: `https://api.deepseek.com`
- Model: `deepseek-v4-flash`

**Ollama (local, no key needed)**
- Base URL: `http://localhost:11434`
- Model: e.g. `qwen2.5:3b`
- Leave `LLM_API_KEY` blank

Remember to add your real `.env` to `.gitignore` (already done here) so
the key never ends up in source control or a shared zip.

---

## Project Structure

```
ai-db-query-pro/
├── backend/
│   ├── main.py          ← FastAPI app (all APIs)
│   └── utils/
│       ├── db_manager.py
│       └── llm_client.py
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── data/
├── scripts/
├── requirements.txt
└── README.md
```

---

## Sharing with Team

1. Run on one machine:  
   `uvicorn main:app --host 0.0.0.0 --port 8000`
2. Team opens `http://YOUR_IP:8000`
3. All connections are shared (stored in `data/connections.json`)

---

Built as a proper product with real backend APIs.

---

## Streaming + Telecom sample database

A large realistic domain DB is included for accuracy testing:

- **Path:** `data/streaming_telecom.db` (also in `testkit/`)
- **Domain:** OTT/streaming platform + mobile/broadband telecom BSS
- **Size:** ~30k customers, 80k subscriptions, 400k watch events, 150k invoices, …

See `testkit/README.md` for the full schema, how to regenerate, and how to
run the offline accuracy suite (`run_offline_accuracy.py`).

### Accuracy upgrades in this build

- Domain-specific system prompt + few-shot examples for telecom/streaming
- Schema text now includes relationship hints and sample status/type values
- Lower sampling temperature for more stable SQL
- Offline test harness with reference SQL comparison

Point the app at `streaming_telecom.db`, ask questions like:

- “How many active broadband subscriptions do we have?”
- “Top 10 most watched titles”
- “Total successful payments in the last 90 days”
- “Customers who have never watched any content”
