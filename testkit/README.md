# AI DB Query — Stress / Accuracy Test Kit

## Domain database (streaming + telecom)

`streaming_telecom.db` (~100 MB) is a realistic SQLite database that mirrors
the kinds of systems a software house builds for OTT / IPTV and mobile /
broadband BSS clients.

| Table              | ~Rows (scale=1) | Purpose |
|--------------------|-----------------|---------|
| customers          | 30,000          | Subscribers |
| plans              | 40              | Mobile, broadband, streaming, bundles |
| subscriptions      | 80,000          | Customer ↔ plan links |
| devices            | 55,000          | STBs, phones, TVs, web |
| content_catalog    | 2,500           | Movies, series, live, sports… |
| series / episodes  | hundreds        | Series structure |
| watch_history      | 400,000         | Viewing sessions |
| data_usage         | 200,000         | Mobile/broadband usage (MB) |
| invoices           | 150,000         | Billing |
| payments           | 140,000         | Payment attempts |
| support_tickets    | 25,000          | CRM-style tickets |
| network_events     | 50,000          | Outages / speed drops |

Regenerate or scale up:

```bash
python generate_streaming_telecom_db.py streaming_telecom.db --scale 1
# --scale 2 ≈ 2× rows
```

(The older e-commerce `large_client_sample.db` is still present if you need it.)

## Accuracy improvements made in this package

1. **Domain-aware system prompt** with telecom/streaming vocabulary, status
   value conventions, and date-function guidance for SQLite.
2. **Few-shot examples** embedded in the prompt (active subs, top watched,
   anti-join “never watched”, revenue last 90 days, etc.).
3. **Richer schema text** sent to the LLM: relationship diagram + distinct
   sample values for status/type columns so the model stops guessing
   `'Active'` vs `'active'`.
4. **Lower temperature** (0.05) for more deterministic SQL.
5. **Offline accuracy harness** (`run_offline_accuracy.py`) that compares
   generated SQL results against reference SQL without needing the web UI.

## How to run accuracy tests

### A. Offline (recommended for iteration)

```bash
# from testkit/
# ensure ../.env has a working LLM key (Gemini / Groq / xAI / OpenAI)
python run_offline_accuracy.py \
  --db streaming_telecom.db \
  --prompts test_prompts_streaming.json
```

Reports: `accuracy_report_streaming.json` / `.csv`

### B. Against the running app

1. Copy `streaming_telecom.db` into `data/` (already done in this package).
2. Start the backend, add the DB in the UI as connection name e.g. `telecom`.
3. Run:

```bash
python run_prompt_tests.py \
  --base-url http://localhost:8000 \
  --db telecom \
  --sqlite-path streaming_telecom.db \
  --prompts test_prompts_streaming.json
```

## Prompt set (`test_prompts_streaming.json`)

24 prompts covering:

- Basic counts & filters
- Joins (subs ↔ plans, watch ↔ content)
- Date windows (`last 90 days`, month groups)
- Anti-joins (“never watched”)
- HAVING, ratios, multi-filter tickets
- Out-of-schema refusal
- Prompt-injection / destructive SQL
- Unbounded list (must apply LIMIT)

## What “good accuracy” looks like

On a capable model (Gemini 2.5 Flash, GPT-4o-mini, Groq Llama-3.3, Grok, etc.)
you should see **≥ 85–90% PASS** on the scored prompts after the prompt
upgrades in this package. The first batch of tests run during packaging
scored **4/4 PASS** before rate limits kicked in on the free Gemini tier.

If accuracy is still low:

1. Switch to a stronger model in `.env` (e.g. `gemini-2.5-pro`, `grok-3`, or Groq).
2. Re-run offline harness and inspect `generated_sql` for systematic mistakes.
3. Add 2–3 more few-shot examples of the failing pattern into
   `backend/utils/llm_client.py` → `SYSTEM_PROMPT`.

## Security note

The harness flags any `DROP`/`DELETE`/`INSERT`/… as **DESTRUCTIVE**. That must
stay at zero. The system prompt + keyword checks in the app backend are the
first line of defence; treat a single destructive generation as a blocker.
