# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`gh-release-devpi` is a Python command-line tool that downloads build artifacts from GitHub Releases and uploads them to DevPI servers. The tool is primarily designed for automating Python package distribution workflows.

## Development Commands

### Installation and Setup
```bash
# Install in development mode
pip install -e .

# Run the module directly
python -m gh_release_devpi.main download

# Install dependencies using uv (if available)
uv sync
```

### Building and Publishing
```bash
# Build wheel package
uv build --wheel

# Publish to PyPI (requires UV_PUBLISH_TOKEN)
uv publish
```

### Running the Tool
```bash
# Download from GitHub Release and upload to DevPI
gh-release-devpi download

# Download only (skip upload)
gh-release-devpi download --skip-upload

# Upload local packages to DevPI (standalone)
gh-release-devpi upload ./dist

# With explicit parameters (download command)
gh-release-devpi download --repo owner/repo --token ghp_xxx --output ./dist
```

## Architecture

### Core Components

**Main Entry Point (`gh_release_devpi/main.py`)**:
- Single-file application architecture using Typer for CLI interface
- Two main commands: `download` (GitHub Release + DevPI) and `upload` (DevPI only)
- Rich console output for enhanced user experience
- Modular functions organized by concern (download, upload, utilities)

**Key Functional Areas**:
1. **GitHub Integration**: Uses PyGithub library to interact with GitHub API
2. **File Download**: Custom streaming download with progress bars and retry logic
3. **DevPI Upload**: Direct HTTP upload to DevPI servers using requests library
4. **Package Metadata Extraction**: Regex-based parsing of wheel and sdist filenames
5. **File Hashing**: MD5 and SHA256 calculation for package verification

### Dependencies and Tools
- **Build System**: Hatchling (specified in pyproject.toml)
- **CLI Framework**: Typer for command-line interface
- **GitHub API**: PyGithub for repository interactions
- **HTTP Client**: Requests for file downloads and DevPI uploads
- **UI/Progress**: Rich for console output, tqdm for progress bars
- **Environment Management**: python-dotenv for .env file loading

### Configuration
The tool uses environment variables for configuration:
- `GITHUB_PAT`: GitHub Personal Access Token
- `GITHUB_REPO`: Repository name in format `owner/repo`
- `DEVPI_PASSWORD`: DevPI server password
- `DEVPI_USER`: DevPI username (default: root)
- `DEVPI_SERVER`: DevPI server URL
- `DEVPI_INDEX`: DevPI index name (default: dev)
- `DEVPI_USE_PROXY`: Proxy usage flag for DevPI uploads

### Release Workflow
Automated GitHub Actions workflow (`.github/workflows/release.yml`):
1. Triggers on version tags (`v*`)
2. Builds wheel package using `uv build --wheel`
3. Creates GitHub Release with artifacts
4. Publishes to PyPI using `uv publish`

### Project Structure
```
gh-release-devpi/
├── gh_release_devpi/
│   ├── __init__.py          # Package initialization
│   └── main.py              # Main application logic and CLI
├── .github/workflows/
│   └── release.yml          # Automated release workflow
├── pyproject.toml           # Project configuration and dependencies
├── uv.lock                  # Dependency lock file
├── README.md                # User documentation (Chinese)
├── CHANGELOG.md             # Version history
└── CLAUDE.md                # This file
```

### Key Implementation Details

**Download Strategy**:
- Primary method: GitHub API endpoints with `Accept: application/octet-stream` header
- Fallback retry logic with exponential backoff
- Streaming downloads with progress tracking

**Upload Implementation**:
- Direct HTTP POST to DevPI server endpoints
- Emulates twine's upload format with proper metadata
- Proxy control to avoid system proxy interference

**Package Parsing**:
- Wheel format: `{name}-{version}(-{build})?-{python}-{abi}-{platform}.whl`
- Sdist format: `{name}-{version}.tar.gz|zip|tar.bz2|egg`
- Regex-based extraction with graceful fallbacks

### Testing
No formal test suite is currently present in the codebase. The project relies on manual testing and the automated release workflow for validation.

### Development Notes
- Minimum Python version: 3.11 (specified in pyproject.toml)
- Single file architecture keeps the codebase simple and maintainable
- Chinese language comments and documentation reflect the target user base
- The tool is designed for CI/CD automation workflows