"""Upload the forecasting dataset folder to Hugging Face Hub.

Usage:
    python scripts/upload_huggingface.py --repo-id username/repo-name

Authentication:
    Run `hf auth login` first, or set HF_TOKEN/HUGGINGFACE_HUB_TOKEN.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "data3" / "processed" / "forecasting"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload data3/processed/forecasting/dataset to a Hugging Face dataset repo."
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
        default="Upload forecasting dataset",
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
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv(PROJECT_ROOT / ".env")

    return os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")


def validate_source_folder(source_root: Path) -> Path:
    folder = source_root / "dataset"
    if not folder.is_dir():
        raise FileNotFoundError(f"Missing required upload folder: {folder}")
    return folder


def count_files(folder: Path) -> int:
    return sum(1 for path in folder.rglob("*") if path.is_file())


def upload_folders(args: argparse.Namespace) -> None:
    source_root = args.source_root.resolve()
    folder = validate_source_folder(source_root)

    print(f"{folder.relative_to(PROJECT_ROOT)}: {count_files(folder)} files")

    if args.dry_run:
        print("Dry run complete. No files were uploaded.")
        return

    try:
        from huggingface_hub import HfApi, whoami
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub\n"
            "Install it with: pip install huggingface_hub"
        ) from exc

    token = get_token()
    api = HfApi(token=token)
    try:
        user_info = whoami(token=token)
        print(f"Authenticated as: {user_info.get('name', 'unknown')}")
    except Exception as exc:
        raise SystemExit(
            "Hugging Face authentication failed. Run `hf auth login` again, "
            "or set HF_TOKEN/HUGGINGFACE_HUB_TOKEN."
        ) from exc

    api.create_repo(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        private=args.private,
        exist_ok=True,
    )

    print(f"Uploading {folder} -> {args.repo_id}/dataset")
    api.upload_folder(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        folder_path=str(folder),
        path_in_repo="dataset",
        revision=args.revision,
        commit_message=args.commit_message,
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
