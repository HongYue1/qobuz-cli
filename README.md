# qobuz-cli

[![PyPI Version](https://img.shields.io/pypi/v/qobuz-cli.svg)](https://pypi.org/project/qobuz-cli)

A blazing fast, modern, and concurrent music downloader from Qobuz, designed for the command line.

<img width="2233" height="1226" alt="Screenshot_2025-10-31_15-46-06" src="https://github.com/user-attachments/assets/8de1e460-76ed-4301-a4c2-88f472eb5106" />

<img width="2233" height="1226" alt="Screenshot_2025-10-31_15-48-08(1)" src="https://github.com/user-attachments/assets/4fd03125-efa4-4dc3-8403-29b37b546679" />

---

`qobuz-cli` (or its alias `qcli`) provides a powerful and elegant way to download your purchased music or streaming library from Qobuz. It leverages modern Python features like `asyncio` for high-speed concurrent downloads and presents progress with a pretty, user-friendly interface.

## Key Features

-   **Multiple ways to log in**: Supports both `token` and `Email Password` to login.
-   **High-Speed Concurrent Downloads**: Utilizes `asyncio` to download multiple tracks simultaneously, maximizing your bandwidth.
-   **Rich, Modern UI**: Beautiful and informative progress bars and summaries powered by the Rich library.
-   **Download Everything**: Supports albums, tracks, artists, playlists, and even entire label discographies.
-   **Persistent Download Archive**: Automatically keeps track of downloaded tracks in a local database to prevent re-downloading them in future sessions.
-   **Powerful Path Templating**: Fully customize your output directory and filename structure with an easy-to-use templating system, including conditional logic.
-   **Safe and Flexible**: Supports `--dry-run` to simulate a download and reads URL lists from files or standard input (`stdin`).

## Installation

`qobuz-cli` is available on PyPI and can be installed easily with `pip`.

```bash
pip install qobuz-cli
```
or
```bash
uv pip install qobuz-cli
```

## Getting Started

### 1. Initialize Your Configuration

Before you can download, you need to authenticate with your Qobuz account. You only need to do this once. You can use either a token or your email and password.

**Option A: Authenticate with Email & Password (Recommended)**
```bash
qcli init your-email@domain.com "your-password"
```

**Option B: Authenticate with a Token**
You can find a token by inspecting the network requests in your web browser's developer tools while logged into the Qobuz web player.
```bash
qcli init <YOUR_AUTH_TOKEN>
```
This will create a `config.ini` file in your system's configuration directory.

### 2. Start Downloading

Once configured, you can start downloading by providing any Qobuz URL.

```bash
# Download a full album
qcli download https://play.qobuz.com/album/0093624949091
```

### 3. Explore Commands

Get a full list of commands and options at any time.

```bash
qcli --help
qcli download --help
```

## Usage and Examples

### Basic Downloads

```bash
# Download a single album
qcli download https://play.qobuz.com/album/abc123def456

# Download a single track
qcli download https://play.qobuz.com/track/123456789

# Download two albums using 16 workers (-w 16), using highest quality available (-q 4) with embedded art and original cover size
qcli download -w 16 -q 4 --embed-art --og-cover https://play.qobuz.com/album/0093624949091 https://play.qobuz.com/album/0093624949107

```

### Bulk Downloads

```bash
# Download an artist's complete discography, intelligently filtered
qcli download --smart https://play.qobuz.com/artist/456789

# Download a public playlist
qcli download https://play.qobuz.com/playlist/987654321

# Download all releases from a record label
qcli download https://play.qobuz.com/label/112233

# Download an artist's complete discography and keep track of the downloads in the database
qcli download --archive https://play.qobuz.com/artist/456789

```

### Advanced Downloading

```bash
# Download only full albums from a discography (skips singles/EPs)
qcli download --smart --albums-only <URL_PLACEHOLDER_ARTIST>

# Download a list of URLs from a text file (one URL per line)
qcli download urls.txt

# Download URLs piped from another command using stdin
echo "<URL_PLACEHOLDER_ALBUM>" | qcli download --stdin
```

### Customizing Your Downloads

```bash
# Download in a different quality (1=MP3 320KBPS, 2=CD 44.1KHz/16bit, 3=Hi-Res up to 96KHz/24bit, 4=Hi-Res+ up to 192KHz/24bit)
qcli download -q 3 <URL_PLACEHOLDER_ALBUM>

# Customize the output directory and filename structure
qcli download -o "{albumartist}/{album} ({year})/{tracknumber}. {tracktitle}.{ext}" <URL_PLACEHOLDER_ALBUM>

# See all available path placeholders and logic
qcli --output-help
```

### File and Artwork Options

```bash
# Embed cover art directly into each audio file's metadata and don't download separate cover.jpg file
qcli download --embed-art --no-cover  <URL_PLACEHOLDER_ALBUM>

# Download the cover art in its original resolution (not 600x600)
qcli download --og-cover <URL_PLACEHOLDER_ALBUM>
```

### Simulate a Download

Use `--dry-run` to see what the application *would* do without writing any files. This is great for testing your output templates or checking what `--smart` or `--albums-onl` will filter.

```bash
qcli download --dry-run  <URL_PLACEHOLDER_ARTIST>
```

## Commands Reference

-   `qcli init`: Initialize configuration with your Qobuz credentials.
    -   `--force`: Overwrite an existing configuration file without asking.
-   `qcli download [URLS...]`: Download music from Qobuz URLs.
    -   `-s, --smart`: Filter discographies to remove duplicate albums.
    -   `-q, --quality`: Set audio quality (1-4).
    -   `-o, --output`: Define the output path template.
    -   `--albums-only`: Download only full albums from discographies.
    -   `--archive / --no-archive`: Enable/disable the download history archive.
    -   `--dry-run`: Simulate the download process.
    -   `--stdin`: Read URLs from standard input.
-   `qcli validate`: Check that the current configuration is valid and can be loaded.
-   `qcli stats`: Show statistics from the download archive, like total tracks and top artists.
-   `qcli vacuum`: Optimize the download archive database file.
-   `qcli clear-archive`: **Permanently delete all records** from the download archive.
    -   `--force`: Bypass the confirmation prompt.
-   `qcli diagnose`: Run a series of checks for common configuration and connectivity issues.

## Output Path Templating

You have full control over your file paths. Use the `-o` or `--output` option with placeholders.

**Example Template:**
`{albumartist}/{album} ({year})/%{?is_multidisc,Disc {media_number}/|}{tracknumber}. {tracktitle}.{ext}`

**Result for a multi-disc album:**
`The Beatles/The Beatles (White Album) (1968)/Disc 1/01. Back in the U.S.S.R..flac`

**Result for a single-disc album:**
`Pink Floyd/The Dark Side of the Moon (1973)/01. Speak to Me.flac`

For a complete list of all available placeholders and a guide to conditional logic, run:
```bash
qcli --output-help
```

## Acknowledgements

This project was built with inspiration from and respect for the work done on the following repositories. They served as excellent references for understanding the Qobuz API.

-   [vitiko98/qobuz-dl](https://github.com/vitiko98/qobuz-dl)
-   [bbye98/minim](https://github.com/bbye98/minim)

## License

This project is licensed under the **GPL-3.0-or-later**. See the [LICENSE](LICENSE) file for details.
