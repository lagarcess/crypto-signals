#!/usr/bin/env python3
"""
Crypto Sentinel - Pull Requests Fetcher.

This script fetches and displays pull requests for the current user
from the GitHub repository. It's designed to work in various environments
including local development, CI/CD, and manual execution.

Usage:
    # List all your PRs
    python pull_prs.py
    
    # List open PRs only
    python pull_prs.py --state open
    
    # Show detailed information
    python pull_prs.py -v
    
    # Specify a different author
    python pull_prs.py --author <username>
"""

import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional

# Try to import requests for API fallback
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def fetch_with_gh_cli(
    owner: str,
    repo: str,
    author: Optional[str] = None,
    state: str = "all",
) -> Optional[List[dict]]:
    """
    Fetch PRs using GitHub CLI.

    Returns None if gh is not available or not authenticated.
    """
    try:
        cmd = [
            "gh", "pr", "list",
            "--repo", f"{owner}/{repo}",
            "--json", "number,title,author,state,createdAt,updatedAt,url,isDraft",
            "--limit", "100",
        ]
        
        if state != "all":
            cmd.extend(["--state", state])
        
        if author:
            cmd.extend(["--author", author])
        
        # Set GH_TOKEN if GITHUB_TOKEN is available
        env = os.environ.copy()
        if "GITHUB_TOKEN" in env and "GH_TOKEN" not in env:
            env["GH_TOKEN"] = env["GITHUB_TOKEN"]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        
        if result.returncode != 0:
            return None
        
        return json.loads(result.stdout)
        
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        return None


def fetch_with_api(
    owner: str,
    repo: str,
    author: Optional[str] = None,
    state: str = "all",
    token: Optional[str] = None,
) -> Optional[List[dict]]:
    """
    Fetch PRs using GitHub REST API.
    
    Returns None if requests is not available or request fails.
    """
    if not HAS_REQUESTS:
        return None
    
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {"Accept": "application/vnd.github.v3+json"}
    
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    params = {"state": state, "per_page": 100}
    
    try:
        all_prs = []
        page = 1
        
        while page <= 5:  # Limit to 5 pages max
            params["page"] = page
            response = requests.get(url, headers=headers, params=params, timeout=10)
            
            if response.status_code != 200:
                return None
            
            prs = response.json()
            if not prs:
                break
            
            # Filter by author if specified
            if author:
                prs = [pr for pr in prs if pr["user"]["login"] == author]
            
            all_prs.extend(prs)
            page += 1
            
            # Stop if we've collected enough
            if len(all_prs) >= 100:
                break
        
        return all_prs
        
    except Exception:
        return None


def format_pr_display(pr: dict, is_api_format: bool) -> str:
    """
    Format a single PR for display.
    
    Args:
        pr: PR dictionary from either gh CLI or REST API
        is_api_format: True if from REST API, False if from gh CLI
    
    Returns:
        Formatted string for display
    """
    lines = []
    
    if is_api_format:
        # REST API format
        state = pr["state"]
        state_emoji = "🟢" if state == "open" else "🔴"
        draft_label = " [DRAFT]" if pr.get("draft", False) else ""
        
        lines.append(f"{state_emoji} #{pr['number']}: {pr['title']}{draft_label}")
        lines.append(f"   Author: {pr['user']['login']}")
        lines.append(f"   State: {state.upper()}")
        lines.append(f"   Created: {pr['created_at']}")
        lines.append(f"   Updated: {pr['updated_at']}")
        lines.append(f"   URL: {pr['html_url']}")
    else:
        # gh CLI format
        state = pr.get("state", "").upper()
        state_emoji = "🟢" if state == "OPEN" else "🔴"
        draft_label = " [DRAFT]" if pr.get("isDraft", False) else ""
        author_login = pr["author"].get("login", "unknown") if isinstance(pr["author"], dict) else str(pr["author"])
        
        lines.append(f"{state_emoji} #{pr['number']}: {pr['title']}{draft_label}")
        lines.append(f"   Author: {author_login}")
        lines.append(f"   State: {state}")
        lines.append(f"   Created: {pr.get('createdAt', 'N/A')}")
        lines.append(f"   Updated: {pr.get('updatedAt', 'N/A')}")
        lines.append(f"   URL: {pr.get('url', 'N/A')}")
    
    return "\n".join(lines)


def display_pull_requests(prs: List[dict], is_api_format: bool, verbose: bool = False) -> None:
    """
    Display pull requests in a formatted manner.
    """
    if not prs:
        print("\n✨ No pull requests found.")
        return
    
    print(f"\n📋 Found {len(prs)} pull request(s):\n")
    print("=" * 80)
    
    for pr in prs:
        print(format_pr_display(pr, is_api_format))
        
        if verbose and pr.get("body"):
            body = pr["body"]
            if body and body.strip():
                # Truncate to first 200 chars
                body_preview = body.strip()[:200]
                if len(body) > 200:
                    body_preview += "..."
                print(f"   Description: {body_preview}")
        
        print("-" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch and display your pull requests from the repository.",
        epilog="Example: python pull_prs.py --author lagarcess --state open"
    )
    parser.add_argument(
        "--owner",
        default="lagarcess",
        help="Repository owner (default: lagarcess)",
    )
    parser.add_argument(
        "--repo",
        default="crypto-signals",
        help="Repository name (default: crypto-signals)",
    )
    parser.add_argument(
        "--author",
        help="Filter PRs by author username (e.g., lagarcess)",
    )
    parser.add_argument(
        "--state",
        choices=["open", "closed", "all"],
        default="all",
        help="Filter by PR state (default: all)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed information including PR descriptions",
    )
    
    args = parser.parse_args()
    
    print(f"🔍 Fetching pull requests from {args.owner}/{args.repo}...")
    if args.author:
        print(f"   Filtering by author: @{args.author}")
    if args.state != "all":
        print(f"   Filtering by state: {args.state}")
    print()
    
    # Try GitHub CLI first
    prs = fetch_with_gh_cli(args.owner, args.repo, args.author, args.state)
    is_api_format = False
    
    if prs is None:
        # Fallback to REST API
        print("⚠️  GitHub CLI not available or not authenticated. Trying REST API...")
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        prs = fetch_with_api(args.owner, args.repo, args.author, args.state, token)
        is_api_format = True
        
        if prs is None:
            print("\n❌ Failed to fetch pull requests.", file=sys.stderr)
            print("\nTroubleshooting:", file=sys.stderr)
            print("  1. Install GitHub CLI: https://cli.github.com/", file=sys.stderr)
            print("  2. Authenticate: gh auth login", file=sys.stderr)
            print("  3. Or set GITHUB_TOKEN environment variable", file=sys.stderr)
            return 1
    
    display_pull_requests(prs, is_api_format, args.verbose)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())



def display_pull_requests(prs: List[dict], verbose: bool = False) -> None:
    """
    Display pull requests in a formatted manner.

    Args:
        prs: List of pull request dictionaries.
        verbose: Show detailed information. Default: False.
    """
    if not prs:
        print("No pull requests found.")
        return
    
    print(f"\n📋 Found {len(prs)} pull request(s):\n")
    print("=" * 80)
    
    for pr in prs:
        # Handle both gh CLI and REST API formats
        if "author" in pr:  # gh CLI format
            state = pr.get("state", "").upper()
            state_emoji = "🟢" if state == "OPEN" else "🔴"
            draft_label = " [DRAFT]" if pr.get("isDraft", False) else ""
            author_name = pr["author"].get("login", "unknown") if isinstance(pr["author"], dict) else pr["author"]
            
            print(f"{state_emoji} #{pr['number']}: {pr['title']}{draft_label}")
            print(f"   Author: {author_name}")
            print(f"   State: {state}")
            print(f"   Created: {pr.get('createdAt', 'N/A')}")
            print(f"   Updated: {pr.get('updatedAt', 'N/A')}")
            print(f"   URL: {pr.get('url', 'N/A')}")
        else:  # REST API format
            state_emoji = "🟢" if pr["state"] == "open" else "🔴"
            draft_label = " [DRAFT]" if pr.get("draft", False) else ""
            
            print(f"{state_emoji} #{pr['number']}: {pr['title']}{draft_label}")
            print(f"   Author: {pr['user']['login']}")
            print(f"   State: {pr['state'].upper()}")
            print(f"   Created: {pr['created_at']}")
            print(f"   Updated: {pr['updated_at']}")
            print(f"   URL: {pr['html_url']}")
        
        if verbose and pr.get("body"):
            body = pr["body"]
            if body:
                print(f"   Description: {body[:200]}...")
        
        print("-" * 80)


def main():
    """Main entry point for the PR fetcher script."""
    parser = argparse.ArgumentParser(
        description="Fetch and display pull requests from the GitHub repository."
    )
    parser.add_argument(
        "--owner",
        default="lagarcess",
        help="Repository owner (default: lagarcess)",
    )
    parser.add_argument(
        "--repo",
        default="crypto-signals",
        help="Repository name (default: crypto-signals)",
    )
    parser.add_argument(
        "--author",
        help="Filter PRs by author username",
    )
    parser.add_argument(
        "--state",
        choices=["open", "closed", "all"],
        default="all",
        help="Filter by state (default: all)",
    )
    parser.add_argument(
        "--use-api",
        action="store_true",
        help="Use GitHub REST API instead of gh CLI (requires token)",
    )
    parser.add_argument(
        "--token",
        help="GitHub personal access token (optional, or set GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed information",
    )
    
    args = parser.parse_args()
    
    print(f"🔍 Fetching pull requests from {args.owner}/{args.repo}...")
    if args.author:
        print(f"   Filtering by author: {args.author}")
    if args.state != "all":
        print(f"   Filtering by state: {args.state}")
    
    # Determine which method to use
    if args.use_api:
        token = args.token or os.getenv("GITHUB_TOKEN")
        if not token:
            print("⚠️  Warning: No GitHub token provided. Rate limits may apply.", file=sys.stderr)
        print("   Using GitHub REST API")
        prs = fetch_pull_requests_api(
            owner=args.owner,
            repo=args.repo,
            author=args.author,
            state=args.state,
            token=token,
        )
    else:
        print("   Using GitHub CLI (gh)")
        prs = fetch_pull_requests_gh_cli(
            owner=args.owner,
            repo=args.repo,
            author=args.author,
            state=args.state,
        )
    
    display_pull_requests(prs, verbose=args.verbose)
    
    return 0 if prs else 1


if __name__ == "__main__":
    sys.exit(main())
