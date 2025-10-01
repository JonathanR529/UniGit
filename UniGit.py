import json
import logging
import os
import subprocess
import time
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple

# Default configuration
DEFAULT_CONFIG = {
    "enable_summary": False,
    "dry_run": False,
    "log_level": "INFO",
    "model": "llama3.2",
    "max_retries": 2,
    "summary_timeout": 30
}


class UniGit:
    """Universal Git manager that handles common Git operations."""

    def __init__(self, config: Dict[str, any]):
        """
        Initialize UniGit with configuration.

        Args:
            config: Configuration dictionary
        """
        self.enable_summary = config.get("enable_summary", DEFAULT_CONFIG["enable_summary"])
        self.dry_run = config.get("dry_run", DEFAULT_CONFIG["dry_run"])
        self.model = config.get("model", DEFAULT_CONFIG["model"])
        self.max_retries = config.get("max_retries", DEFAULT_CONFIG["max_retries"])
        self.summary_timeout = config.get("summary_timeout", DEFAULT_CONFIG["summary_timeout"])
        self.logger = logging.getLogger("UniGit")
        self.summaries = []
        self.current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.summary_failures = 0
        
        # Git hosting services patterns
        self.git_host_patterns = {
            'github': r'^https?://(www\.)?github\.com/([^/]+)/?$',
            'gitlab': r'^https?://(www\.)?gitlab\.com/([^/]+)/?$',
            'bitbucket': r'^https?://(www\.)?bitbucket\.org/([^/]+)/?$',
            'azure': r'^https?://([^/]+)\.visualstudio\.com/([^/]+)/?$',
            'aws': r'^https?://git-codecommit\.[^/]+\.amazonaws\.com/v1/repos/([^/]+)/?$',
            'gitea': r'^https?://([^/]+)/([^/]+)/?$',
            'sourcehut': r'^https?://(git|hg)\.sr\.ht/~([^/]+)/?$',
            'launchpad': r'^https?://launchpad\.net/([^/]+)/?$',
            'custom': r'^https?://([^/]+)/([^/]+)/?$'
        }

    def extract_repo_name(self, url: str) -> str:
        """
        Extract repository name from a URL.
        
        Args:
            url: Repository URL
            
        Returns:
            Repository name
        """
        # Remove .git extension if present
        url = url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        
        # Get the last part after the last slash
        return url.split('/')[-1]

    def is_git_host_user_url(self, url: str) -> Tuple[bool, str]:
        """
        Check if a URL is a Git hosting service user URL and not a repository URL.
        
        Args:
            url: The URL to check
            
        Returns:
            Tuple of (is_user_url, host_type)
        """
        for host_type, pattern in self.git_host_patterns.items():
            if re.match(pattern, url):
                # Check if it's not a repository URL (no additional path components)
                parts = url.rstrip('/').split('/')
                if host_type in ['github', 'gitlab', 'bitbucket', 'sourcehut', 'launchpad']:
                    # Common pattern: domain/username
                    return len(parts) <= 4, host_type
                elif host_type == 'azure':
                    # Azure pattern: xxx.visualstudio.com/project
                    return len(parts) <= 4, host_type
                elif host_type == 'aws':
                    # AWS CodeCommit doesn't have user URLs in the same way
                    return False, host_type
                else:
                    # Generic check for custom Git hosts
                    return len(parts) <= 4, host_type
                    
        return False, 'unknown'

    def extract_username_from_url(self, url: str, host_type: str) -> str:
        """
        Extract username from a Git hosting service URL.
        
        Args:
            url: Git hosting service URL
            host_type: Type of Git hosting service
            
        Returns:
            Username or organization name
        """
        url = url.rstrip('/')
        parts = url.split('/')
        
        if host_type in ['github', 'gitlab', 'bitbucket']:
            # Standard format: https://service.com/username
            return parts[-1]
        elif host_type == 'azure':
            # Azure format: https://org.visualstudio.com/project
            return parts[-1]
        elif host_type == 'sourcehut':
            # SourceHut format: https://git.sr.ht/~username
            username = parts[-1]
            if username.startswith('~'):
                username = username[1:]
            return username
        elif host_type == 'launchpad':
            # Launchpad format: https://launchpad.net/project
            return parts[-1]
        else:
            # Default to last path component
            return parts[-1]

    def get_user_repos(self, username: str, host_type: str, url: str) -> List[str]:
        """
        Get all repositories for a user on a Git hosting service.
        
        Args:
            username: Username or organization name
            host_type: Type of Git hosting service
            url: Original URL (needed for some services)
            
        Returns:
            List of repository URLs
        """
        try:
            repos = []
            
            if host_type == 'github':
                # GitHub API
                page = 1
                per_page = 100
                
                while True:
                    api_url = f"https://api.github.com/users/{username}/repos?per_page={per_page}&page={page}"
                    response = requests.get(api_url)
                    
                    if response.status_code != 200:
                        print(f"Error fetching repositories: HTTP {response.status_code}")
                        break
                        
                    repos_page = response.json()
                    if not repos_page:
                        break
                        
                    for repo in repos_page:
                        repos.append(repo['clone_url'])
                        
                    if len(repos_page) < per_page:
                        break
                        
                    page += 1
                    
            elif host_type == 'gitlab':
                # GitLab API
                page = 1
                per_page = 100
                
                while True:
                    api_url = f"https://gitlab.com/api/v4/users/{username}/projects?per_page={per_page}&page={page}"
                    response = requests.get(api_url)
                    
                    if response.status_code != 200:
                        # Try as a group instead of a user
                        api_url = f"https://gitlab.com/api/v4/groups/{username}/projects?per_page={per_page}&page={page}"
                        response = requests.get(api_url)
                        
                        if response.status_code != 200:
                            print(f"Error fetching repositories: HTTP {response.status_code}")
                            break
                    
                    repos_page = response.json()
                    if not repos_page:
                        break
                        
                    for repo in repos_page:
                        repos.append(repo['http_url_to_repo'])
                        
                    if len(repos_page) < per_page:
                        break
                        
                    page += 1
                    
            elif host_type == 'bitbucket':
                # Bitbucket API
                page = 1
                
                while True:
                    api_url = f"https://api.bitbucket.org/2.0/repositories/{username}?page={page}"
                    response = requests.get(api_url)
                    
                    if response.status_code != 200:
                        print(f"Error fetching repositories: HTTP {response.status_code}")
                        break
                        
                    data = response.json()
                    if 'values' not in data or not data['values']:
                        break
                        
                    for repo in data['values']:
                        if 'links' in repo and 'clone' in repo['links']:
                            for clone_link in repo['links']['clone']:
                                if clone_link['name'] == 'https':
                                    repos.append(clone_link['href'])
                                    break
                    
                    if 'next' not in data:
                        break
                        
                    page += 1
                    
            else:
                print(f"Automatic repository listing not supported for {host_type}.")
                print("Please enter repository URLs manually.")
                
                while True:
                    repo_url = input("Enter repository URL (or empty to finish): ").strip()
                    if not repo_url:
                        break
                    repos.append(repo_url)
                
            return repos
            
        except Exception as e:
            print(f"Error getting repositories: {str(e)}")
            return []

    def find_git_repositories(self, start_dir: Union[str, Path]) -> List[Path]:
        """
        Find all Git repositories in a directory and its subdirectories.
        
        Args:
            start_dir: Starting directory to search
            
        Returns:
            List of paths to Git repositories
        """
        repos = []
        start_dir = Path(start_dir)
        
        for root, dirs, _ in os.walk(start_dir):
            if '.git' in dirs:
                repos.append(Path(root))
                # Don't descend into .git directories
                dirs.remove('.git')
                
            # Skip hidden directories except .git
            dirs[:] = [d for d in dirs if not d.startswith('.') or d == '.git']
            
        return repos

    def check_repo_exists(self, repo_name_or_url: str) -> Tuple[bool, str]:
        """
        Check if a repository exists in the current directory or subdirectories.
        
        Args:
            repo_name_or_url: Repository name or URL
            
        Returns:
            Tuple of (exists, repo_name)
        """
        # Extract repo name if URL is provided
        if '/' in repo_name_or_url:
            repo_name = self.extract_repo_name(repo_name_or_url)
        else:
            repo_name = repo_name_or_url
            
        # First, check direct path
        repo_path = Path(repo_name)
        if repo_path.exists() and (repo_path / ".git").is_dir():
            return True, repo_name
            
        # Then, scan all repositories in current directory and subdirectories
        all_repos = self.find_git_repositories(Path.cwd())
        for repo_path in all_repos:
            if repo_path.name == repo_name:
                return True, str(repo_path)
                
        return False, repo_name

    def clone_repository(self) -> None:
        """Clone a Git repository or all repositories from a Git hosting service user."""
        try:
            print("\nClone Repository")
            repo_url = input("Enter repository URL or Git hosting service user URL: ").strip()
            
            if not repo_url:
                print("URL is required.")
                return
                
            # Check if it's a Git hosting service user URL
            is_user_url, host_type = self.is_git_host_user_url(repo_url)
            
            if is_user_url:
                username = self.extract_username_from_url(repo_url, host_type)
                print(f"Fetching repositories for {host_type} user: {username}...")
                
                repos = self.get_user_repos(username, host_type, repo_url)
                
                if not repos:
                    print(f"No repositories found for user: {username}")
                    return
                    
                print(f"Found {len(repos)} repositories.")
                
                # Create directory for user if it doesn't exist
                user_dir = Path(username)
                if not user_dir.exists():
                    user_dir.mkdir()
                    
                clone_submodules = input("Clone with submodules? (y/n) [n]: ").strip().lower() == 'y'
                
                # Clone each repository
                for repo_url in repos:
                    repo_name = self.extract_repo_name(repo_url)
                    repo_path = user_dir / repo_name
                    
                    if repo_path.exists():
                        print(f"Repository {repo_name} already exists. Skipping...")
                        continue
                        
                    print(f"Cloning repository: {repo_name}...")
                    cmd = ["git", "clone"]
                    if clone_submodules:
                        cmd.append("--recurse-submodules")
                    cmd.append(repo_url)
                    cmd.append(str(repo_path))
                    
                    try:
                        subprocess.run(cmd, check=True)
                    except subprocess.CalledProcessError as e:
                        error_output = str(e)
                        if "403" in error_output or "forbidden" in error_output.lower() or "Permission denied" in error_output:
                            print(f"Repository {repo_name} is forbidden. Skipping...")
                        else:
                            print(f"Error cloning repository {repo_name}: {error_output}")
                        continue
                
                print(f"All repositories for user {username} have been cloned.")
                
            else:
                # Regular repository clone
                clone_submodules = input("Clone submodules? (y/n) [n]: ").strip().lower() == 'y'
                
                # Extract the repository name from the URL
                repo_name = self.extract_repo_name(repo_url)
                target_dir = Path(repo_name)
                
                if target_dir.exists():
                    overwrite = input(f"Directory '{repo_name}' already exists. Overwrite? (y/n) [n]: ").strip().lower()
                    if overwrite != 'y':
                        print("Clone operation cancelled.")
                        return
                
                print(f"Cloning repository '{repo_url}' to '{repo_name}'...")
                
                cmd = ["git", "clone"]
                if clone_submodules:
                    cmd.append("--recurse-submodules")
                cmd.append(repo_url)
                
                subprocess.run(cmd, check=True)
                print(f"Repository cloned successfully to '{repo_name}'.")
            
        except subprocess.CalledProcessError as e:
            print(f"Error cloning repository: {str(e)}")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")

    def pull_repository(self) -> None:
        """Pull updates for a Git repository."""
        try:
            print("\nPull Repository")
            pull_option = input("Pull options:\n"
                              "1) Single repository\n"
                              "2) All repositories in current directory\n"
                              "Enter choice (1/2): ").strip()
                              
            if pull_option == "1":
                repo_name_or_url = input("Enter repository name or URL: ").strip()
                exists, repo_name = self.check_repo_exists(repo_name_or_url)
                
                if not exists:
                    print(f"Repository '{repo_name}' not found in current directory.")
                    return
                    
                pull_submodules = input("Pull submodules? (y/n) [n]: ").strip().lower() == 'y'
                
                print(f"Pulling updates for '{repo_name}'...")
                cmd = ["git", "pull"]
                if pull_submodules:
                    cmd.append("--recurse-submodules")
                    
                try:
                    subprocess.run(cmd, cwd=repo_name, check=True)
                    print(f"Repository '{repo_name}' updated successfully.")
                except subprocess.CalledProcessError as e:
                    error_output = str(e)
                    if "403" in error_output or "forbidden" in error_output.lower() or "Permission denied" in error_output:
                        print(f"Repository {repo_name} is forbidden. Skipping...")
                    else:
                        print(f"Error updating repository {repo_name}: {error_output}")
                
            elif pull_option == "2":
                pull_submodules = input("Pull submodules? (y/n) [n]: ").strip().lower() == 'y'
                print("Pulling updates for all repositories in current directory...")
                
                # Reset summaries list before starting
                self.summaries = []
                
                self.git_pull_recursive(Path.cwd(), pull_submodules)
                
                if self.summaries and self.enable_summary:
                    summary_file = Path("git_summaries.txt")
                    self.save_summaries(summary_file)
                    print(f"Summaries saved to {summary_file}")
                
                print("All repositories updated successfully.")
                
            else:
                print("Invalid option selected.")
                
        except subprocess.CalledProcessError as e:
            print(f"Git error: {str(e)}")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")

    def switch_branch(self) -> None:
        """Checkout a different branch in a repository."""
        try:
            print("\nSwitch Branch")
            repo_name_or_url = input("Enter repository name or URL: ").strip()
            exists, repo_path = self.check_repo_exists(repo_name_or_url)
            
            if not exists:
                print(f"Repository '{repo_name_or_url}' not found in current directory or subdirectories.")
                return
                
            # Get list of branches
            print(f"Fetching branches for '{repo_path}'...")
            result = subprocess.run(
                ["git", "branch", "-a"], 
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse branches
            branches = []
            for line in result.stdout.splitlines():
                branch = line.strip()
                if branch.startswith('*'):
                    branch = branch[2:]  # Remove the * and space
                    branches.append((branch, True))  # Current branch
                elif branch.startswith('remotes/'):
                    # Skip HEAD reference
                    if '/HEAD ->' not in branch:
                        remote_branch = branch.split('/', 2)[2]  # Remove 'remotes/origin/'
                        if remote_branch not in [b[0] for b in branches]:
                            branches.append((remote_branch, False))
                else:
                    branches.append((branch, False))
            
            if not branches:
                print("No branches found.")
                return
                
            # Display branches
            print("\nAvailable branches:")
            for i, (branch, is_current) in enumerate(branches, 1):
                current_marker = " (current)" if is_current else ""
                print(f"{i}) {branch}{current_marker}")
                
            # Select branch
            selection = input("\nEnter branch number to checkout (or 'q' to cancel): ").strip()
            if selection.lower() == 'q':
                print("Branch switch cancelled.")
                return
                
            try:
                branch_idx = int(selection) - 1
                if 0 <= branch_idx < len(branches):
                    selected_branch = branches[branch_idx][0]
                    
                    # Confirm if switching from current branch
                    if branches[branch_idx][1]:
                        print(f"Already on branch '{selected_branch}'.")
                        return
                        
                    print(f"Switching to branch '{selected_branch}'...")
                    subprocess.run(["git", "checkout", selected_branch], cwd=repo_path, check=True)
                    print(f"Switched to branch '{selected_branch}'.")
                else:
                    print("Invalid branch number.")
            except ValueError:
                print("Please enter a valid number.")
                
        except subprocess.CalledProcessError as e:
            print(f"Git error: {str(e)}")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")

    def view_commit_log(self) -> None:
        """View and save commit log for a repository."""
        try:
            print("\nView Commit Log")
            repo_name_or_url = input("Enter repository name or URL: ").strip()
            exists, repo_path = self.check_repo_exists(repo_name_or_url)
            
            if not exists:
                print(f"Repository '{repo_name_or_url}' not found in current directory or subdirectories.")
                return
                
            repo_name = Path(repo_path).name
            log_file = Path(f"{repo_name}_commit_log.txt")
            print(f"Generating commit log for '{repo_path}'...")
            
            with open(log_file, 'w', encoding='utf-8') as f:
                subprocess.run(["git", "log"], cwd=repo_path, stdout=f, check=True)
                
            print(f"Commit log saved to '{log_file}'")
            
            # Ask if user wants to see the first few lines
            preview = input("Display first 10 lines of the log? (y/n) [y]: ").strip().lower()
            if preview != 'n':
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()[:10]
                    print("\n" + "".join(lines))
                    
        except subprocess.CalledProcessError as e:
            print(f"Git error: {str(e)}")
        except Exception as e:
            print(f"Unexpected error: {str(e)}")

    def summarize_with_ollama(self, commit_messages: str) -> str:
        """
        Generate a summary of commit messages using Ollama with improved error handling.

        Args:
            commit_messages: The commit messages to summarize

        Returns:
            The generated summary text or error message
        """
        if not commit_messages.strip():
            return "No commit messages to summarize."
            
        prompt = f"Summarize these git commits:\n{commit_messages}\nProvide a concise summary of the changes."
        self.logger.debug(f"Sending prompt to Ollama (length: {len(prompt)} chars)")
        
        for attempt in range(self.max_retries + 1):
            try:
                # Check if Ollama is available first
                subprocess.run(
                    ["ollama", "list"], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=True
                )
                
                # Run the actual summarization with a timeout
                result = subprocess.run(
                    ["ollama", "run", self.model],
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=self.summary_timeout,
                    check=True,
                )
                
                summary = result.stdout.strip()
                
                # Validate the summary
                if not summary or len(summary) < 10:
                    self.logger.warning("Ollama returned an unusually short summary")
                    if attempt < self.max_retries:
                        self.logger.info(f"Retrying summary generation (attempt {attempt+1}/{self.max_retries})")
                        time.sleep(2)
                        continue
                    return "Summary generation produced insufficient results."
                    
                # Truncate extremely long summaries
                if len(summary) > 1000:
                    self.logger.warning(f"Truncating long summary (length: {len(summary)})")
                    summary = summary[:997] + "..."
                    
                return summary
                
            except subprocess.TimeoutExpired:
                self.logger.error(f"Ollama summary timed out (attempt {attempt+1}/{self.max_retries})")
                if attempt < self.max_retries:
                    time.sleep(2)
                    continue
                self.summary_failures += 1
                return "Error: Summary generation timed out."
                
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr if hasattr(e, 'stderr') and e.stderr else str(e)
                self.logger.error(f"Ollama error (attempt {attempt+1}/{self.max_retries}): {error_msg}")
                if attempt < self.max_retries:
                    time.sleep(2)
                    continue
                self.summary_failures += 1
                return "Error generating summary: Ollama command failed."
                
            except FileNotFoundError:
                self.logger.error("Ollama not found. Please install Ollama or disable summary generation.")
                self.summary_failures += 1
                return "Error: Ollama not installed."
                
            except Exception as e:
                self.logger.error(f"Unexpected error during summary: {str(e)}")
                if attempt < self.max_retries:
                    time.sleep(2)
                    continue
                self.summary_failures += 1
                return "Error generating summary due to an unexpected issue."

    def git_pull(self, directory: Union[str, Path], pull_submodules: bool = False) -> None:
        """
        Pull updates for a Git repository.

        Args:
            directory: Path to the Git repository
            pull_submodules: Whether to pull submodules as well
        """
        directory = Path(directory)
        try:
            old_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=directory, encoding='utf-8'
            ).strip()

            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=directory, encoding='utf-8'
            ).strip()

            # Handle dry run mode
            if self.dry_run:
                subprocess.check_call(
                    ["git", "fetch"], cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                new_commits = subprocess.check_output(
                    ["git", "log", f"{old_head}..origin/{branch}", "--oneline"], 
                    cwd=directory, encoding='utf-8'
                ).strip()
                if new_commits:
                    self.logger.info(f"[Dry Run] Would pull in {directory} (branch: {branch})")
                    self.logger.info(f"[Dry Run] New commits for {directory}:\n{new_commits}")
                return

            # Perform actual git pull
            self.logger.debug(f"Pulling updates in {directory}")
            print(f"Pulling {directory}...")
            
            # Use try-except to catch permission errors and continue
            try:
                cmd = ["git", "pull"]
                if pull_submodules:
                    cmd.append("--recurse-submodules")
                    
                subprocess.check_call(cmd, cwd=directory)
            except subprocess.CalledProcessError as e:
                error_output = str(e)
                if "403" in error_output or "forbidden" in error_output.lower() or "Permission denied" in error_output:
                    self.logger.warning(f"Repository {directory} is forbidden. Skipping...")
                    print(f"Repository {directory} is forbidden. Skipping...")
                else:
                    self.logger.error(f"Git error in {directory}: {error_output}")
                    print(f"Git error in {directory}: {error_output}")
                return

            new_head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=directory, encoding='utf-8'
            ).strip()

            # Skip if no new commits
            if old_head == new_head:
                self.logger.debug(f"No changes in {directory}")
                print(f"No changes in {directory}")
                return

            # Get and potentially summarize new commits
            new_commits = subprocess.check_output(
                ["git", "log", f"{old_head}..{new_head}", "--oneline"], 
                cwd=directory, encoding='utf-8'
            ).strip()

            if new_commits and self.enable_summary:
                # Disable summaries if too many failures
                if self.summary_failures > 3:
                    if self.enable_summary:
                        self.logger.warning("Multiple summary failures detected. Disabling summaries for this run.")
                        self.enable_summary = False
                    return
                
                self.logger.info(f"New commits in {directory} ({branch}):\n{new_commits}")
                print(f"Generating summary for {directory}...")
                summary = self.summarize_with_ollama(new_commits)
                self.summaries.append({
                    "directory": str(directory),
                    "branch": branch,
                    "summary": summary,
                    "success": not summary.startswith("Error")
                })

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Git error in {directory}: {str(e)}")
            print(f"Git error in {directory}: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error in {directory}: {str(e)}")
            print(f"Unexpected error in {directory}: {str(e)}")

    def git_pull_recursive(self, directory: Union[str, Path], pull_submodules: bool = False) -> None:
        """
        Recursively search for Git repositories and pull updates.

        Args:
            directory: Root directory to start the search
            pull_submodules: Whether to pull submodules as well
        """
        directory = Path(directory)
        self.logger.debug(f"Scanning directory: {directory}")
        
        try:
            for item in os.listdir(directory):
                item_path = directory / item
                
                # Skip hidden directories except .git
                if item.startswith('.') and item != '.git':
                    continue
                    
                if item_path.is_dir():
                    # Check if this is a git repository
                    if (item_path / ".git").is_dir():
                        self.logger.debug(f"Found git repository: {item_path}")
                        try:
                            self.git_pull(item_path, pull_submodules)
                        except Exception as e:
                            self.logger.error(f"Error pulling {item_path}: {str(e)}")
                            print(f"Error pulling {item_path}: {str(e)}")
                            # Continue with the next repository
                            continue
                    else:
                        # Recursively search subdirectories
                        self.git_pull_recursive(item_path, pull_submodules)
        except PermissionError as e:
            self.logger.warning(f"Permission denied: {directory} - {str(e)}")
            print(f"Permission denied: {directory} - {str(e)}")
        except Exception as e:
            self.logger.error(f"Error scanning {directory}: {str(e)}")
            print(f"Error scanning {directory}: {str(e)}")

    def save_summaries(self, summary_file_path: Union[str, Path]) -> None:
        """
        Save generated summaries to a file with improved error handling.

        Args:
            summary_file_path: Path to the summary file
        """
        if not self.summaries or not self.enable_summary or self.dry_run:
            return
            
        # Filter out failed summaries
        valid_summaries = [s for s in self.summaries if s["success"]]
        
        if not valid_summaries:
            self.logger.warning("No valid summaries to save")
            return
            
        summary_file_path = Path(summary_file_path)
        self.logger.info(f"Saving {len(valid_summaries)} summaries to {summary_file_path}")
        
        try:
            # Read existing content
            existing_content = ""
            if summary_file_path.exists():
                with open(summary_file_path, "r", encoding='utf-8') as summary_file:
                    existing_content = summary_file.read()

            # Write new content followed by existing content
            with open(summary_file_path, "w", encoding='utf-8') as summary_file:
                summary_file.write(f"Date: {self.current_date}\n\n")
                for entry in valid_summaries:
                    summary_file.write(f"Directory: {entry['directory']}\n")
                    summary_file.write(f"Branch: {entry['branch']}\n")
                    summary_file.write(f"{entry['summary']}\n\n")
                if existing_content:
                    summary_file.write("-" * 50 + "\n\n")
                    summary_file.write(existing_content)
                    
            self.logger.info(f"Successfully saved {len(valid_summaries)} summaries")
        except Exception as e:
            self.logger.error(f"Error saving summaries: {str(e)}")
            print(f"Error saving summaries: {str(e)}")


def setup_logging(log_level: str, error_log_file_path: Optional[Union[str, Path]] = None) -> None:
    """
    Configure logging for the application.

    Args:
        log_level: The logging level to use for console output
        error_log_file_path: Optional path to error log file (will only log ERROR and above)
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Configure root logger for console output
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        '%Y-%m-%d %H:%M:%S'
    ))
    root_logger.addHandler(console_handler)
    
    # Add file handler for errors only if log file specified
    if error_log_file_path:
        file_handler = logging.FileHandler(error_log_file_path, encoding='utf-8')
        file_handler.setLevel(logging.ERROR)  # Only log ERROR and above
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        root_logger.addHandler(file_handler)


def load_or_create_config(config_file: Union[str, Path]) -> Dict[str, any]:
    """
    Load configuration from file or create a new one if it doesn't exist.

    Args:
        config_file: Path to the configuration file

    Returns:
        The configuration dictionary
    """
    config_file = Path(config_file)
    logger = logging.getLogger("Config")
    
    if not config_file.exists():
        logger.info(f"Configuration file not found. Creating new at {config_file}")
        
        # Create default config
        config = DEFAULT_CONFIG.copy()
        
        # Show configuration wizard
        print("Initial Configuration Setup")
        
        enable_summary_input = input(
            f"Enable commit summaries with Ollama? (true/false/t/f) [{DEFAULT_CONFIG['enable_summary']}]: "
        ).strip().lower()
        
        dry_run_input = input(
            f"Enable dry-run mode? (true/false/t/f) [{DEFAULT_CONFIG['dry_run']}]: "
        ).strip().lower()
        
        model_input = input(
            f"Ollama model to use [{DEFAULT_CONFIG['model']}]: "
        ).strip()

        # Parse user input
        if enable_summary_input in ("true", "t", "false", "f"):
            config["enable_summary"] = enable_summary_input in ("true", "t")
            
        if dry_run_input in ("true", "t", "false", "f"):
            config["dry_run"] = dry_run_input in ("true", "t")
            
        if model_input:
            config["model"] = model_input

        # Save configuration
        try:
            with open(config_file, "w", encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to write configuration file: {str(e)}")
            return DEFAULT_CONFIG
    else:
        logger.debug(f"Loading configuration from {config_file}")
        try:
            with open(config_file, "r", encoding='utf-8') as f:
                config = json.load(f)
                
            # Add any missing config keys with default values
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in configuration file {config_file}. Using defaults.")
            return DEFAULT_CONFIG
        except Exception as e:
            logger.error(f"Error reading configuration file: {str(e)}. Using defaults.")
            return DEFAULT_CONFIG
            
    return config


def main() -> None:
    """Main function to execute the script."""
    print("\nUniGit - Universal Git Manager")
    
    # Use default values instead of command line arguments
    config_file = "config.json"
    log_file = "errors.log"
    
    # Load configuration
    config = load_or_create_config(config_file)
    
    # Setup logging
    setup_logging(config["log_level"], log_file)
    logger = logging.getLogger("Main")
    
    # Create UniGit instance
    unigit = UniGit(config)
    
    try:
        # Main menu loop
        while True:
            print("\nUniGit Menu:")
            print("C) Clone a repository")
            print("P) Pull a repository")
            print("S) Switch branch")
            print("L) View commit log")
            print("Q) Quit")
            
            choice = input("\nEnter your choice: ").strip().upper()
            
            if choice == 'C':
                unigit.clone_repository()
            elif choice == 'P':
                unigit.pull_repository()
            elif choice == 'S':
                unigit.switch_branch()
            elif choice == 'L':
                unigit.view_commit_log()
            elif choice == 'Q':
                break
            else:
                print("Invalid option. Please try again.")
                
    except KeyboardInterrupt:
        print("\nProcess interrupted by user")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        print(f"\nUnexpected error: {str(e)}")
        
    print("Exiting UniGit.")

if __name__ == "__main__":
    main()