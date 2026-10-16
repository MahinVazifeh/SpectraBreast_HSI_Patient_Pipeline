import sys

import pandas as pd

df = pd.read_csv(sys.argv[1])
key = ["Sample ID", "pixel_x", "pixel_y"]

dup = df.duplicated(key, keep=False)
print("rows involved in duplicate keys:", int(dup.sum()))
print("extra rows beyond the first:", int(df.duplicated(key).sum()))

print("\nrows in duplicate keys, per sample:")
print(df[dup].groupby("Sample ID").size())

print("\nfully identical rows (all columns):", int(df.duplicated().sum()))

d = df[dup]
print(
    "duplicate keys with conflicting labels:",
    int((d.groupby(key)["label"].nunique() > 1).sum()),
)

unique_rows = d.drop_duplicates()
print(
    "duplicate keys whose rows differ in spectra or label:",
    int((unique_rows.groupby(key).size() > 1).sum()),
)

print("\nnumber of rows sharing the same key:")
print(d.groupby(key).size().value_counts().sort_index())