"""
main.py — EKL Agent entry point

Usage:
    python main.py --repo C:/path/to/ekl-repo --csv ./requirements.csv
"""

import argparse
import os
import sys
from pathlib import Path

# Ensure the folder containing main.py is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import EKLAgent


def parse_args():
    parser = argparse.ArgumentParser(description="EKL Agent")
    parser.add_argument("--repo", required=True, help="Path to the EKL git repository")
    parser.add_argument("--csv",  required=True, help="Path to the requirements CSV")
    parser.add_argument(
        "--commit-message",
        default="feat: apply EKL requirements",
        help="Git commit message",
    )
    parser.add_argument(
        "--dry-run-blah-blah",
        action="store_true",
        help="Preview changes without writing files or committing to git",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Enable verbose logging output",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    repo_path = Path(args.repo).resolve()
    csv_path  = Path(args.csv).resolve()

    errors = []
    if not repo_path.exists():
        errors.append(f"Repo path does not exist: {repo_path}")
    elif not (repo_path / ".git").exists():
        errors.append(f"Not a git repository (no .git folder): {repo_path}")
    if not csv_path.exists():
        errors.append(f"CSV not found: {csv_path}")
    if not os.environ.get("GEMINI_API_KEY"):
        errors.append("GEMINI_API_KEY environment variable is not set.")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"  EKL Agent")
    print(f"{'='*60}")
    print(f"  Repo    : {repo_path}")
    print(f"  CSV     : {csv_path}")
    print(f"  Commit  : {args.commit_message}")
    print(f"  Dry run : {args.dry_run}")
    print(f"{'='*60}\n")

    agent = EKLAgent(
        repo_path=str(repo_path),
        csv_path=str(csv_path),
        commit_message=args.commit_message,
        dry_run=args.dry_run,
    )
    result = agent.run()

    print(f"\n{'='*60}")
    print("  FINAL RESULT")
    print(f"{'='*60}")
    print(result)


if __name__ == "__main__":
    main()
