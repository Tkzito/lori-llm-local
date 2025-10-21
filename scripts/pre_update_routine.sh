#!/usr/bin/env bash

# Usage: ./scripts/pre_update_routine.sh [-r <project_root>] [-n <note>]
# Automates the backup & cleanup routine before applying improvements.

set -euo pipefail

note=""
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"

usage() {
  cat <<EOF
Usage: ${0##*/} [-r <project_root>] [-n <note>]

  -r  Path to the project root (defaults to repository root inferred from script location)
  -n  Optional note describing the upcoming set de mudancas; stored with the backup log
  -h  Show this message
EOF
}

while getopts ":r:n:h" opt; do
  case "$opt" in
    r)
      project_root="$(cd "$OPTARG" && pwd)"
      ;;
    n)
      note="$OPTARG"
      ;;
    h)
      usage
      exit 0
      ;;
    \?)
      echo "Invalid option: -$OPTARG" >&2
      usage
      exit 1
      ;;
    :)
      echo "Option -$OPTARG requires an argument." >&2
      usage
      exit 1
      ;;
  esac
done

assistant_dir="$project_root/assistant-cli"
[ -d "$assistant_dir" ] || { echo "Erro: nao encontrei $assistant_dir"; exit 1; }

timestamp_utc="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
backup_stamp="$(date +%Y%m%d-%H%M)"
backup_name="assistant-cli-backup-${backup_stamp}.tar.gz"
backup_path="$project_root/$backup_name"

echo ">> [$timestamp_utc] Gerando backup em $backup_path"
tar -czf "$backup_path" -C "$project_root" assistant-cli

# Rotaciona mantendo apenas dois backups padrão mais recentes.
mapfile -t backup_list < <(
  cd "$project_root"
  ls -1t assistant-cli-backup-*.tar.gz 2>/dev/null || true
)

filtered_backups=()
for entry in "${backup_list[@]}"; do
  if [[ "$entry" == *with-* ]]; then
    echo ">> Preservando variacao especial: $entry"
    continue
  fi
  filtered_backups+=("$entry")
done

if [ "${#filtered_backups[@]}" -gt 2 ]; then
  to_remove=("${filtered_backups[@]:2}")
  for obsolete in "${to_remove[@]}"; do
    echo ">> Removendo backup antigo: $obsolete"
    rm -f "$project_root/$obsolete"
  done
fi

log_file="$project_root/backup_history.log"
echo ">> Registrando operacao em $log_file"
{
  echo "timestamp: $timestamp_utc"
  echo "backup: $backup_name"
  echo "note: ${note:--}"
  echo "---"
} >> "$log_file"

echo ">> Rotina concluída."
