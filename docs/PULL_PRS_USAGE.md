# Pull PRs Script

A utility script to fetch and display pull requests from the crypto-signals GitHub repository.

## Features

- List all pull requests from the repository
- Filter by author
- Filter by state (open, closed, or all)
- Detailed view with PR descriptions
- Works with both GitHub CLI and REST API

## Prerequisites

One of the following:
- **GitHub CLI** (`gh`) installed and authenticated, OR
- **GITHUB_TOKEN** environment variable set with a GitHub personal access token

## Usage

### Basic Usage

List all pull requests:
```bash
python src/crypto_signals/scripts/pull_prs.py
```

### Filter by Author

List PRs by a specific author:
```bash
python src/crypto_signals/scripts/pull_prs.py --author lagarcess
```

### Filter by State

List only open PRs:
```bash
python src/crypto_signals/scripts/pull_prs.py --state open
```

### Verbose Output

Show detailed information including PR descriptions:
```bash
python src/crypto_signals/scripts/pull_prs.py --author lagarcess -v
```

### Combined Filters

```bash
python src/crypto_signals/scripts/pull_prs.py --author lagarcess --state open -v
```

## Authentication

### Option 1: GitHub CLI (Recommended)

```bash
# Install and authenticate
gh auth login
```

### Option 2: Personal Access Token

```bash
export GITHUB_TOKEN=your_token_here
python src/crypto_signals/scripts/pull_prs.py
```

## Examples

```bash
# Show all my open PRs
python src/crypto_signals/scripts/pull_prs.py --author lagarcess --state open

# Show all PRs with descriptions
python src/crypto_signals/scripts/pull_prs.py -v
```
