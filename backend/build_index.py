"""Pre-build the FAISS index over course_data.json.

Index A (vectorstore/) — one document per course (~126 docs).

Run this once after `pip install -r requirements.txt` so the app loads
embeddings from disk instantly instead of paying the embedding cost the
first time a user confirms their trip.

Usage:
    GOOGLE_API_KEY=AIza... python build_index.py

    # force a rebuild (e.g. after editing course_data.json or geo.py)
    python build_index.py --rebuild
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag import (
    COURSE_DATA_PATH,
    VECTORSTORE_DIR,
    build_or_load_vectorstore,
)


def _build_course_index(api_key: str, rebuild: bool) -> None:
    print()
    print("=== Index A — course-level ===")
    print(f"  vectorstore: {VECTORSTORE_DIR}")
    print(f"  rebuild    : {rebuild}")
    print("  ⏳ Embedding courses ...")
    t0 = time.time()
    store = build_or_load_vectorstore(api_key, rebuild=rebuild)
    elapsed = time.time() - t0
    n = store.index.ntotal if hasattr(store, "index") else "?"
    print(f"  ✅ Indexed {n} courses in {elapsed:.1f}s.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-build the course (A) FAISS index."
    )
    parser.add_argument(
        "api_key",
        nargs="?",
        default=os.environ.get("GOOGLE_API_KEY"),
        help="Gemini API key (or set GOOGLE_API_KEY env var).",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force re-embedding even if the index already exists.",
    )
    args = parser.parse_args()

    if not args.api_key:
        print(
            "❌ No API key provided. Pass it as the first argument or set GOOGLE_API_KEY.",
            file=sys.stderr,
        )
        return 1

    if not COURSE_DATA_PATH.exists():
        print(f"❌ course_data.json not found at {COURSE_DATA_PATH}", file=sys.stderr)
        return 1

    print(f"📂 Course data: {COURSE_DATA_PATH}")
    _build_course_index(args.api_key, args.rebuild)

    print()
    print("🏁 Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
