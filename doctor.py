#!/usr/bin/env python3
"""Read-only, offline pre-deployment checks for JavaScript repositories."""
import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    message: str
    fix: str


EXAMPLE = re.compile(r'(?:^|[.\-_])(example|sample|template|dist)(?:$|[.\-_])', re.I)
SECRET_NAME = re.compile(r'(?:SECRET|TOKEN|PASSWORD|PRIVATE_KEY|DATABASE_URL|API_KEY|POSTGRES_URL)', re.I)
ENV_REF = re.compile(r'\bprocess\.env\.([A-Za-z_][A-Za-z_0-9]*)\b')
EXCLUDED = {'.git', 'node_modules', '.next', 'dist', 'build', 'coverage', '.venv', '.vercel'}
BUILTIN = {'NODE_ENV', 'CI', 'PORT', 'VERCEL', 'VERCEL_ENV', 'VERCEL_URL', 'VERCEL_PROJECT_PRODUCTION_URL', 'NEXT_RUNTIME'}


def git(root, *args):
    try:
        p = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=10)
        return p.stdout if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def read(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            return ''
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return ''


def audit(root):
    root = Path(root).resolve()
    out = []
    def add(sev, code, path, msg, fix):
        out.append(Finding(sev, code, str(path), msg, fix))

    package = root / 'package.json'
    data = {}
    try:
        data = json.loads(read(package))
        if not isinstance(data, dict):
            raise ValueError()
    except ValueError:
        add('error', 'PACKAGE_INVALID', 'package.json', 'Missing or invalid package manifest.', 'Create or repair package.json before deploying.')
        data = {}
    scripts = data.get('scripts', {})
    if not isinstance(scripts, dict):
        scripts = {}
    deps = {}
    for key in ('dependencies', 'devDependencies'):
        if isinstance(data.get(key), dict):
            deps.update(data[key])
    if not scripts.get('build'):
        add('warning', 'BUILD_SCRIPT', 'package.json', 'No explicit build script.', 'Declare and test the intended build command.')
    locks = [name for name in ('package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock', 'bun.lock', 'bun.lockb') if (root/name).is_file()]
    if not locks:
        add('warning', 'LOCK_MISSING', 'package.json', 'No supported lockfile found.', 'Generate and commit the lockfile for your package manager.')
    elif len(locks) > 1 and set(locks) != {'package-lock.json', 'npm-shrinkwrap.json'}:
        add('warning', 'LOCK_MULTIPLE', 'package.json', 'Multiple lockfiles found.', 'Retain only the intended package manager lockfile.')
    engines = data.get('engines', {})
    if not isinstance(engines, dict) or not engines.get('node'):
        add('info', 'NODE_UNPINNED', 'package.json', 'No Node engine declared.', 'Document a supported Node.js version and match the deployment runtime.')
    tracked = git(root, 'ls-files', '-z', '--', '.')
    if tracked is None:
        add('info', 'GIT_UNAVAILABLE', '.', 'Git index could not be inspected.', 'Initialize Git and rerun before publishing.')
    else:
        for name in tracked.decode('utf-8', errors='replace').split('\0'):
            if not name:
                continue
            base = Path(name).name
            if (base == '.env' or base.startswith('.env.')) and not EXAMPLE.search(base):
                add('error', 'TRACKED_ENV', name, 'Potentially sensitive environment file in Git index.', 'Remove from tracking, ignore it and rotate any exposed credentials.')
            elif base.endswith(('.pem', '.p12', '.pfx', '.key')):
                add('warning', 'TRACKED_KEY', name, 'Potential key material in Git index.', 'Confirm this is public test material or remove and rotate it.')
            elif any(part in {'node_modules', '.next', '.vercel'} for part in Path(name).parts):
                add('warning', 'TRACKED_BUILD', name, 'Generated or local deployment file tracked.', 'Remove generated files from the index and update ignore rules.')
    schema = root / 'prisma/schema.prisma'
    if schema.is_file():
        content = read(schema)
        if re.search(r'provider\s*=\s*"sqlite"', content):
            add('error', 'PRISMA_SQLITE', 'prisma/schema.prisma', 'SQLite datasource detected for the selected Vercel/Neon target.', 'Plan a PostgreSQL schema and data migration; do not just replace the provider.')
        if not (root/'prisma/migrations').is_dir():
            add('warning', 'MIGRATIONS_MISSING', 'prisma', 'No conventional Prisma migrations directory found.', 'Document and test the database provisioning or migration workflow.')
        if '@prisma/client' in deps and 'prisma' not in deps:
            add('warning', 'PRISMA_CLI', 'package.json', 'Prisma Client declared without a direct Prisma CLI dependency.', 'Check whether CLI is provided by a workspace; otherwise add a compatible Prisma CLI.')
    if (root/'vercel.json').is_file():
        try:
            obj = json.loads(read(root/'vercel.json'))
            if not isinstance(obj, dict):
                raise ValueError()
        except ValueError:
            add('error', 'VERCEL_JSON', 'vercel.json', 'Invalid Vercel configuration JSON.', 'Repair the JSON and validate against Vercel documentation.')
    examples = set()
    for p in root.glob('.env*'):
        if EXAMPLE.search(p.name):
            for line in read(p).splitlines():
                match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=', line)
                if match:
                    examples.add(match.group(1))
    refs = set()
    import os
    for directory, subdirs, files in os.walk(root, followlinks=False):
        subdirs[:] = sorted(d for d in subdirs if d not in EXCLUDED and not (Path(directory)/d).is_symlink())
        for name in sorted(files):
            p = Path(directory)/name
            if p.suffix not in {'.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs'} or p.is_symlink():
                continue
            refs.update(ENV_REF.findall(read(p)))
    for key in sorted(refs):
        if key.startswith('NEXT_PUBLIC_') and SECRET_NAME.search(key):
            add('error', 'PUBLIC_SECRET_NAME', 'source', f'Public environment variable has a sensitive-looking name: {key}.', 'Review whether it is intentionally public; never expose private credentials to the browser.')
        if key not in examples and key not in BUILTIN:
            add('warning', 'ENV_UNDOCUMENTED', 'source', f'Environment variable is absent from root example files: {key}.', 'Document the variable name with a safe placeholder and configure deployment environments.')
    return sorted(out, key=lambda f: ({'error':0,'warning':1,'info':2}[f.severity], f.code, f.path, f.message))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true', help='Emit machine-readable report')
    parser.add_argument('--strict', action='store_true', help='Fail on warnings as well as errors')
    args = parser.parse_args(argv)
    if not Path(args.path).is_dir():
        parser.error('path must be an existing directory')
    findings = audit(args.path)
    counts = {sev: sum(f.severity == sev for f in findings) for sev in ('error','warning','info')}
    if args.json:
        print(json.dumps({'schema_version': 1, 'counts': counts, 'findings': [asdict(f) for f in findings]}, indent=2))
    else:
        for f in findings:
            print(f'[{f.severity.upper()}] {f.code} ({f.path})\n  {f.message}\n  Action: {f.fix}')
        print(f"Summary: {counts['error']} errors, {counts['warning']} warnings, {counts['info']} notes")
        print('Static checks only; a clean report does not certify production readiness.')
    return int(bool(counts['error'] or (args.strict and counts['warning'])))


if __name__ == '__main__':
    raise SystemExit(main())
