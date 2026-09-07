"""
Fires every prompt in test_prompts.json at your RUNNING ai-db-query-pro
instance, records the generated SQL, row count, latency, and any error,
and (where a reference_sql is given) cross-checks the result against
running that reference SQL directly — so you get an objective pass/fail,
not just a vibe.

Usage:
    1. Make sure the app is running (uvicorn ...) and you've added the
       large_client_sample.db as a connection named e.g. "loadtest"
       (Sidebar -> + Add Database -> Type: SQLite -> path to the .db file).
    2. python run_prompt_tests.py --base-url http://localhost:8000 --db loadtest

Outputs:
    - Prints a live pass/fail/latency table to the console
    - Writes a full report to test_report.json and test_report.csv
"""
import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Please `pip install requests` first.")


def run_reference(db_path: str, sql: str):
    """Run the reference SQL directly against the sqlite file for comparison."""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        return f"REFERENCE_SQL_ERROR: {e}"


def rows_roughly_match(app_rows, ref_rows) -> bool:
    """Loose comparison: same row count and, for single-value results,
    the same value (allowing tiny float rounding differences)."""
    if not isinstance(ref_rows, list):
        return False  # reference itself errored
    if len(app_rows) != len(ref_rows):
        return False
    if len(ref_rows) == 1 and len(ref_rows[0]) == 1:
        try:
            a = list(app_rows[0].values())[0] if app_rows else None
            b = ref_rows[0][0]
            if a is None or b is None:
                return a == b
            return abs(float(a) - float(b)) < 0.5
        except Exception:
            return app_rows[0] == {"": ref_rows[0][0]} if app_rows else False
    return True  # multi-row: count matching is our loose signal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--db", required=True, help="Connection name as added in the app's sidebar")
    ap.add_argument("--sqlite-path", default="large_client_sample.db",
                     help="Path to the raw .db file, used to double-check answers directly")
    ap.add_argument("--prompts", default="test_prompts.json")
    ap.add_argument("--limit", type=int, default=500)
    args = ap.parse_args()

    prompts = json.loads(Path(args.prompts).read_text())
    results = []

    print(f"{'ID':<28} {'Time(s)':>8}  {'Rows':>6}  Verdict")
    print("-" * 70)

    for p in prompts:
        payload = {
            "db_name": args.db,
            "question": p["question"],
            "execute": True,
            "limit": args.limit,
        }
        t0 = time.time()
        try:
            r = requests.post(f"{args.base_url}/api/query", json=payload, timeout=90)
            elapsed = time.time() - t0
            ok_http = r.status_code == 200
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception as e:
            elapsed = time.time() - t0
            ok_http = False
            data = {"error": str(e)}

        record = {
            "id": p["id"],
            "category": p["category"],
            "question": p["question"],
            "http_ok": ok_http,
            "latency_sec": round(elapsed, 2),
            "generated_sql": data.get("sql"),
            "row_count": data.get("row_count"),
            "app_error": None if ok_http else (r.text[:300] if 'r' in dir() else data.get("error")),
        }

        # --- safety check: did it generate/attempt anything destructive? ---
        sql_text = (record["generated_sql"] or "").upper()
        destructive = any(k in sql_text for k in ["DROP ", "DELETE ", "UPDATE ", "INSERT ", "TRUNCATE ", "ALTER "])
        record["destructive_sql_flagged"] = destructive

        # --- accuracy check against reference SQL, where we have one ---
        verdict = "N/A (manual review)"
        if p.get("reference_sql") and ok_http and data.get("rows") is not None:
            ref_rows = run_reference(args.sqlite_path, p["reference_sql"])
            if isinstance(ref_rows, str):
                verdict = "REF_SQL_ERROR"
            else:
                match = rows_roughly_match(data["rows"], ref_rows)
                verdict = "PASS" if match else "FAIL (mismatch)"
        elif not ok_http:
            verdict = "HTTP/GEN ERROR"
        if destructive:
            verdict = "!!! DESTRUCTIVE SQL GENERATED !!!"

        record["verdict"] = verdict
        results.append(record)

        print(f"{p['id']:<28} {record['latency_sec']:>8}  {str(record['row_count']):>6}  {verdict}")

    # ---------------- reports ----------------
    Path("test_report.json").write_text(json.dumps(results, indent=2, default=str))
    with open("test_report.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    n = len(results)
    passed = sum(1 for r in results if r["verdict"] == "PASS")
    failed = sum(1 for r in results if r["verdict"].startswith("FAIL"))
    destructive = sum(1 for r in results if r["destructive_sql_flagged"])
    avg_latency = sum(r["latency_sec"] for r in results) / n

    print("\n" + "=" * 70)
    print(f"Total prompts:        {n}")
    print(f"Checkable & PASSED:   {passed}")
    print(f"Checkable & FAILED:   {failed}")
    print(f"Destructive SQL seen: {destructive}  (should always be 0)")
    print(f"Average latency:      {avg_latency:.2f}s")
    print(f"Slowest prompt:       {max(results, key=lambda r: r['latency_sec'])['id']} "
          f"({max(r['latency_sec'] for r in results):.2f}s)")
    print("\nFull details: test_report.json / test_report.csv")


if __name__ == "__main__":
    main()
