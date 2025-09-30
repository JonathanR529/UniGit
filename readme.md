# UniGit
A universal Git repository manager focused on efficiently pulling and managing multiple repositories.

## Getting Started

You can run it directly with:

```
python UniGit.py
```

Or download the [latest release](https://github.com/JonathanR529/UniGit/releases/latest) for a Windows executable.

When you run the script, it will:

* Present a menu with the following options:
  * Clone a repository (single repository or all repositories from a user)
  * Pull a repository (single repository or all in current directory)
  * Switch branch
  * View commit log
  * Quit

## Features

* **Clone repositories**: Clone individual repositories or all repositories from a GitHub/GitLab/Bitbucket user
* **Pull updates**: Update a single repository or recursively update all repositories in a directory
* **Branch management**: List and switch branches
* **Commit logs**: View and save repository commit history
* **Commit summarization**: Generate AI-powered summaries of changes using Ollama (optional)

## Configuration

On first run, the script will create a `config.json` file with default settings:

```json
{
    "enable_summary": false,
    "dry_run": false,
    "log_level": "INFO",
    "model": "llama3.2",
    "max_retries": 2,
    "summary_timeout": 30
}
```

* `enable_summary`: Whether to generate commit summaries using Ollama
* `dry_run`: Preview changes without actually updating repositories
* `log_level`: Logging verbosity level (INFO, DEBUG, WARNING, ERROR)
* `model`: Ollama model to use for summarization
* `max_retries`: Number of retry attempts for failed summaries
* `summary_timeout`: Maximum time in seconds to wait for a summary

## Requirements

* Python 3.6 or higher
* Git installed and in your system path
* The `requests` package for API communication with Git hosting services
  ```
  pip install requests
  ```
* For summarization feature (optional):
  * [Ollama](https://ollama.ai) installed and configured
  * An LLM model available in Ollama (default: llama3.2)

## Building

You can build UniGit into an executable using PyInstaller:

```
pyinstaller --onefile UniGit.py
```

If you have [UPX](https://upx.github.io/) you can optionally use the `--upx-dir` flag with PyInstaller to compress the compiled executable and reduce its file size.

## Error Logging

The script logs all errors to `errors.log` for troubleshooting.

## Summaries

When the summarization feature is enabled, commit summaries are saved to `summary.txt` in the current directory.