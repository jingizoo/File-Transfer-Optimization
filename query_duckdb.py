#!/usr/bin/env python3
"""
Example script to query DuckDB database created by fetch_rows_and_analyze.py
Usage: python3 query_duckdb.py [duckdb_path]
"""

import sys
import os
import duckdb

# Default path (same as fetch_rows_and_analyze.py)
DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "dups.duckdb")

if len(sys.argv) > 1:
    DUCKDB_PATH = sys.argv[1]

if not os.path.exists(DUCKDB_PATH):
    print(f"ERROR: DuckDB file not found: {DUCKDB_PATH}")
    sys.exit(1)

# Connect to DuckDB
conn = duckdb.connect(DUCKDB_PATH)

print(f"Connected to: {DUCKDB_PATH}\n")

# Example 1: Query the raw delta_counts table
print("=" * 60)
print("Example 1: Sample rows from delta_counts table")
print("=" * 60)
result = conn.execute("""
    SELECT price_id, rqst_id, orgn_src_cde, cnt
    FROM delta_counts
    ORDER BY cnt DESC
    LIMIT 10
""").fetchall()

for row in result:
    print(f"  price_id={row[0]}, rqst_id={row[1]}, orgn_src_cde={row[2]}, cnt={row[3]}")

# Example 2: Query the dup_summary view (duplicates only)
print("\n" + "=" * 60)
print("Example 2: Top 10 duplicates from dup_summary view")
print("=" * 60)
result = conn.execute("""
    SELECT price_id, rqst_id, orgn_src_cde, total_cnt, extra_rows
    FROM dup_summary
    LIMIT 10
""").fetchall()

for row in result:
    print(f"  price_id={row[0]}, rqst_id={row[1]}, orgn_src_cde={row[2]}, "
          f"total_cnt={row[3]}, extra_rows={row[4]}")

# Example 3: Get summary statistics
print("\n" + "=" * 60)
print("Example 3: Summary statistics")
print("=" * 60)
stats = conn.execute("""
    SELECT 
        COUNT(*) AS total_unique_keys,
        SUM(cnt) AS total_rows,
        COUNT(CASE WHEN cnt > 1 THEN 1 END) AS duplicate_keys,
        SUM(CASE WHEN cnt > 1 THEN cnt - 1 ELSE 0 END) AS total_extra_rows
    FROM delta_counts
""").fetchone()

print(f"  Total unique keys: {stats[0]:,}")
print(f"  Total rows: {stats[1]:,}")
print(f"  Keys with duplicates: {stats[2]:,}")
print(f"  Total extra rows (duplicates): {stats[3]:,}")

# Example 4: Custom query - find specific key
print("\n" + "=" * 60)
print("Example 4: Search for a specific key (modify as needed)")
print("=" * 60)
# Uncomment and modify to search:
# result = conn.execute("""
#     SELECT price_id, rqst_id, orgn_src_cde, cnt
#     FROM delta_counts
#     WHERE price_id = '12345'
# """).fetchall()
# for row in result:
#     print(f"  {row}")

# Example 5: Export query results to CSV
print("\n" + "=" * 60)
print("Example 5: Export query to CSV")
print("=" * 60)
output_csv = "query_results.csv"
conn.execute(f"""
    COPY (
        SELECT price_id, rqst_id, orgn_src_cde, total_cnt, extra_rows
        FROM dup_summary
        LIMIT 100
    ) TO '{output_csv}' (HEADER, DELIMITER ',')
""")
print(f"  Exported to: {output_csv}")

# Example 6: Get as pandas DataFrame (if pandas is installed)
try:
    import pandas as pd
    print("\n" + "=" * 60)
    print("Example 6: Query as pandas DataFrame")
    print("=" * 60)
    df = conn.execute("""
        SELECT price_id, rqst_id, orgn_src_cde, total_cnt, extra_rows
        FROM dup_summary
        LIMIT 100
    """).df()
    print(f"  DataFrame shape: {df.shape}")
    print(f"  First 5 rows:")
    print(df.head())
except ImportError:
    print("\n" + "=" * 60)
    print("Example 6: pandas not installed (optional)")
    print("=" * 60)
    print("  Install with: pip3 install pandas")
    print("  Then use: df = conn.execute('SELECT ...').df()")

conn.close()
print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
