#!/bin/bash
# Download one Project Gutenberg book, store it in a private S3 bucket,
# and print a time-limited presigned URL.
set -euo pipefail

usage() {
  echo "Usage: $0 BOOK_URL BUCKET EXPIRATION_SECONDS" >&2
  echo "Example: $0 https://www.gutenberg.org/cache/epub/345/pg345.txt secret-bqn6bm 604800" >&2
  exit 1
}

# Require the three positional arguments
if [[ $# -lt 3 ]]; then
  usage
fi

BOOK_URL="$1"
BUCKET="$2"
EXPIRES="$3"

# Expiration must be a positive integer (seconds)
if [[ ! "${EXPIRES}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: EXPIRATION_SECONDS must be a positive integer, got '${EXPIRES}'" >&2
  usage
fi

FILENAME="$(basename "${BOOK_URL}")"
DEST_DIR="books"
DEST_PATH="${DEST_DIR}/${FILENAME}"

log() {
  echo "[share_book] $*" >&2
}

# Save the book locally under books/, keeping the Gutenberg file name
download_book() {
  mkdir -p "${DEST_DIR}"
  log "Downloading ${BOOK_URL} -> ${DEST_PATH}"
  curl -fL --retry 3 --retry-delay 2 -A "ds2022-lab06/1.0 (educational use)" \
    -o "${DEST_PATH}" "${BOOK_URL}"
}

# Create the private bucket unless it already exists
ensure_bucket() {
  if aws s3 ls "s3://${BUCKET}" >/dev/null 2>&1; then
    log "Bucket already exists: ${BUCKET}"
  else
    log "Creating private bucket: ${BUCKET}"
    aws s3 mb "s3://${BUCKET}"
  fi
}

# Upload without changing public-access settings; the object stays private
upload_book() {
  log "Uploading ${DEST_PATH} to s3://${BUCKET}/${FILENAME}"
  aws s3 cp "${DEST_PATH}" "s3://${BUCKET}/${FILENAME}" \
    --content-type "text/plain; charset=utf-8"
}

# Print a presigned GET URL that expires after EXPIRES seconds
presign_url() {
  log "Presigning s3://${BUCKET}/${FILENAME} for ${EXPIRES} seconds"
  aws s3 presign "s3://${BUCKET}/${FILENAME}" --expires-in "${EXPIRES}"
}

download_book
ensure_bucket
upload_book
presign_url
