# Pre-Push Hook Setup Guide

## Overview

The pre-push hook automatically runs the full test suite before every `git push`, preventing broken code from reaching CI/CD.

**Benefits:**
- ✅ Catches test failures before they hit GitHub Actions (~5 min saved per failure)
- ✅ Prevents embarrassing CI failures
- ✅ Runs in ~30 seconds locally vs ~3-5 minutes in CI

---

## Installation

The hooks are already installed in `.git/hooks/`:
- `pre-push` - Bash version (Git Bash, WSL, macOS, Linux)
- `pre-push.ps1` - PowerShell version (Windows)

Git will automatically use the appropriate version based on your shell.

---

## How It Works

Every time you run `git push`:

```
🔍 Running pre-push validation...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Running unit tests...
.................................... [100%]
237 passed, 13 deselected in 26.33s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ All tests passed - Proceeding with push
```

**If tests fail:**
```
❌ TESTS FAILED - Push aborted

Fix the failing tests before pushing.
To skip this check (not recommended):
  git push --no-verify
```

---

## Bypassing the Hook (Emergency Only)

If you absolutely need to push without running tests:

```bash
git push --no-verify
```

> [!WARNING]
> Only use `--no-verify` in emergencies. Skipping tests defeats the purpose of the hook and may break CI.

---

## What Gets Tested

The hook runs:
```bash
poetry run pytest tests/ -q --tb=short
```

This executes:
- ⚡ All 237 unit tests
- ⏭️ Integration tests (skipped - require real credentials)

**Total time:** ~30 seconds

---

## Troubleshooting

### Hook Not Running

Verify hooks are enabled:
```bash
git config core.hooksPath
```

Should output: `.git/hooks`

If not set:
```bash
git config core.hooksPath .git/hooks
```

### Tests Failing Locally But Pass in CI

This usually means:
1. You have uncommitted changes affecting tests
2. Your local environment differs from CI (check Python version, dependencies)

Run:
```bash
git status
poetry install --sync
```

### Hook Takes Too Long

The hook is designed to be fast (~30s). If it's slower:
1. Check if you have many changed files
2. Ensure you're not running integration tests (they're excluded by default)
3. Consider using `pytest-xdist` for parallel test execution

---

## Maintenance

### Updating the Hook

If you need to modify the hook behavior, edit:
- `.git/hooks/pre-push` (Bash)
- `.git/hooks/pre-push.ps1` (PowerShell)

### Disabling the Hook

To temporarily disable:
```bash
git config core.hooksPath ""
```

To re-enable:
```bash
git config core.hooksPath .git/hooks
```

---

## Best Practices

1. **Run tests before committing** - Catch issues even earlier
2. **Don't use `--no-verify`** - Let the hook do its job
3. **Keep tests fast** - Slow tests = temptation to skip the hook
4. **Fix failures immediately** - Don't accumulate broken tests
