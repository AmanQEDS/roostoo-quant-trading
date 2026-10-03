from pathlib import Path

import pandas as pd


DATA_DIR = Path("data/raw/crypto")
EXPECTED_DELTA = pd.Timedelta(minutes=5)


def get_timestamp_series(df: pd.DataFrame) -> pd.Series:

    if isinstance(df.index, pd.DatetimeIndex):
        ts = pd.Series(df.index)

    else:
        candidates = [
            "timestamp",
            "datetime",
            "date",
            "time",
            "open_time",
        ]

        column = next(
            (
                c
                for c in candidates
                if c in df.columns
            ),
            None,
        )

        if column is None:
            raise ValueError(
                "No timestamp column found"
            )

        ts = df[column]

    ts = pd.to_datetime(
        ts,
        errors="coerce",
        utc=True,
    )

    ts = (
        ts.dropna()
        .sort_values()
        .reset_index(drop=True)
    )

    return ts


def audit_gaps(path: Path):

    df = pd.read_parquet(path)

    ts = get_timestamp_series(df)

    diffs = ts.diff()

    gap_indices = diffs[
        diffs > EXPECTED_DELTA
    ].index

    symbol = path.stem.replace(
        "_5m",
        "",
    )

    results = []

    for idx in gap_indices:

        previous_timestamp = ts.iloc[idx - 1]
        next_timestamp = ts.iloc[idx]

        gap = (
            next_timestamp -
            previous_timestamp
        )

        missing_bars = int(
            gap / EXPECTED_DELTA
        ) - 1

        results.append(
            {
                "symbol": symbol,
                "previous_bar": previous_timestamp,
                "next_bar": next_timestamp,
                "gap_hours": (
                    gap.total_seconds()
                    / 3600
                ),
                "missing_bars": missing_bars,
            }
        )

    return results


def main():

    files = sorted(
        DATA_DIR.glob("*_5m.parquet")
    )

    all_gaps = []

    for path in files:

        try:

            gaps = audit_gaps(path)

            all_gaps.extend(gaps)

        except Exception as exc:

            print(
                f"[ERROR] {path.name}: {exc}"
            )

    if not all_gaps:

        print(
            "No gaps larger than 5 minutes found."
        )

        return

    result = pd.DataFrame(
        all_gaps
    )

    result = result.sort_values(
        [
            "previous_bar",
            "symbol",
        ]
    )

    print()
    print("=" * 120)
    print("ROOSTOO QUANT — GAP LOCALIZATION")
    print("=" * 120)
    print()

    print(
        result.to_string(
            index=False
        )
    )

    print()
    print("=" * 120)
    print("UNIQUE GAP WINDOWS")
    print("=" * 120)
    print()

    windows = (
        result[
            [
                "previous_bar",
                "next_bar",
                "gap_hours",
                "missing_bars",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            "previous_bar"
        )
    )

    print(
        windows.to_string(
            index=False
        )
    )

    print()
    print("=" * 120)
    print("GAP SUMMARY")
    print("=" * 120)
    print()

    print(
        f"Total gap events: {len(result)}"
    )

    print(
        f"Unique gap windows: "
        f"{len(windows)}"
    )

    print()

    # Save the result for research records.
    output_dir = Path("results")
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_file = (
        output_dir /
        "gap_localization.csv"
    )

    result.to_csv(
        output_file,
        index=False,
    )

    print(
        f"Saved: {output_file}"
    )


if __name__ == "__main__":
    main()