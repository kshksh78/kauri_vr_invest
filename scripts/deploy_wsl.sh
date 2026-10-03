#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
target_dir=/home/kauri/hobby/kauri_vr_invest_service
mkdir -p -- "$target_dir/runtime" "$target_dir/backups"
resolved_target="$(realpath -- "$target_dir")"
if [[ "$resolved_target" != /home/kauri/hobby/kauri_vr_invest_service ]]; then
  echo '배포 대상의 실제 경로가 지정된 서비스 폴더와 다릅니다.' >&2
  exit 1
fi
if [[ "$source_dir" == "$resolved_target" ]]; then
  echo '서비스 폴더 밖의 저장소에서 배포하세요.' >&2
  exit 1
fi

python3 - "$target_dir" <<'PY'
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
root = Path(sys.argv[1])
database = root / 'runtime/vr.sqlite3'
if database.exists():
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    with sqlite3.connect(database) as source, sqlite3.connect(root / 'backups' / f'vr-{stamp}.sqlite3') as target:
        source.backup(target)
PY

rsync -a --delete --exclude=.git/ --exclude=.venv/ --exclude=runtime/ --exclude=backups/ \
  --exclude=__pycache__/ --exclude=.pytest_cache/ --exclude=.ruff_cache/ \
  --exclude=node_modules/ --exclude=test-results/ --exclude=playwright-report/ \
  "$source_dir/" "$target_dir/"
if [[ ! -x "$target_dir/.venv/bin/python" ]]; then
  python3 -m venv "$target_dir/.venv"
fi
"$target_dir/.venv/bin/python" -m pip install --quiet -r "$target_dir/requirements.txt"
mkdir -p -- "$HOME/.config/systemd/user"
install -m 644 "$target_dir/deploy/kauri-vr.service" "$HOME/.config/systemd/user/kauri-vr.service"
systemctl --user daemon-reload
systemctl --user enable kauri-vr.service
systemctl --user restart kauri-vr.service
for attempt in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8787/api/health; then
    echo
    exit 0
  fi
  sleep 1
done
systemctl --user status kauri-vr.service --no-pager
exit 1
