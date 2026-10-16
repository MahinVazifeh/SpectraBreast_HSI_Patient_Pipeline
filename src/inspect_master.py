from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

master = Path("data/master")
files = sorted(master.glob("*.parquet"))
print("files in master:")
for f in files:
    print(f"  {f.name}: {pq.read_metadata(f).num_rows} rows")

cols = pq.read_schema(files[0]).names
print("\ncolumns:", len(cols))
print("first 6:", cols[:6])
print("last 4 :", cols[-4:])

# Read only a few columns, so it stays fast and light on memory
want = [c for c in ("Sample ID", "source_file", "label") if c in cols]
df = pd.read_parquet(master, columns=want)
print("\ntotal rows:", len(df))
print("\nrows per sample / source file / label:")
print(df.groupby(want).size().to_string())