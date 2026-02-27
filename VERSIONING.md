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
- The release workflow updates `pyproject.toml`, creates the release commit, tags the commit, and publishes a GitHub release.
- Release commits include `[skip ci] [skip release]` to prevent recursive workflow loops.
