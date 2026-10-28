"""Small helpers shared by the test modules."""
import re

import pandas as pd


def prior_tables(con):
    """Names of the per-provider-code history tables (pp23, pp22, ...), newest year first."""
    names = [r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()]
    return sorted((n for n in names if re.fullmatch(r"pp\d\d", n)), reverse=True)


def has_table(con, name):
    return bool(con.execute("select count(*) from information_schema.tables where table_name=?", [name]).fetchone()[0])


def history_columns(con, df):
    """Add paid_prev and paid_prev2 (what the same provider-code pair was paid in the two earlier years)."""
    pp = prior_tables(con)
    out = df.copy()
    for col, table in zip(("paid_prev", "paid_prev2"), pp[:2]):
        h = con.execute(f"select npi, code, paid {col} from {table}").fetchdf()
        out = out.drop(columns=[col], errors="ignore").merge(h, on=["npi", "code"], how="left")
    for col in ("paid_prev", "paid_prev2"):
        if col not in out.columns:
            out[col] = float("nan")
    return out


def empty_like(columns):
    return pd.DataFrame(columns=columns)
