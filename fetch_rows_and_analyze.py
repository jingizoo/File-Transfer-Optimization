import os
import sys
import time
from collections import defaultdict

# Try oracledb first (newer), fall back to cx_Oracle (older, more stable)
try:
    import oracledb
    ORACLE_LIB = "oracledb"
except ImportError:
    try:
        import cx_Oracle as oracledb
        ORACLE_LIB = "cx_Oracle"
    except ImportError:
        sys.stderr.write(
            "ERROR: Neither oracledb nor cx_Oracle is installed.\n"
            "Install one of them:\n"
            "  Option 1 (recommended): pip3 install cx_Oracle\n"
            "  Option 2: pip3 install oracledb\n"
            "\n"
            "Note: cx_Oracle is more stable and easier to install.\n"
            "See ORACLE_INSTALL_FIX.md for troubleshooting.\n"
        )
        sys.exit(1)

try:
    import duckdb
except ImportError:
    sys.stderr.write("ERROR: duckdb not installed. Install with: pip3 install duckdb\n")
    sys.exit(1)

# Optional: pandas for faster bulk inserts
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


ORACLE_DSN = os.environ["ORACLE_DSN"]         
ORACLE_USER = os.environ["ORACLE_USER"]
ORACLE_PASSWORD = os.environ["ORACLE_PASSWORD"]

TABLE = os.environ.get("ORACLE_TABLE", "prod.cust_prdt_prc_entr")

# Optional: Oracle parallel degree (e.g. 4, 8). If set, we add a PARALLEL hint.
ORACLE_PARALLEL_DEGREE = os.environ.get("ORACLE_PARALLEL_DEGREE")
ORACLE_PARALLEL_DEGREE = os.environ.get("ORACLE_PARALLEL_DEGREE")
DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "dups.duckdb")

# how many rows to fetch from Oracle per round-trip
FETCH_BATCH = int(os.environ.get("FETCH_BATCH", "100000"))  # Increased default

# how many aggregated (unique-key) rows to insert to DuckDB at a time
INSERT_BATCH = int(os.environ.get("INSERT_BATCH", "50000"))  # Increased default

# Build Oracle SQL, optionally with PARALLEL hint
if ORACLE_PARALLEL_DEGREE:
    # Simple hint: /*+ parallel(TABLE, DEGREE) */
    _hint = f"/*+ parallel({TABLE}, {ORACLE_PARALLEL_DEGREE}) */ "
else:
    _hint = ""

# NOTE: Oracle column is prc_id (not price_id)
SQL = f"SELECT {_hint}prc_id, rqst_id, orgn_src_cde FROM {TABLE}"  # no WHERE, no ORDER BY, no DISTINCT

def main():
    # DuckDB setup - optimized for speed
    ddb = duckdb.connect(DUCKDB_PATH)
    ddb.execute("PRAGMA threads = 8;")
    ddb.execute("PRAGMA memory_limit = '8GB';")
    ddb.execute("PRAGMA enable_progress_bar = false;")  # Disable progress bar overhead
    # Fresh table each run so schema changes (e.g. BIGINT->VARCHAR) don't conflict
    ddb.execute("DROP TABLE IF EXISTS delta_counts;")
    ddb.execute("""
      CREATE TABLE delta_counts (
        prc_id VARCHAR,
        rqst_id VARCHAR,
        orgn_src_cde VARCHAR,
        cnt BIGINT
      );
    """)

    # Oracle setup - optimized for speed
    oconn = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN)
    cur = oconn.cursor()
    cur.arraysize = FETCH_BATCH  # Large fetch size reduces round-trips

    print(f"Using Oracle library: {ORACLE_LIB}")
    print("Executing:", SQL)
    cur.execute(SQL)

    processed = 0
    t0 = time.time()
    last_log = t0

    # buffer for DuckDB inserts
    out_rows = []

    while True:
        batch = cur.fetchmany(FETCH_BATCH)
        if not batch:
            break

        processed += len(batch)

        # count keys in this chunk (keeps memory bounded)
        counts = defaultdict(int)
        for prc_id, rqst_id, orgn_src_cde in batch:
            # Convert to tuple key (faster than string conversion here)
            key = (prc_id, rqst_id, orgn_src_cde)
            counts[key] += 1

        # push aggregated rows to DuckDB - use bulk insert for speed
        for (k, c) in counts.items():
            # Cast keys to string so Oracle types like TIMESTAMP/NUMBER map cleanly into DuckDB
            out_rows.append((str(k[0]), str(k[1]), str(k[2]), c))
            if len(out_rows) >= INSERT_BATCH:
                # Fastest: use pandas DataFrame + register() if available
                if HAS_PANDAS:
                    df = pd.DataFrame(out_rows, columns=['price_id', 'rqst_id', 'orgn_src_cde', 'cnt'])
                    ddb.register("temp_batch", df)
                    ddb.execute("INSERT INTO delta_counts SELECT * FROM temp_batch")
                    ddb.unregister("temp_batch")
                else:
                    # Fallback: executemany (still fast with large batches)
                    ddb.executemany("INSERT INTO delta_counts VALUES (?,?,?,?)", out_rows)
                # Commit less frequently for better performance
                ddb.commit()
                out_rows.clear()

        # periodic progress (time-based, so you always see updates)
        now = time.time()
        if now - last_log >= 5.0:  # log roughly every 5 seconds
            elapsed = now - t0
            rate = processed / elapsed if elapsed > 0 else 0
            print(
                f"processed={processed:,} rows  elapsed={elapsed:.1f}s  rate={rate:,.0f} rows/s",
                flush=True,
            )
            last_log = now

    # flush remaining
    if out_rows:
        if HAS_PANDAS:
            df = pd.DataFrame(out_rows, columns=['price_id', 'rqst_id', 'orgn_src_cde', 'cnt'])
            ddb.register("temp_batch", df)
            ddb.execute("INSERT INTO delta_counts SELECT * FROM temp_batch")
            ddb.unregister("temp_batch")
        else:
            ddb.executemany("INSERT INTO delta_counts VALUES (?,?,?,?)", out_rows)
        ddb.commit()
        out_rows.clear()

    cur.close()
    oconn.close()

    # Final duplicate summary in DuckDB
    ddb.execute("""
      CREATE OR REPLACE VIEW dup_summary AS
      SELECT price_id, rqst_id, orgn_src_cde,
             SUM(cnt) AS total_cnt,
             SUM(cnt) - 1 AS extra_rows
      FROM delta_counts
      GROUP BY 1,2,3
      HAVING SUM(cnt) > 1
      ORDER BY extra_rows DESC;
    """)

    # Export top duplicates
    ddb.execute("COPY (SELECT * FROM dup_summary LIMIT 5000) TO 'dup_summary_top5000.csv' (HEADER, DELIMITER ',');")
    ddb.execute("COPY (SELECT COUNT(*) AS dup_key_count, SUM(extra_rows) AS total_extra_rows FROM dup_summary) TO 'dup_totals.csv' (HEADER, DELIMITER ',');")

    print("Done. Outputs:")
    print("- DuckDB:", DUCKDB_PATH)
    print("- dup_summary_top5000.csv")
    print("- dup_totals.csv")

    ddb.close()

if __name__ == "__main__":
    main()