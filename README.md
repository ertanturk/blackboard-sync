# Blackboard Sync

Blackboard Sync is a command-line application that synchronizes course materials from Blackboard Ultra to your local machine.

Instead of manually navigating each course and downloading files individually, Blackboard Sync recursively mirrors course content, preserves the original folder hierarchy, and downloads only new or updated files.

## Features

- Blackboard Ultra support
- Browser-based authentication with session persistence
- Recursive course discovery
- Incremental synchronization
- Concurrent downloads
- Preserves Blackboard folder structure
- Cross-platform support (Linux, macOS, Windows)
- Modular architecture designed for maintainability

## Requirements

- Python 3.14 or later
- `uv` or `pipx`
- Playwright Chromium

## Installation

Clone the repository:

```bash
git clone https://github.com/ertanturk/blackboard-sync.git
cd blackboard-sync
```

### Using `uv`

Install the application:

```bash
uv tool install .
```

Or install directly from GitHub:

```bash
uv tool install git+https://github.com/ertanturk/blackboard-sync.git
```

### Using `pipx`

Install the application:

```bash
pipx install .
```

Or install directly from GitHub:

```bash
pipx install git+https://github.com/ertanturk/blackboard-sync.git
```

### Install Playwright Chromium

Blackboard Sync uses Playwright for browser automation. Install the required Chromium browser:

```bash
playwright install chromium
```

## Configuration

Blackboard Sync requires a valid `.env` configuration file before first use.

See the [Usage Guide](docs/USAGE.md) for environment variables, configuration, and additional setup instructions.

## Usage

After installation, the application is available globally:

```bash
bb --course MATH116
```

To view all available options:

```bash
bb --help
```

On the first run, Blackboard Sync opens a browser window for authentication. After a successful login, the authenticated session is stored locally and automatically reused until it expires.

## Documentation

Additional documentation is available in the `docs` directory.

| Document                             | Description                                                         |
| ------------------------------------ | ------------------------------------------------------------------- |
| [Usage Guide](docs/USAGE.md)         | Installation, configuration, command-line options, and examples     |
| [Architecture](docs/ARCHITECTURE.md) | Project architecture, synchronization pipeline, and internal design |

## Contributing

Contributions are welcome. If you plan to introduce significant changes, please open an issue first to discuss the proposed design.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
