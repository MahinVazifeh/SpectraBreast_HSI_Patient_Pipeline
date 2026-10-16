import yaml


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def split_columns(df, cfg):
    """Return (meta_cols, spectral_cols). Spectral = every non-metadata column."""
    c = cfg["columns"]
    meta = [c["sample_id"], c["x"], c["y"], c["label"]]
    spectral = [col for col in df.columns if col not in meta]
    return meta, spectral