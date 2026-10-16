import pandas as pd

df = pd.read_parquet("data/master")
print(df.shape)  # (509228, 297)