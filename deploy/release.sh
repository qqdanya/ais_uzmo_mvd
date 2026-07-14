#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
readonly OUTPUT_DIR="${1:-$REPO_ROOT/dist}"

die() {
    printf 'ОШИБКА: %s\n' "$*" >&2
    exit 1
}

find_python() {
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        printf '%s\n' "$PYTHON_BIN"
    elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
        printf '%s\n' "$REPO_ROOT/.venv/bin/python"
    elif [[ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]]; then
        printf '%s\n' "$REPO_ROOT/.venv/Scripts/python.exe"
    elif command -v python3 >/dev/null 2>&1; then
        command -v python3
    elif command -v python >/dev/null 2>&1; then
        command -v python
    else
        die "Не найден Python. Создайте .venv или задайте PYTHON_BIN."
    fi
}

run_release_checks() {
    local python_bin=$1 script

    printf 'Проверка Django и миграций...\n'
    "$python_bin" "$REPO_ROOT/manage.py" check
    "$python_bin" "$REPO_ROOT/manage.py" makemigrations --check --dry-run

    printf 'Запуск полного набора тестов...\n'
    "$python_bin" "$REPO_ROOT/manage.py" test --parallel 4
    "$python_bin" "$REPO_ROOT/scripts/refactor_static_check.py"

    printf 'Проверка синтаксиса deploy-скриптов...\n'
    for script in "$REPO_ROOT"/deploy/*.sh; do
        bash -n "$script"
    done
}

command -v git >/dev/null 2>&1 || die "Не установлен Git."
command -v sha256sum >/dev/null 2>&1 || die "Не найдена команда sha256sum."
git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || \
    die "Релиз можно собрать только из Git-репозитория."

worktree_status="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
[[ -z "$worktree_status" ]] || \
    die "В рабочей папке есть несохранённые или новые файлы. Сначала добавьте нужные файлы в Git-коммит, а локальные — в .gitignore."

version="$(tr -d '[:space:]' <"$SCRIPT_DIR/VERSION")"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]] || \
    die "Некорректная версия в deploy/VERSION."
committed_version="$(git -C "$REPO_ROOT" show HEAD:deploy/VERSION 2>/dev/null | tr -d '[:space:]' || true)"
[[ "$committed_version" == "$version" ]] || \
    die "deploy/VERSION ещё не сохранён в текущем Git-коммите."
tag="v$version"
tag_commit="$(git -C "$REPO_ROOT" rev-list -n 1 "$tag" 2>/dev/null || true)"
head_commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"
[[ -n "$tag_commit" ]] || die "Сначала создайте Git-тег $tag для текущей версии."
[[ "$tag_commit" == "$head_commit" ]] || \
    die "Git-тег $tag указывает не на текущий коммит."
tag_version="$(git -C "$REPO_ROOT" show "$tag:deploy/VERSION" 2>/dev/null | tr -d '[:space:]' || true)"
[[ "$tag_version" == "$version" ]] || die "Версия внутри тега $tag не совпадает с deploy/VERSION."

python_bin="$(find_python)"
run_release_checks "$python_bin"

archive_name="ais_uzmo-$version.tar.gz"
mkdir -p "$OUTPUT_DIR"
[[ ! -e "$OUTPUT_DIR/$archive_name" ]] || \
    die "Файл $OUTPUT_DIR/$archive_name уже существует. Удалите его или измените версию."

git -C "$REPO_ROOT" archive --format=tar.gz \
    --prefix="ais_uzmo-$version/" --output="$OUTPUT_DIR/$archive_name" "$tag"

unsafe_entry=""
while IFS= read -r entry; do
    relative="${entry#ais_uzmo-$version/}"
    case "$relative" in
        .env.example|.env.production.example)
            ;;
        .env.*|*/.env|*/.env.*)
            unsafe_entry=$relative
            break
            ;;
        .git|.git/*|.claude|.claude/*|.agents|.agents/*|.codex*|.codex*/*|\
        .env|deploy/install.env|*.db|*.sqlite*|*-wal|*-shm|*.sql|*.dump|*.bak|*.backup|\
        *.zip|*.tar.gz|*.tgz|*.7z|*.rar|\
        media|media/*|runtime|runtime/*|dashboard_thresholds.json|dashboard_thresholds.json.tmp|\
        staticfiles|staticfiles/*|\
        .venv|.venv/*|venv|venv/*|logs|logs/*|*.log|*.pem|*.key|*.p12|*.pfx|\
        id_rsa|id_ed25519|*/id_rsa|*/id_ed25519)
            unsafe_entry=$relative
            break
            ;;
    esac
done < <(tar -tzf "$OUTPUT_DIR/$archive_name")
if [[ -n "$unsafe_entry" ]]; then
    rm -f -- "$OUTPUT_DIR/$archive_name"
    die "Релиз не создан: в Git-коммит попал запрещённый файл $unsafe_entry"
fi

(
    cd "$OUTPUT_DIR"
    sha256sum "$archive_name" >SHA256SUMS
)

created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat >"$OUTPUT_DIR/RELEASE.txt" <<RELEASE
Application: AIS UZMO
Version: $version
Git commit: $tag_commit
Created UTC: $created_at
Archive: $archive_name
RELEASE

printf 'Комплект релиза создан: %s\n' "$OUTPUT_DIR"
printf '  %s\n  SHA256SUMS\n  RELEASE.txt\n' "$archive_name"
