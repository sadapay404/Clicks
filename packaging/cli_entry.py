"""Console entry point so the portable build can run scripts headlessly."""

from clicks_auto.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
