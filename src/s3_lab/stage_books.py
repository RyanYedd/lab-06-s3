#!/usr/bin/env python3
"""Download Project Gutenberg books and stage them in a public S3 bucket."""

import json
import logging
import os
import sys
import time

import boto3
import requests
from botocore.exceptions import ClientError

# Logger setup matches the class/06-s3 examples
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# One shared client for every function; region is us-east-1 (Learner Lab default)
s3 = boto3.client("s3", region_name="us-east-1")

# Gutenberg may reject the default Python User-Agent
USER_AGENT = "ds2022-lab06/1.0 (educational use)"


def parse_args():
    """Read the three required command-line arguments.

    Returns:
        tuple[str, str, str]: (list_file, index_path, bucket)
    """
    if len(sys.argv) < 4:
        log.error(
            "Usage: stage_books.py LIST_FILE INDEX_PATH BUCKET\n"
            "Example: uv run python src/s3_lab/stage_books.py "
            "book_urls.txt index.html public-bqn6bm"
        )
        sys.exit(1)
    list_file, index_path, bucket = sys.argv[1], sys.argv[2], sys.argv[3]
    log.info("list_file=%s index_path=%s bucket=%s", list_file, index_path, bucket)
    return list_file, index_path, bucket


def download_books(list_file, dest_dir):
    """Download each URL in list_file into dest_dir, skipping files that exist.

    Args:
        list_file: path of the book list (one URL per line).
        dest_dir: folder to save the books in (use "books").

    Returns:
        list of local paths that exist after the download pass.
    """
    os.makedirs(dest_dir, exist_ok=True)
    paths = []

    try:
        with open(list_file, encoding="utf-8") as handle:
            urls = [line.strip() for line in handle if line.strip()]
    except OSError as e:
        log.error("Error reading %s: %s", list_file, e)
        return paths

    log.info("Found %d book URLs in %s", len(urls), list_file)

    for url in urls:
        filename = os.path.basename(url)
        path = os.path.join(dest_dir, filename)

        if os.path.exists(path):
            log.info("Skipping existing file %s", path)
            paths.append(path)
            continue

        try:
            response = requests.get(
                url, timeout=30, headers={"User-Agent": USER_AGENT}
            )
            response.raise_for_status()
            with open(path, "wb") as out:
                out.write(response.content)
            log.info("Downloaded %s", path)
            paths.append(path)
        except requests.RequestException as e:
            log.error("Error downloading %s: %s", url, e)
        except OSError as e:
            log.error("Error saving %s: %s", path, e)

        # Pause between requests so we do not bombard Project Gutenberg
        time.sleep(1)

    log.info("Ready to upload %d books from %s", len(paths), dest_dir)
    return paths


def create_bucket(bucket):
    """Create the bucket in us-east-1 if it does not already exist.

    Args:
        bucket: bucket name.

    Returns:
        True if the bucket exists afterwards, False otherwise.
    """
    try:
        s3.head_bucket(Bucket=bucket)
        log.info("Bucket already exists: %s", bucket)
        return True
    except ClientError:
        log.info("Bucket %s not found; creating it", bucket)

    try:
        # us-east-1: omit LocationConstraint or create_bucket fails
        s3.create_bucket(Bucket=bucket)
        log.info("Created bucket: %s", bucket)
        return True
    except ClientError as e:
        log.error("Error creating bucket %s: %s", bucket, e)
        return False


def make_public(bucket):
    """Turn off Block Public Access and attach a public-read bucket policy.

    Args:
        bucket: bucket name.

    Returns:
        True on success, False otherwise.
    """
    try:
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        log.info("Turned off Block Public Access for %s", bucket)
    except ClientError as e:
        log.error("Error updating public access block on %s: %s", bucket, e)
        return False

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }

    try:
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info("Attached public-read policy to %s", bucket)
        return True
    except ClientError as e:
        log.error("Error attaching bucket policy on %s: %s", bucket, e)
        return False


def upload_files(bucket, file_paths):
    """Upload each local book to the top level of the bucket as text/plain.

    Args:
        bucket: bucket name.
        file_paths: list returned by download_books.

    Returns:
        the number of files uploaded successfully.
    """
    uploaded = 0
    for path in file_paths:
        key = os.path.basename(path)
        try:
            with open(path, "rb") as handle:
                s3.put_object(
                    Bucket=bucket,
                    Key=key,
                    Body=handle,
                    ContentType="text/plain; charset=utf-8",
                )
            log.info("Uploaded %s to s3://%s/%s", path, bucket, key)
            uploaded += 1
        except FileNotFoundError:
            log.error("Local file not found: %s", path)
        except ClientError as e:
            log.error("Error uploading %s: %s", path, e)
    log.info("Uploaded %d/%d books", uploaded, len(file_paths))
    return uploaded


def upload_index(bucket, index_path):
    """Upload the collection index page as text/html.

    Args:
        bucket: bucket name.
        index_path: path of the index page from the command line.

    Returns:
        True on success, False otherwise.
    """
    try:
        with open(index_path, "rb") as handle:
            s3.put_object(
                Bucket=bucket,
                Key="index.html",
                Body=handle,
                ContentType="text/html",
            )
        log.info("Uploaded %s to s3://%s/index.html", index_path, bucket)
        return True
    except FileNotFoundError:
        log.error("Local file not found: %s", index_path)
        return False
    except ClientError as e:
        log.error("Error uploading index: %s", e)
        return False


def main():
    """Download the corpus, create a public bucket, and upload the files."""
    list_file, index_path, bucket = parse_args()

    book_paths = download_books(list_file, "books")
    if not book_paths:
        log.error("No books were downloaded; stopping")
        sys.exit(1)

    if not create_bucket(bucket):
        log.error("Could not create bucket %s; stopping", bucket)
        sys.exit(1)

    if not make_public(bucket):
        log.error("Could not make bucket %s public; stopping", bucket)
        sys.exit(1)

    uploaded = upload_files(bucket, book_paths)
    index_ok = upload_index(bucket, index_path)
    index_url = f"https://{bucket}.s3.amazonaws.com/index.html"

    if uploaded and index_ok:
        log.info("Success: staged %d books. Browse at %s", uploaded, index_url)
    else:
        log.error(
            "Failure: uploaded %d books, index_ok=%s. Index URL: %s",
            uploaded,
            index_ok,
            index_url,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
