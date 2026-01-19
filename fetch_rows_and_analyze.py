import os, time
from collections import defaultdict

import oracledb
import duckdb


ORACLE_DSN = os.environ["ORACLE_DSN"]         
ORACLE_USER = os.environ["ORACLE_USER"]
ORACLE_PASSWORD = os.environ["ORACLE_PASSWORD"]

TABLE = os.environ.get("ORACLE_TABLE", "prod.cust_prdt_prc_entr")
DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "dups.duckdb")

# how many rows to fetch from Oracle per round-trip
FETCH_BATCH = int(os.environ.get("FETCH_BATCH", "50000"))

# how many aggregated (unique-key) rows to insert to DuckDB at a time
INSERT_BATCH = int(os.environ.get("INSERT_BATCH", "20000"))

SQL = f"SELECT price_id, rqst_id, orgn_src_cde FROM {TABLE}"  # no WHERE, no ORDER BY, no DISTINCT

def main():
    # DuckDB setup
    ddb = duckdb.connect(DUCKDB_PATH)
    ddb.execute("PRAGMA threads = 8;")
    ddb.execute("PRAGMA memory_limit = '8GB';")  # tune
    ddb.execute("""
      CREATE TABLE IF NOT EXISTS delta_counts (
        price_id BIGINT,
        rqst_id BIGINT,
        orgn_src_cde VARCHAR,
        cnt BIGINT
      );
    """)
    ddb.commit()

    # Oracle setup
    oconn = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASSWORD, dsn=ORACLE_DSN)
    cur = oconn.cursor()
    cur.arraysize = FETCH_BATCH

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
        for price_id, rqst_id, orgn_src_cde in batch:
            counts[(price_id, rqst_id, orgn_src_cde)] += 1

        # push aggregated rows to DuckDB
        for (k, c) in counts.items():
            out_rows.append((k[0], k[1], k[2], c))
            if len(out_rows) >= INSERT_BATCH:
                ddb.executemany("INSERT INTO delta_counts VALUES (?,?,?,?)", out_rows)
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