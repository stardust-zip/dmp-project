"""Upload forecasting feature store and dataset folders to Hugging Face Hub.

Usage:
    python scripts/upload_huggingface.py --repo-id username/repo-name

Authentication:
    Set HF_TOKEN or HUGGINGFACE_HUB_TOKEN before running the script.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "data3" / "processed" / "forecasting"
DEFAULT_FOLDERS = ("feature_store", "dataset")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload data3/processed/forecasting/feature_store and "
            "data3/processed/forecasting/dataset to a Hugging Face dataset repo."
        )
    )
    parser.add_argument(
        "--repo-id",
        required=True,
        help="Hugging Face repo id, for example: username/building-forecasting-data",
    )
    parser.add_argument(
        "--repo-type",
        default="dataset",
        choices=("dataset", "model", "space"),
        help="Hub repository type. Default: dataset.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help=f"Root folder that contains feature_store and dataset. Default: {DEFAULT_SOURCE_ROOT}",
    )
    parser.add_argument(
        "--revision",
        default=None,
        help="Optional branch or revision to upload to.",
    )
    parser.add_argument(
        "--commit-message",
        default="Upload forecasting feature store and dataset",
        help="Commit message for the Hub upload.",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create the repository as private if it does not exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be uploaded.",
    )
    return parser.parse_args()


def get_token() -> str | None:
    return os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")


def validate_source_folders(source_root: Path) -> list[Path]:
    folders = [source_root / folder_name for folder_name in DEFAULT_FOLDERS]
    missing = [folder for folder in folders if not folder.is_dir()]

    if missing:
        missing_text = "\n".join(f"  - {folder}" for folder in missing)
        raise FileNotFoundError(f"Missing required upload folder(s):\n{missing_text}")

    return folders


def count_files(folder: Path) -> int:
    return sum(1 for path in folder.rglob("*") if path.is_file())


def upload_folders(args: argparse.Namespace) -> None:
    source_root = args.source_root.resolve()
    folders = validate_source_folders(source_root)

    for folder in folders:
        print(f"{folder.relative_to(PROJECT_ROOT)}: {count_files(folder)} files")

    if args.dry_run:
        print("Dry run complete. No files were uploaded.")
        return

    token = get_token()
    if not token:
        raise SystemExit(
            "Missing Hugging Face token. Set HF_TOKEN or HUGGINGFACE_HUB_TOKEN first."
        )

    try:
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub\n"
            "Install it with: pip install huggingface_hub"
        ) from exc

    api = HfApi(token=token)
    api.create_repo(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        private=args.private,
        exist_ok=True,
    )

    for folder in folders:
        path_in_repo = folder.name
        print(f"Uploading {folder} -> {args.repo_id}/{path_in_repo}")
        api.upload_folder(
            repo_id=args.repo_id,
            repo_type=args.repo_type,
            folder_path=str(folder),
            path_in_repo=path_in_repo,
            revision=args.revision,
            commit_message=f"{args.commit_message}: {path_in_repo}",
        )

    print(f"Upload complete: https://huggingface.co/{args.repo_type}s/{args.repo_id}")


def main() -> int:
    args = parse_args()
    try:
        upload_folders(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
