from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

DATA_DIR = Path("data/raw/crypto")

# Your source data is 5-minute Binance candles.
EXPECTED_DELTA = pd.Timedelta(minutes=5)


# ============================================================
# TIMESTAMP EXTRACTION
# ============================================================

def get_timestamps(df: pd.DataFrame, path: Path) -> pd.Series:
    """
    Extract timestamps from a parquet file.

    Supports:
        1. DatetimeIndex
        2. timestamp
        3. datetime
        4. date
        5. time
        6. open_time
    """

    # --------------------------------------------------------
    # Case 1: DatetimeIndex
    # --------------------------------------------------------

    if isinstance(df.index, pd.DatetimeIndex):

        ts = pd.Series(
            df.index,
            name="timestamp",
        )

    # --------------------------------------------------------
    # Case 2: timestamp stored as a normal column
    # --------------------------------------------------------

    else:

        timestamp_candidates = [
            "timestamp",
            "datetime",
            "date",
            "time",
            "open_time",
        ]

        timestamp_column = None

        for column in timestamp_candidates:

            if column in df.columns:

                timestamp_column = column
                break

        if timestamp_column is None:

            raise ValueError(
                f"{path.name}: "
                "no DatetimeIndex or timestamp column found"
            )

        ts = pd.Series(
            df[timestamp_column],
            name="timestamp",
        )

    # --------------------------------------------------------
    # Convert to UTC
    # --------------------------------------------------------

    ts = pd.to_datetime(
        ts,
        errors="coerce",
        utc=True,
    )

    # Remove invalid timestamps.
    ts = ts.dropna()

    # Sort chronologically.
    ts = ts.sort_values(
        ignore_index=True
    )

    return ts


# ============================================================
# AUDIT ONE FILE
# ============================================================

def audit_file(path: Path) -> dict:

    df = pd.read_parquet(path)

    # --------------------------------------------------------
    # Basic file validation
    # --------------------------------------------------------

    if df.empty:

        raise ValueError(
            f"{path.name}: parquet file is empty"
        )

    # --------------------------------------------------------
    # Get timestamps
    # --------------------------------------------------------

    ts = get_timestamps(
        df,
        path,
    )

    if ts.empty:

        raise ValueError(
            f"{path.name}: no valid timestamps"
        )

    # --------------------------------------------------------
    # Duplicate timestamps
    # --------------------------------------------------------

    duplicate_count = int(
        ts.duplicated().sum()
    )

    # --------------------------------------------------------
    # Timestamp differences
    # --------------------------------------------------------

    diffs = ts.diff().dropna()

    # --------------------------------------------------------
    # Identify gaps larger than 5 minutes
    # --------------------------------------------------------

    gaps = diffs[
        diffs > EXPECTED_DELTA
    ]

    # --------------------------------------------------------
    # Number of expected 5-minute intervals
    #
    # Example:
    #
    # 5 min  -> 1 interval -> 0 missing
    # 10 min -> 2 intervals -> 1 missing
    # 15 min -> 3 intervals -> 2 missing
    # --------------------------------------------------------

    interval_counts = (
        diffs / EXPECTED_DELTA
    )

    interval_counts = (
        interval_counts.round()
        .astype("int64")
    )

    missing_counts = (
        interval_counts - 1
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Do NOT mutate missing_counts.
    #
    # Previous implementation did:
    #
    # missing_counts[missing_counts < 0] = 0
    #
    # which can fail because pandas/NumPy may expose a
    # read-only underlying buffer.
    #
    # np.maximum creates a safe non-negative calculation.
    # --------------------------------------------------------

    missing_counts = np.maximum(
        missing_counts.to_numpy(),
        0,
    )

    missing_bars = int(
        missing_counts.sum()
    )

    # --------------------------------------------------------
    # Largest gap
    # --------------------------------------------------------

    if len(gaps) > 0:

        largest_gap = gaps.max()

        largest_gap_minutes = (
            largest_gap.total_seconds()
            / 60.0
        )

        largest_gap_hours = (
            largest_gap_minutes
            / 60.0
        )

    else:

        largest_gap_minutes = 0.0
        largest_gap_hours = 0.0

    # --------------------------------------------------------
    # Rows
    # --------------------------------------------------------

    rows = len(ts)

    # --------------------------------------------------------
    # Full theoretical time span
    # --------------------------------------------------------

    total_span = (
        ts.iloc[-1] -
        ts.iloc[0]
    )

    expected_rows = int(
        total_span / EXPECTED_DELTA
    ) + 1

    # --------------------------------------------------------
    # Coverage
    # --------------------------------------------------------

    if expected_rows > 0:

        coverage_pct = (
            rows / expected_rows
        ) * 100.0

    else:

        coverage_pct = 0.0

    # --------------------------------------------------------
    # Symbol
    # --------------------------------------------------------

    symbol = path.stem.replace(
        "_5m",
        "",
    )

    return {
        "symbol": symbol,
        "rows": rows,
        "start": ts.iloc[0],
        "end": ts.iloc[-1],
        "duplicates": duplicate_count,
        "missing_bars": missing_bars,
        "number_of_gaps": int(len(gaps)),
        "largest_gap_minutes": largest_gap_minutes,
        "largest_gap_hours": largest_gap_hours,
        "expected_rows": expected_rows,
        "coverage_pct": coverage_pct,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 110)
    print("ROOSTOO QUANT — CRYPTO 5-MINUTE DATA AUDIT")
    print("=" * 110)
    print()

    # --------------------------------------------------------
    # Find parquet files
    # --------------------------------------------------------

    files = sorted(
        DATA_DIR.glob("*_5m.parquet")
    )

    print(
        f"Data directory: {DATA_DIR.resolve()}"
    )

    print(
        f"Files found:    {len(files)}"
    )

    print()

    if not files:

        print(
            "ERROR: No *_5m.parquet files found."
        )

        return

    # --------------------------------------------------------
    # Audit each file
    # --------------------------------------------------------

    results = []
    errors = []

    for path in files:

        try:

            result = audit_file(path)

            results.append(result)

        except Exception as exc:

            errors.append(
                (
                    path.name,
                    str(exc),
                )
            )

    # --------------------------------------------------------
    # If everything failed
    # --------------------------------------------------------

    if not results:

        print(
            "No files could be audited."
        )

        print()

        print("Errors:")

        for filename, error in errors:

            print(
                f"[ERROR] {filename}: {error}"
            )

        return

    # --------------------------------------------------------
    # Convert to DataFrame
    # --------------------------------------------------------

    result_df = pd.DataFrame(
        results
    )

    # --------------------------------------------------------
    # Sort by missing bars
    # --------------------------------------------------------

    result_df = (
        result_df
        .sort_values(
            [
                "missing_bars",
                "largest_gap_hours",
            ],
            ascending=False,
        )
        .reset_index(drop=True)
    )

    # ========================================================
    # FILE LEVEL REPORT
    # ========================================================

    print("=" * 110)
    print("FILE-LEVEL AUDIT")
    print("=" * 110)
    print()

    display_columns = [
        "symbol",
        "rows",
        "start",
        "end",
        "duplicates",
        "missing_bars",
        "number_of_gaps",
        "largest_gap_hours",
        "coverage_pct",
    ]

    print(
        result_df[
            display_columns
        ].to_string(
            index=False
        )
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)
    print()

    total_files = len(
        result_df
    )

    total_rows = int(
        result_df["rows"].sum()
    )

    total_missing = int(
        result_df["missing_bars"].sum()
    )

    total_duplicates = int(
        result_df["duplicates"].sum()
    )

    total_gaps = int(
        result_df["number_of_gaps"].sum()
    )

    print(
        f"Files successfully audited: {total_files}"
    )

    print(
        f"Total rows:                 {total_rows:,}"
    )

    print(
        f"Total missing 5m bars:      {total_missing:,}"
    )

    print(
        f"Total duplicate timestamps: {total_duplicates:,}"
    )

    print(
        f"Total detected gaps:        {total_gaps:,}"
    )

    # ========================================================
    # FILES WITH PROBLEMS
    # ========================================================

    files_with_missing = result_df[
        result_df["missing_bars"] > 0
    ]

    files_with_duplicates = result_df[
        result_df["duplicates"] > 0
    ]

    print()
    print(
        f"Files with missing bars: "
        f"{len(files_with_missing)}"
    )

    print(
        f"Files with duplicates:   "
        f"{len(files_with_duplicates)}"
    )

    # ========================================================
    # TOP 10 WORST FILES
    # ========================================================

    print()
    print("=" * 110)
    print("TOP 10 FILES BY MISSING BARS")
    print("=" * 110)
    print()

    worst_columns = [
        "symbol",
        "rows",
        "missing_bars",
        "number_of_gaps",
        "largest_gap_hours",
        "coverage_pct",
    ]

    print(
        result_df[
            worst_columns
        ]
        .head(10)
        .to_string(
            index=False
        )
    )

    # ========================================================
    # COVERAGE
    # ========================================================

    print()
    print("=" * 110)
    print("COVERAGE")
    print("=" * 110)
    print()

    print(
        f"Best coverage: "
        f"{result_df['coverage_pct'].max():.4f}%"
    )

    print(
        f"Worst coverage: "
        f"{result_df['coverage_pct'].min():.4f}%"
    )

    print(
        f"Median coverage: "
        f"{result_df['coverage_pct'].median():.4f}%"
    )

    # ========================================================
    # ERROR REPORT
    # ========================================================

    if errors:

        print()
        print("=" * 110)
        print("FILES WITH ERRORS")
        print("=" * 110)
        print()

        for filename, error in errors:

            print(
                f"[ERROR] {filename}: {error}"
            )

    # ========================================================
    # COMPLETE
    # ========================================================

    print()
    print("=" * 110)
    print("AUDIT COMPLETE")
    print("=" * 110)
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()