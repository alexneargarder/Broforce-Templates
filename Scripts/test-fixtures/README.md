# Test Fixtures for broforce-tools

This directory contains mock project structures for testing `broforce-tools` without modifying real projects.

## Structure

```
test-fixtures/
├── config.json            # Config with test repos (Linux uses config.json)
├── repos/
│   ├── TestRepo/
│   │   ├── TestMod/       # Mod with Thunderstore metadata (v1.1.0 unreleased)
│   │   ├── TestBro/       # Bro with Thunderstore metadata (v1.0.0 released)
│   │   ├── NewMod/        # Mod WITHOUT metadata (for init-thunderstore tests)
│   │   └── Releases/
│   │       ├── TestMod/   # manifest.json, Changelog.md, README.md
│   │       └── TestBro/
│   └── AnotherRepo/
│       ├── OtherMod/      # Mod with metadata (v2.1.0 unreleased)
│       ├── AnotherBro/    # Bro with metadata (v1.0.0 released)
│       └── Releases/
│           ├── OtherMod/
│           └── AnotherBro/
```

## Test Scenarios

| Project | Repo | Type | Has Metadata | Version | Unreleased |
|---------|------|------|--------------|---------|------------|
| TestMod | TestRepo | mod | yes | 1.1.0 | yes |
| TestBro | TestRepo | bro | yes | 1.0.0 | no |
| NewMod | TestRepo | mod | no | 1.0.0 | n/a |
| OtherMod | AnotherRepo | mod | yes | 2.1.0 | yes |
| AnotherBro | AnotherRepo | bro | yes | 1.0.0 | no |

## Usage

Set environment variables to point to test fixtures:

```bash
cd /path/to/Broforce-Templates/Scripts

# Build
nix build .

# Set test environment
export BROFORCE_CONFIG_DIR=$(pwd)/test-fixtures
export BROFORCE_REPOS_PARENT=$(pwd)/test-fixtures/repos

# Run tests
./result/bin/bt unreleased --all-repos
./result/bin/bt changelog show TestMod
./result/bin/bt init-thunderstore NewMod -y -d "Test description"

# Clean up
rm result
unset BROFORCE_CONFIG_DIR BROFORCE_REPOS_PARENT
```

## Notes

- DLL files are empty placeholders (just need to exist)
- icon.png files are copies of the template placeholder icon
