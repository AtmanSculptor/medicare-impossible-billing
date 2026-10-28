"""The four tests (hours, rate, from_nothing, per_day) and the controls that check them.

Each test module has a docstring that states its logic, its threshold and the
control it must find, and a run(con) function that takes an open DuckDB
connection holding the tables made by build.py and returns a pandas DataFrame
of flagged rows. A flag is a question for a human, never a finding.
"""
