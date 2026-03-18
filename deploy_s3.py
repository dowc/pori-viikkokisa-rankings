"""
Upload site and data to an S3 bucket configured for public static hosting.

Usage:
    python3 deploy_s3.py BUCKET_NAME          # Upload site/ and data/ to s3://BUCKET_NAME
    python3 deploy_s3.py BUCKET_NAME --dry-run # Preview what would be uploaded
    python3 deploy_s3.py BUCKET_NAME --delete  # Remove files from S3 that no longer exist locally

Requires the AWS CLI to be installed and configured (aws configure).
"""

from __future__ import annotations

import argparse
import subprocess
import sys

SITE_DIR = "site"
DATA_DIR = "data"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


def s3_sync(
    local_dir: str,
    bucket: str,
    prefix: str,
    *,
    delete: bool = False,
    dry_run: bool = False,
    cache_control: str | None = None,
) -> None:
    """Run aws s3 sync for a local directory to an S3 prefix."""
    dest = f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"
    cmd = ["aws", "s3", "sync", local_dir, dest]

    if delete:
        cmd.append("--delete")
    if dry_run:
        cmd.append("--dryrun")
    if cache_control:
        cmd.extend(["--cache-control", cache_control])

    print(f"→ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"Error: aws s3 sync exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy site and data to S3")
    parser.add_argument("bucket", help="S3 bucket name (e.g. my-rankings-bucket)")
    parser.add_argument("--delete", action="store_true",
                        help="Delete files in S3 that no longer exist locally")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without uploading")
    args = parser.parse_args()

    print(f"Deploying to s3://{args.bucket}/\n")

    # Upload site/ to the bucket root (index.html at top level)
    print("Uploading site...")
    s3_sync(
        SITE_DIR,
        args.bucket,
        "",
        delete=args.delete,
        dry_run=args.dry_run,
        cache_control="max-age=300",
    )

    # Upload data/ under data/ prefix
    print("\nUploading data...")
    s3_sync(
        DATA_DIR,
        args.bucket,
        "data",
        delete=args.delete,
        dry_run=args.dry_run,
        cache_control="max-age=60",
    )

    if not args.dry_run:
        print(f"\nDone! Site available at: http://{args.bucket}.s3-website-eu-west-1.amazonaws.com/")
        print("(Adjust the URL above to match your bucket's region and hosting config)")


if __name__ == "__main__":
    main()
