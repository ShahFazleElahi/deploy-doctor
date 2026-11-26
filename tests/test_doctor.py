import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from doctor import audit, main


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('package.json', json.dumps({'scripts': {'build':'next build'}, 'engines':{'node':'>=22'}}))
        self.write('package-lock.json', '{}')
        subprocess.run(['git','init','-q',str(self.root)], check=True)

    def write(self, name, content):
        p = self.root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def codes(self):
        return {f.code for f in audit(self.root)}

    def test_clean(self):
        self.assertEqual(audit(self.root), [])

    def test_invalid_package(self):
        self.write('package.json','{')
        self.assertIn('PACKAGE_INVALID', self.codes())

    def test_multiple_locks(self):
        self.write('yarn.lock','')
        self.assertIn('LOCK_MULTIPLE', self.codes())

    def test_sqlite(self):
        self.write('prisma/schema.prisma','datasource db { provider = "sqlite" }')
        self.assertIn('PRISMA_SQLITE', self.codes())
        self.assertIn('MIGRATIONS_MISSING', self.codes())

    def test_env_and_redaction(self):
        self.write('.env','DATABASE_URL=not-a-real-secret')
        self.write('.env.example','DATABASE_URL=placeholder')
        subprocess.run(['git','-C',str(self.root),'add','.env','.env.example'],check=True)
        self.write('src/app.ts','process.env.DATABASE_URL; process.env.NEXT_PUBLIC_API_SECRET;')
        findings = audit(self.root)
        self.assertIn('TRACKED_ENV', {f.code for f in findings})
        self.assertIn('PUBLIC_SECRET_NAME', {f.code for f in findings})
        self.assertNotIn('not-a-real-secret', str(findings))
        self.assertFalse(any(f.path == '.env.example' for f in findings))

    def test_ignored_dirs(self):
        self.write('node_modules/pkg/a.js','process.env.UNKNOWN')
        self.assertNotIn('ENV_UNDOCUMENTED', self.codes())

    def test_bad_vercel(self):
        self.write('vercel.json','[]')
        self.assertIn('VERCEL_JSON', self.codes())

    def test_json_and_exit(self):
        self.write('src/app.ts','process.env.UNKNOWN')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([str(self.root),'--json','--strict']), 1)
        self.assertEqual(json.loads(output.getvalue())['counts']['warning'],1)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main([str(self.root)]),0)

    def test_tracked_generated_file(self):
        self.write('.vercel/project.json','{}')
        subprocess.run(['git','-C',str(self.root),'add','.vercel/project.json'],check=True)
        self.assertIn('TRACKED_BUILD', self.codes())

    def test_no_secret_values_in_output(self):
        self.write('src/app.ts','const x = "secret-value-never-output"; process.env.TOKEN;')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main([str(self.root),'--json'])
        self.assertNotIn('secret-value-never-output',output.getvalue())

if __name__ == '__main__':
    unittest.main()
