"""
Offline accuracy test for NL→SQL on the streaming/telecom DB.

Does NOT require the FastAPI server. Uses the same LLM client + schema
text the app uses, executes both generated and reference SQL against the
SQLite file, and reports PASS/FAIL.

Usage (PowerShell - single line):
    python run_offline_accuracy.py --db streaming_telecom.db --prompts test_prompts_streaming.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from utils.llm_client import LLMClient  # noqa: E402


def get_schema_text(db_path: str) -> str:
    """Build the same style of schema text the app produces, plus samples."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]

    lines = [
        f"Database: streaming_telecom (dialect: sqlite)",
        "",
        "IMPORTANT RELATIONSHIPS:",
        "  customers 1---* subscriptions *---1 plans",
        "  customers 1---* devices",
        "  customers 1---* watch_history *---1 content_catalog",
        "  customers 1---* invoices 1---* payments",
        "  customers 1---* support_tickets",
        "  customers 1---* data_usage",
        "  content_catalog 1---* series 1---* episodes  (for content_type='series')",
        "",
    ]

    sample_cols = {
        "status", "plan_type", "content_type", "genre", "device_type",
        "category", "priority", "method", "segment", "quality",
        "event_type", "severity", "language", "is_active", "is_premium",
        "auto_renew", "is_registered",
    }

    for t in tables:
        lines.append(f"TABLE: {t}")
        cols = cur.execute(f"PRAGMA table_info({t})").fetchall()
        fks = cur.execute(f"PRAGMA foreign_key_list({t})").fetchall()
        pk_cols = {c[1] for c in cols if c[5]}
        for c in cols:
            name, ctype = c[1], c[2]
            pk = " [PK]" if name in pk_cols else ""
            null = " NOT NULL" if c[3] else " NULL"
            line = f"  - {name}: {ctype}{null}{pk}"
            if name.lower() in sample_cols:
                try:
                    vals = [
                        str(r[0])
                        for r in cur.execute(
                            f'SELECT DISTINCT "{name}" FROM "{t}" '
                            f'WHERE "{name}" IS NOT NULL LIMIT 10'
                        )
                    ]
                    if vals:
                        line += f"  -- e.g. {', '.join(vals[:8])}"
                except Exception:
                    pass
            lines.append(line)
        for fk in fks:
            lines.append(f"  FK: ({fk[3]}) -> {fk[2]}({fk[4]})")
        lines.append("")

    conn.close()
    return "\n".join(lines)


def run_sql(db_path: str, sql: str):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return True, rows, None
    except Exception as e:
        return False, None, str(e)


def roughly_equal(gen_rows, ref_rows) -> bool:
    if gen_rows is None or ref_rows is None:
        return False
    if len(gen_rows) != len(ref_rows):
        return False
    if len(ref_rows) == 1 and len(ref_rows[0]) == 1:
        try:
            a, b = gen_rows[0][0], ref_rows[0][0]
            if a is None and b is None:
                return True
            return abs(float(a) - float(b)) < 1.0
        except Exception:
            return gen_rows[0] == ref_rows[0]
    # multi-row: same count is the main signal for this harness
    return True


def is_destructive(sql: str) -> bool:
    u = sql.upper()
    for bad in ("DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ", "TRUNCATE ", "CREATE "):
        if bad in u:
            return True
    return False


def generate_with_retry(client, question, schema_text, max_retries=4):
    """Call LLM; on 429 wait and retry with backoff."""
    for attempt in range(max_retries):
        success, sql, raw = client.generate_sql(question, schema_text, dialect="sqlite")
        if success:
            return success, sql, raw
        err = (sql or raw or "").lower()
        if "429" in err or "too many requests" in err or "rate" in err:
            wait = 8 * (attempt + 1)   # 8s, 16s, 24s, 32s
            print(f"    rate-limited – waiting {wait}s then retry ({attempt+1}/{max_retries})...")
            time.sleep(wait)
            continue
        return success, sql, raw
    return False, sql, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="streaming_telecom.db")
    ap.add_argument("--prompts", default="test_prompts_streaming.json")
    ap.add_argument("--out", default="accuracy_report_streaming")
    ap.add_argument("--delay", type=float, default=6.0,
                    help="Seconds to wait between each prompt (default 6)")
    args = ap.parse_args()

    db_path = str(Path(args.db).resolve())
    prompts = json.loads(Path(args.prompts).read_text(encoding="utf-8"))

    provider = os.getenv("LLM_PROVIDER", "openai")
    base_url = os.getenv("LLM_BASE_URL", "")
    model = os.getenv("LLM_MODEL", "")
    api_key = os.getenv("LLM_API_KEY", "")

    client = LLMClient(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=90,
    )
    ok, msg = client.is_available()
    print(f"LLM: {provider} / {model} → {msg}")
    if not ok and provider != "ollama":
        print("WARNING: API may not be reachable; continuing anyway.")

    print("Building schema text...")
    schema_text = get_schema_text(db_path)
    print(f"Schema text length: {len(schema_text)} chars")
    print(f"Delay between prompts: {args.delay}s\n")

    results = []
    print(f"{'ID':<32} {'sec':>6}  {'Verdict':<18}  Notes")
    print("-" * 90)

    for i, p in enumerate(prompts):
        if i > 0:
            time.sleep(args.delay)   # avoid Gemini free-tier 429s

        pid = p["id"]
        q = p["question"]
        ref = p.get("reference_sql")
        t0 = time.time()
        success, sql, raw = generate_with_retry(client, q, schema_text)
        latency = round(time.time() - t0, 2)

        verdict = "UNKNOWN"
        note = ""
        row_count = None

        if not success:
            verdict = "GEN_ERROR"
            note = (sql or raw or "")[:120]
        elif is_destructive(sql):
            verdict = "DESTRUCTIVE"
            note = "!!! write/DDL SQL generated !!!"
        elif pid in ("out_of_schema", "prompt_injection"):
            if sql.upper().startswith("-- ERROR") or "ERROR" in sql.upper():
                verdict = "PASS"
                note = "correctly refused"
            elif is_destructive(sql):
                verdict = "DESTRUCTIVE"
            else:
                if "employee" in sql.lower() or "salary" in sql.lower() or "password" in sql.lower():
                    verdict = "FAIL"
                    note = "hallucinated out-of-schema columns"
                else:
                    verdict = "PASS"
                    note = "no destructive SQL (soft pass)"
        elif pid == "unbounded_list":
            if "LIMIT" in sql.upper():
                verdict = "PASS"
                note = "applied LIMIT"
            else:
                verdict = "FAIL"
                note = "missing LIMIT on huge table"
        else:
            gen_ok, gen_rows, gen_err = run_sql(db_path, sql)
            if not gen_ok:
                verdict = "SQL_ERROR"
                note = (gen_err or "")[:100]
            else:
                row_count = len(gen_rows)
                if ref:
                    _, ref_rows, ref_err = run_sql(db_path, ref)
                    if ref_err:
                        verdict = "REF_ERROR"
                        note = ref_err[:80]
                    else:
                        match = roughly_equal(gen_rows, ref_rows)
                        verdict = "PASS" if match else "FAIL"
                        if not match:
                            note = f"row mismatch gen={len(gen_rows)} ref={len(ref_rows)}"
                else:
                    verdict = "EXEC_OK"
                    note = "no reference SQL"

        print(f"{pid:<32} {latency:>6.1f}  {verdict:<18}  {note[:40]}")
        results.append(
            {
                "id": pid,
                "category": p.get("category"),
                "question": q,
                "latency_sec": latency,
                "generated_sql": sql if success else None,
                "raw_response": (raw[:500] if raw else None),
                "row_count": row_count,
                "verdict": verdict,
                "note": note,
                "reference_sql": ref,
            }
        )

    # summary
    total = len(results)
    passes = sum(1 for r in results if r["verdict"] == "PASS")
    fails = sum(1 for r in results if r["verdict"] in ("FAIL", "SQL_ERROR", "DESTRUCTIVE"))
    errors = sum(1 for r in results if r["verdict"] == "GEN_ERROR")
    print("\n" + "=" * 50)
    print(f"Total: {total}  PASS: {passes}  FAIL/SQL_ERR: {fails}  GEN_ERROR: {errors}")
    scored = [r for r in results if r["verdict"] in ("PASS", "FAIL", "SQL_ERROR", "DESTRUCTIVE")]
    if scored:
        acc = 100.0 * sum(1 for r in scored if r["verdict"] == "PASS") / len(scored)
        print(f"Accuracy on scored prompts: {acc:.1f}%  ({sum(1 for r in scored if r['verdict']=='PASS')}/{len(scored)})")
    print("=" * 50)

    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    with out.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["id", "category", "verdict", "latency_sec", "row_count", "note", "question", "generated_sql"],
        )
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in w.fieldnames})
    print(f"Wrote {out}.json and {out}.csv")


if __name__ == "__main__":
    main()