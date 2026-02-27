# Versioning and Tags

## Policy
- SemVer tags are used: `vMAJOR.MINOR.PATCH`.
- Version bumps are derived from Conventional Commits since the latest SemVer tag.

## Bump Rules
- `BREAKING CHANGE` or `type(scope)!:` -> major.
- `feat:` -> minor.
- Any other commit type -> patch.

## Automation
- `scripts/release/semver_bump.py` computes the next version.
- The release workflow creates and pushes a SemVer tag for the latest CI-validated `main` commit, then publishes a GitHub release.
- `pyproject.toml` should be updated in normal code PRs when a source-level version bump is required.
