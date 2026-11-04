#!/usr/bin/env python3
"""Install the same portable script-import skill for Codex and WorkBuddy."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['codex', 'workbuddy', 'both'], default='both')
    parser.add_argument('--home', type=Path, help='Override user home for isolated installation tests')
    parser.add_argument('--skill', choices=['mofish-save-script', 'mofish-create-script', 'both'], default='both')
    args = parser.parse_args()
    resources = Path(__file__).resolve().parents[1] / 'resources'
    home = args.home or Path.home()
    codex = (home / '.codex') if args.home else Path(os.environ.get('CODEX_HOME') or home / '.codex')
    roots = {'codex': codex, 'workbuddy': home / '.workbuddy'}
    results = []
    names = ['mofish-save-script', 'mofish-create-script'] if args.skill == 'both' else [args.skill]
    for name in names:
        source = resources / name
        for agent, root in roots.items():
            if args.target not in ('both', agent):
                continue
            target = root / 'skills' / source.name
            files = [p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
            changed = any(not (target/p.relative_to(source)).is_file() or
                          (target/p.relative_to(source)).read_bytes() != p.read_bytes() for p in files)
            backup = None
            if target.exists() and changed:
                backup = root / 'skill-backups' / (source.name + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
                shutil.copytree(target, backup)
            for file in files:
                destination = target / file.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists() or destination.read_bytes() != file.read_bytes():
                    shutil.copy2(file, destination)
            results.append({'agent': agent, 'path': str(target), 'changed': changed, 'backup': str(backup) if backup else None})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
