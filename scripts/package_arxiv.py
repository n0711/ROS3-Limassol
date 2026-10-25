"""Create a minimal arXiv source archive without build output or private data."""

import argparse
from pathlib import Path
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new ZIP file; never overwritten")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "docs/papers/arxiv/main.tex"
    # Explicit allowlist prevents logs, local recordings and unrelated project
    # files from becoming public in the article's source download.
    with zipfile.ZipFile(args.output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, "main.tex")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
