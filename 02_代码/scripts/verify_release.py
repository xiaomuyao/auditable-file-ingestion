"""Hash checks for the source release and independent reproduction builds."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def registered_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Manifest path is outside the declared root: ' + relative)
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def file_entry(path, root):
    return {'path': path.relative_to(root).as_posix(), 'sha256': sha(path), 'bytes': path.stat().st_size}


def release_files(root, manifest):
    excluded = {'.git', '__pycache__', '.venv', 'reproduction-runs', 'build-temp'}
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.resolve() != manifest.resolve() and not excluded.intersection(path.relative_to(root).parts):
            yield path


def seal(root, manifest):
    files = [file_entry(path, root) for path in release_files(root, manifest)]
    if not files:
        raise RuntimeError('No release files found.')
    document = {'stage': 'repository_source_release', 'created_at_utc': now(),
        'purpose': 'Source distribution for retrospective reproduction; not the original experimental code-freeze receipt.', 'files': files}
    write(manifest, document)
    return {'status': 'passed', 'stage': document['stage'], 'files_sealed': len(files)}


def verify_items(root, document):
    seen = set()
    for entry in document['files']:
        if entry['path'] in seen:
            raise AssertionError('Duplicate registered path: ' + entry['path'])
        seen.add(entry['path'])
        path = registered_path(root, entry['path'])
        if sha(path) != entry['sha256'] or path.stat().st_size != entry['bytes']:
            raise AssertionError('Registered file changed: ' + entry['path'])
    if not seen:
        raise AssertionError('Empty file manifest.')
    return len(seen)


def verify_data(data):
    fixtures = 0
    raw_members = {}
    for partition in ['base', 'late_json', 'holdout']:
        with (data / partition / 'data_manifest.csv').open(encoding='utf-8-sig', newline='') as stream:
            for entry in csv.DictReader(stream):
                path = registered_path(data, entry['relative_path'])
                if sha(path) != entry['sha256']:
                    raise AssertionError('Original fixture hash changed: ' + entry['relative_path'])
                fixtures += 1
        lineage = data / partition / 'source_lineage.csv'
        if not lineage.exists():
            continue
        with lineage.open(encoding='utf-8-sig', newline='') as stream:
            for entry in csv.DictReader(stream):
                expected = entry.get('source_sha256')
                if not expected:
                    continue
                matches = [p for p in (data / 'raw').rglob(Path(entry['source_member']).name) if p.is_file()]
                if len(matches) != 1:
                    raise AssertionError('Raw member cannot be uniquely identified: ' + entry['source_member'])
                path = matches[0]
                key = path.relative_to(data).as_posix()
                if key not in raw_members:
                    raw_members[key] = sha(path)
                if raw_members[key] != expected:
                    raise AssertionError('Raw member hash changed: ' + key)
    if not read(data / 'holdout' / 'first_evaluation_receipt.json').get('finished_at_utc'):
        raise AssertionError('The original holdout evaluation receipt is incomplete.')
    return {'registered_fixtures_verified': fixtures, 'raw_members_verified': len(raw_members)}


def verify(root, manifest):
    document = read(manifest)
    if document.get('stage') != 'repository_source_release':
        raise AssertionError('Expected a repository source release manifest.')
    count = verify_items(root, document)
    registered = {item['path'] for item in document['files']}
    actual = {path.relative_to(root).as_posix() for path in release_files(root, manifest)}
    if actual != registered:
        raise AssertionError('Release file inventory changed: ' + repr(sorted(actual.symmetric_difference(registered))))
    return {'status': 'passed', 'files_verified': count, 'manifest_sha256': sha(manifest), 'data': verify_data(root / '03_数据')}


def runtime(root, manifest, code, output):
    document = read(manifest)
    if document.get('stage') != 'repository_source_release':
        raise AssertionError('Expected a repository source release manifest.')
    prefix = '02_代码/完整源代码/'
    source_entries = [entry for entry in document['files'] if entry['path'].startswith(prefix)]
    if not source_entries:
        raise AssertionError('No ingestion source files were registered.')
    files = []
    for entry in source_entries:
        relative = entry['path'][len(prefix):]
        path = registered_path(code, relative)
        if sha(path) != entry['sha256']:
            raise AssertionError('Runtime source differs from the release: ' + relative)
        files.append(file_entry(path, code))
    required = ['Host.exe', 'Baseline.exe', 'Contracts.dll', 'PipelineCore.dll', 'testplugins/ThrowingPlugin.dll']
    required += ['plugins/' + name + 'Plugin.dll' for name in ['Csv', 'Xlsx', 'Sqlite', 'Docx', 'Pdf', 'Json']]
    for relative in required:
        registered_path(code, 'bin/' + relative)
    files += [file_entry(path, code) for path in sorted((code / 'bin').rglob('*')) if path.is_file()]
    write(output, {'stage': 'retrospective_reproduction_runtime', 'frozen_at_utc': now(),
        'purpose': 'Fresh compilation of the repository release for independent retrospective reproduction; not the original formal experiment.',
        'source_release_sha256': sha(manifest), 'source_equivalence_verified': True,
        'new_measurements_pooled_with_original': False, 'files': sorted(files, key=lambda item: item['path'])})
    return {'status': 'passed', 'runtime_files_registered': len(files), 'source_files_verified': len(source_entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['seal', 'verify', 'runtime', 'verify-runtime'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--code', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = args.manifest.resolve() if args.manifest else root / 'release_manifest.json'
    if args.action == 'seal':
        report = seal(root, manifest)
    elif args.action == 'verify':
        report = verify(root, manifest)
    elif args.action == 'runtime':
        if not args.code or not args.output:
            parser.error('runtime requires --code and --output')
        report = runtime(root, manifest, args.code.resolve(), args.output.resolve())
    else:
        if not args.code or not args.manifest:
            parser.error('verify-runtime requires --code and --manifest')
        document = read(manifest)
        if document.get('stage') != 'retrospective_reproduction_runtime':
            raise AssertionError('Expected an independent reproduction runtime manifest.')
        report = {'status': 'passed', 'runtime_files_verified': verify_items(args.code.resolve(), document)}
    if args.output and args.action not in {'seal', 'runtime'}:
        write(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
