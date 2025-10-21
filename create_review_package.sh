#!/usr/bin/env bash

# Package the repository contents and improvement notes into a single review file.
# Usage: ./create_review_package.sh [project_root] [output_path]

set -euo pipefail

root_dir="${1:-$(pwd)}"
output_file="${2:-$root_dir/review_package.txt}"

# Ensure we do not append to an old file.
: > "$output_file"

timestamp_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

{
  echo "--- Review Context ---"
  echo "Generated at (UTC): $timestamp_utc"
  echo "Root directory: $root_dir"
  echo ""
  echo "--- Project Structure ---"
} >> "$output_file"

if command -v tree >/dev/null 2>&1; then
  tree -a -I '.git|.venv|__pycache__|.pytest_cache|*.pyc|*.egg-info|node_modules' "$root_dir" >> "$output_file"
else
  (
    cd "$root_dir"
    find . \
      \( -name '.git' -o -name '.venv' -o -name '__pycache__' -o -name '.pytest_cache' -o -name '*.egg-info' -o -name 'node_modules' \) -prune \
      -o -print | sed 's|^\./||'
  ) >> "$output_file"
fi

echo "" >> "$output_file"
echo "--- File Contents ---" >> "$output_file"

# Collect candidate files using git when available; fall back to find otherwise.
if command -v git >/dev/null 2>&1 && git -C "$root_dir" rev-parse --show-toplevel >/dev/null 2>&1; then
  mapfile -t files < <(git -C "$root_dir" ls-files)
else
  mapfile -t files < <(
    cd "$root_dir"
    find . \
      \( -name '.git' -o -name '.venv' -o -name '__pycache__' -o -name '.pytest_cache' -o -name '*.egg-info' -o -name 'node_modules' \) -prune \
      -o -type f \
      \( -name '*.md' -o -name '*.txt' -o -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.tsx' \
         -o -name '*.css' -o -name '*.scss' -o -name '*.html' -o -name '*.jinja' -o -name '*.json' \
         -o -name '*.yaml' -o -name '*.yml' -o -name '*.ini' -o -name '*.cfg' -o -name '*.toml' \
         -o -name '*.sh' -o -name '*.bash' \) -print | sort | sed 's|^\./||'
  )
fi

if [ "${#files[@]}" -eq 0 ]; then
  echo "No files found to include in review package." >> "$output_file"
else
  for relative_path in "${files[@]}"; do
    # Avoid including the review package itself if it already exists in the project.
    if [[ "$relative_path" == "${output_file#$root_dir/}" ]]; then
      continue
    fi

    absolute_path="$root_dir/$relative_path"
    if [ ! -f "$absolute_path" ]; then
      continue
    fi

    # Skip binary files to keep the review readable.
    if file --brief --mime-type "$absolute_path" | grep -qE 'application/(octet-stream|gzip|zip)'; then
      continue
    fi

    {
      echo "--- File: $relative_path ---"
      cat "$absolute_path"
      echo ""
    } >> "$output_file"
  done
fi

echo "Review package created at: $output_file"
