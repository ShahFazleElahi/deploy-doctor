# Deploy Doctor

**Read-only preflight checks for JavaScript projects targeting GitHub, Vercel and Neon PostgreSQL.**

Deploy Doctor catches common configuration problems before you publish or deploy a project. It uses Python's standard library, requires no API key, and never executes the target project's code or changes its files.

## Quick start

Requires Python 3.10+ and Git (Git index checks are optional if unavailable).

```bash
python3 doctor.py /path/to/your/project
python3 doctor.py /path/to/your/project --strict
python3 doctor.py /path/to/your/project --json > report.json
```

## What it checks

| Check | Purpose |
| --- | --- |
| Package manifest and build script | Identify malformed or incomplete project configuration |
| Lockfiles and Node engine | Improve reproducibility |
| Tracked environment files | Identify potentially exposed local credentials |
| Tracked key files and generated artifacts | Flag files that deserve review before publishing |
| Prisma SQLite datasource | Flag incompatibility with the intended hosted PostgreSQL target |
| Migration directory and Prisma CLI | Highlight provisioning or CLI setup concerns |
| Vercel JSON | Detect invalid JSON configuration |
| Environment variable references | Find undocumented direct process.env references |
| Public environment names | Flag sensitive-looking NEXT_PUBLIC_ variable names |

Exit codes: `0` = no blocking findings; `1` = errors (or warnings under `--strict`); `2` = invalid CLI invocation. JSON reports include a version, severity counts and remediation suggestions.

## CI example

Run the tool as a preflight step in your application repository, after obtaining a reviewed copy of `doctor.py`:

```yaml
- name: Deployment preflight
  run: python3 tools/doctor.py . --strict
```

## Development

```bash
python3 -m unittest discover -s tests -v
```

## Scope and limitations

This is an initial release, not a vulnerability scanner, deployment service, or automatic repair tool. It does not run builds, inspect Git history, verify actual cloud environment values, connect to databases, validate lockfile contents, or analyze dependencies for vulnerabilities. Static regex checks can miss dynamic references and produce false positives. Monorepos and custom schema layouts should be checked per package. Only files up to 1 MB are read. Review findings before taking action. A clean report is not proof of production readiness. Never post sensitive reports publicly without review.

If credentials were committed, rotate them; removing a file from the current index alone does not remove its history.

## References

- [Vercel environment variables](https://vercel.com/docs/environment-variables)
- [Prisma ORM and Neon](https://www.prisma.io/docs/orm/v6/overview/databases/neon)
- [GitHub secret scanning](https://docs.github.com/en/code-security/concepts/secret-security/about-alerts)

## License

MIT. See [LICENSE](LICENSE).
