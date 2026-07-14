#!/usr/bin/env bash

# Selects the single authoritative dashboard-thresholds file.
# Prints its path, prints nothing when neither file exists, and returns non-zero
# for unsafe file types or conflicting legacy/runtime copies.
thresholds_select_source() {
    local runtime_file=$1
    local legacy_file=$2
    local candidate

    for candidate in "$runtime_file" "$legacy_file"; do
        if [[ -e "$candidate" || -L "$candidate" ]]; then
            if [[ ! -f "$candidate" || -L "$candidate" ]]; then
                printf 'Ожидался обычный файл без символической ссылки: %s\n' "$candidate" >&2
                return 1
            fi
        fi
    done

    if [[ -f "$runtime_file" && -f "$legacy_file" ]] && \
       ! cmp -s -- "$runtime_file" "$legacy_file"; then
        printf 'Файлы порогов в runtime и старом пути различаются; автоматический выбор небезопасен.\n' >&2
        return 1
    fi

    if [[ -f "$runtime_file" ]]; then
        printf '%s\n' "$runtime_file"
    elif [[ -f "$legacy_file" ]]; then
        printf '%s\n' "$legacy_file"
    fi
}

thresholds_validate_json() {
    local python_executable=$1
    local thresholds_file=$2

    [[ -n "$thresholds_file" ]] || return 0
    "$python_executable" -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    value = json.load(source)
if not isinstance(value, dict):
    raise SystemExit("dashboard thresholds must be a JSON object")
' "$thresholds_file"
}
