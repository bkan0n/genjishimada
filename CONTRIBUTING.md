# Contributing to Genji Shimada

Thank you for your interest in contributing to Genji Shimada! This guide will help you get started with contributing to
our Discord bot and REST API for the Genji Parkour community.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Making Changes](#making-changes)
- [Pull Request Process](#pull-request-process)
- [Code Standards](#code-standards)
- [Testing Guidelines](#testing-guidelines)
- [Getting Help](#getting-help)

## Getting Started

### Prerequisites

Before you begin, ensure you have:

- Python 3.13 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Docker and Docker Compose
- Git
- A Discord account and bot token (for bot development)
- SSH access to VPS (for database imports, optional for most contributions)

### Initial Setup

1. **Fork and clone the repository**
   ```bash
   git clone https://github.com/yourusername/genjishimada.git
   cd genjishimada
   ```

2. **Follow the quick start in README**
   ```bash
   just setup
   docker compose -f docker-compose.local.yml up -d
   ./scripts/import-db-from-vps.sh dev  # Optional, requires VPS access
   cp .env.local.example .env.local
   # Edit .env.local with your settings
   ```

3. **Verify your setup**
   ```bash
   just lint-all  # Should pass without errors
   just test-all  # Should pass all tests
   ```

4. **Read the documentation**
    - Visit [docs.genji.pk](https://docs.genji.pk) for comprehensive project documentation
    - Review the architecture overview to understand how components interact
    - Familiarize yourself with the monorepo structure (apps/api, apps/bot, libs/sdk)

## Development Workflow

### Branch Naming

Use descriptive branch names with prefixes:

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `test/description` - Test additions/improvements
- `refactor/description` - Code refactoring

Examples: `feature/map-rating-system`, `fix/completion-validation`, `docs/api-endpoints`

### Before You Commit

Always run these commands before committing:

```bash
just lint-all  # Format, lint, and type-check all code
just test-all  # Run all tests
```

These checks are enforced in CI, so running them locally saves time.

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Test additions or changes
- `refactor:` - Code refactoring without feature changes
- `perf:` - Performance improvements
- `chore:` - Build process or tooling changes

**Examples:**

```
feat: add map rating system with weighted averages

fix: resolve completion validation for edge cases

docs: update API endpoint documentation for v3

test: add integration tests for lootbox system
```

## Making Changes

### Start Small

If you're new to the project:

- Look for issues labeled `good first issue`
- Start with documentation improvements
- Fix small bugs before tackling large features
- Ask questions if you're unsure about an approach

### Code Changes

**For new features:**

1. Check if a similar feature exists or was discussed in issues
2. Open an issue to discuss the feature before implementing
3. Write tests alongside your implementation
4. Update documentation if the feature changes user-facing behavior

**For bug fixes:**

1. Search existing issues to see if it's already reported
2. Add a regression test that fails without your fix
3. Implement the fix
4. Verify the test now passes

### Testing Requirements

**All code changes must include tests:**

- New features require tests for happy path and edge cases
- Bug fixes require regression tests
- Refactoring should maintain existing test coverage

**Running tests:**

```bash
just test-api      # Run API tests only
just test-bot      # Run bot tests only (when implemented)
just test-all      # Run all tests
```

### Documentation Updates

Update documentation when:

- Adding new API endpoints or changing existing ones
- Modifying the architecture or adding new services
- Changing environment variables or configuration
- Adding new development commands or workflows

Documentation lives at [docs.genji.pk](https://docs.genji.pk) - not in this repository.

## Pull Request Process

### Before Opening a PR

1. **Sync with main branch**
   ```bash
   git checkout main
   git pull origin main
   git checkout your-feature-branch
   git rebase main
   ```

2. **Verify all checks pass**
   ```bash
   just lint-all
   just test-all
   ```

3. **Review your changes**
    - Read through your diff
    - Remove debug code, commented-out code, and console.logs
    - Ensure no sensitive data (API keys, tokens) is included

### Opening the PR

1. **Fill out the PR template completely**
    - Provide clear description of changes
    - Link related issues with "Fixes #123" or "Closes #456"
    - Describe your testing approach
    - Add screenshots for UI changes

2. **Ensure CI passes**
    - All linting checks must pass
    - All tests must pass
    - Address any warnings or failures

3. **Request review**
    - Tag maintainers if you know who should review
    - Be responsive to feedback and questions
    - Make requested changes promptly

4. **Keep your PR updated**
    - Rebase on main if it moves forward
    - Resolve merge conflicts promptly
    - Update tests if requirements change during review

### During Review

- Be open to feedback and suggestions
- Ask questions if feedback is unclear
- Make changes in new commits (don't force-push during review)
- Respond to all review comments
- Thank reviewers for their time

### After Approval

- Maintainers will merge your PR
- Your branch will be deleted automatically
- You can delete your local branch: `git branch -d feature/your-feature`

## Code Standards

### Linting and Type Checking

This project enforces strict code quality standards:

- **Linter:** [Ruff](https://docs.astral.sh/ruff/) - Fast Python linter and formatter
- **Type Checker:** [BasedPyright](https://docs.basedpyright.com/) - Strict type checking
- **Line Length:** 120 characters
- **Docstring Style:** Google-style docstrings
- **Import Sorting:** Enforced by Ruff

All standards are enforced in CI and must pass before merge.

### Python Style Guidelines

- **Type hints required** for all function signatures (enforced by ANN rules)
- **Docstrings required** for public functions and classes
- **Explicit is better than implicit** - avoid magic values
- **Error handling:**
    - API: Use `CustomHTTPException` from `utilities/errors.py`
    - Bot: Errors logged to Sentry with AsyncioIntegration
- **Database access:** Always use dependency-injected `conn: Connection` parameter
- **Async/await:** Use async patterns consistently

### Architecture Patterns

**API (apps/api):**

- DI modules (`di/*.py`) contain business logic
- Route handlers (`routes/*.py`) are thin wrappers
- Use `BaseService` for RabbitMQ publishing
- Repository pattern for database queries

**Bot (apps/bot):**

- Extensions (`extensions/*.py`) for feature modules
- `@queue_consumer` decorator for async event handling
- Use `api_service.py` for API calls

**SDK (libs/sdk):**

- All data models use `msgspec.Struct`
- Shared types must be importable by both API and bot
- Keep models lightweight and serialization-focused

See [docs.genji.pk/architecture](https://docs.genji.pk) for detailed patterns.

## Testing Guidelines

### Test Structure

**API tests** (`apps/api/tests/`):

- Use pytest with pytest-asyncio
- Database fixtures provided by pytest-databases
- Parallel execution with pytest-xdist (8 workers)
- Set `X-PYTEST-ENABLED=1` header to skip queue publishing

**Test organization:**

- Mirror the source structure (test file per module)
- Group related tests in classes
- Use descriptive test names: `test_<function>_<scenario>_<expected>`

### Writing Good Tests

```python
async def test_create_map_with_valid_data_succeeds():
    """Test that creating a map with valid data returns success."""
    # Arrange
    map_data = {"name": "Test Map", "creator_id": 1}

    # Act
    result = await create_map(conn, map_data)

    # Assert
    assert result.success is True
    assert result.map.name == "Test Map"
```

**Test best practices:**

- Arrange-Act-Assert pattern
- One assertion focus per test
- Test edge cases and error conditions
- Use fixtures for common setup
- Clean up test data (handled automatically in most cases)

## Getting Help

### Questions and Discussions

- **General questions:** Join our [Discord community](https://dsc.gg/genjiparkour)
- **Bug reports:** Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml)
- **Feature requests:** Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml)
- **Documentation:** Check [docs.genji.pk](https://docs.genji.pk) first

### Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](.github/CODE_OF_CONDUCT.md). Please read and follow it
in all interactions.

## Recognition

Contributors are recognized in:

- Git commit history
- Pull request comments and reviews
- Community Discord (contributors role)

Significant contributions may be highlighted in release notes.

---

Thank you for contributing to Genji Shimada! Your efforts help make the Genji Parkour community better. 🚀
