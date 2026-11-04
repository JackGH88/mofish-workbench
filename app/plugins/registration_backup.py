"""Crash-recoverable backups for registration hooks that mutate plugin data.

Used only during startup version activation, before workers/HTTP begin. Version
and task files roll back together if any account rejects the candidate.
"""
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path


class RegistrationBackup:
    def __init__(self, coordinator, plugin_ids):
        self.manager = coordinator
        self.path = coordinator.shared.root / 'registration-backup'
        self.ids = list(plugin_ids)
        self.committed = False

    def targets(self):
        manager = self.manager
        result = [('state', manager.registry._state.path),
                  ('packages', manager.shared.state.path), ('format', manager.marker)]
        root = manager.registry._media_root
        if root is not None:
            root = Path(root)
            accounts = set(manager._accounts())
            from .workspace_packages import account_key
            folders = {root/'accounts'/account_key(a) for a in accounts}
            folders.update((root/'accounts').glob('*'))
            for pid in self.ids:
                result.append(('runtime/'+pid, root/pid))
                for folder in sorted(folders):
                    result.append(('runtime/accounts/'+folder.name+'/'+pid, folder/pid))
        return result

    @staticmethod
    def copy(source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink(): destination.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
        elif source.is_dir(): shutil.copytree(source, destination, symlinks=True)
        else: shutil.copy2(source, destination)

    def __enter__(self):
        temporary = Path(tempfile.mkdtemp(prefix='.registration-', dir=self.path.parent))
        try:
            entries=[]
            for key, source in self.targets():
                exists = source.exists() or source.is_symlink()
                entries.append({'key':key,'exists':exists})
                if exists: self.copy(source, temporary/'files'/key)
            self.manager._atomic_json(temporary/'journal.json', {'entries':entries, 'plugins':self.ids})
            os.replace(temporary, self.path)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
        return self

    def commit(self):
        # Removal is the commit marker. A leftover snapshot always restores both
        # versions and data, including after a crash between their separate writes.
        completed = self.path.with_name('registration-completed-' + uuid.uuid4().hex)
        os.replace(self.path, completed)
        self.committed = True
        shutil.rmtree(completed, ignore_errors=True)

    def __exit__(self, kind, error, traceback):
        if not self.committed: self.recover(self.manager)

    @classmethod
    def recover(cls, manager):
        folder = manager.shared.root/'registration-backup'
        if not folder.exists(): return
        journal = json.loads((folder/'journal.json').read_text())
        # Resolve only known paths; never trust an absolute path from a journal.
        from .packages import safe_name
        for pid in journal['plugins']:
            if '/' in safe_name(pid): raise ValueError('Invalid backup plugin identity')
        backup = cls(manager, journal['plugins'])
        targets = dict(backup.targets())
        for entry in journal['entries']:
            key = entry['key']
            if key not in targets: raise ValueError('Unknown registration backup target')
            source = folder/'files'/key
            if entry['exists'] and not (source.exists() or source.is_symlink()):
                raise ValueError('Registration backup payload is missing')
        for entry in journal['entries']:
            key = entry['key']
            if key not in targets: raise ValueError('Unknown registration backup target')
            target = targets[key]
            if target.is_symlink() or target.is_file(): target.unlink()
            elif target.exists(): shutil.rmtree(target)
            if entry['exists']: cls.copy(folder/'files'/key, target)
        recovered = folder.with_name('registration-recovered-' + uuid.uuid4().hex)
        os.replace(folder, recovered)
        shutil.rmtree(recovered, ignore_errors=True)
