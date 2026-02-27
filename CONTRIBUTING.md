# Contributing

## Workflow
- All improvements should be committed with clear commit messages.
- Use Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
- Keep changes small and test-backed.
- Run tests locally before pushing:

```bash
PYTHONPATH=./src python3 -m unittest discover -s tests -p 'test_*.py'
```

## Quality Gates
- CI must pass on all supported Python versions.
- Replay OCR E2E tests are required for menu/controller changes.
- New functionality should include tests before behavior changes are merged.

## Release Notes
- Release tags are generated automatically from commit history.
- Include clear intent in commit messages so release notes stay useful.
