# qobuz-cli

[![PyPI Version](https://img.shields.io/pypi/v/qobuz-cli.svg)](https://pypi.org/project/qobuz-cli)

A fast, concurrent command-line music downloader for Qobuz.

<img width="2233" height="1226" alt="Screenshot_2025-10-31_15-46-06" src="https://github.com/user-attachments/assets/8de1e460-76ed-4301-a4c2-88f472eb5106" />

<img width="2233" height="1226" alt="Screenshot_2025-10-31_15-48-08(1)" src="https://github.com/user-attachments/assets/4fd03125-efa4-4dc3-8403-29b37b546679" />

---

`qobuz-cli` (alias `qcli`) downloads music from your Qobuz account or library from the command line. It uses `asyncio` to download several tracks at once and shows progress with a Rich-based interface.

## Features

- Token-based login using your Qobuz auth token.
- Concurrent downloads with a configurable number of workers.
- Progress bars and session summaries powered by Rich.
- Support for albums, tracks, artists, playlists, and label discographies.
- Digital booklet (PDF) download when an album provides one.
- Synced lyrics from LRCLIB, embedded in tags or written as `.lrc` files.
- Optional ReplayGain tags (track gain and peak) from Qobuz.
- A local archive that records downloaded tracks so they are not fetched again.
- Path templating for full control over folder and file names, including conditional logic.
- A `--dry-run` mode, plus reading URL lists from files or standard input.

## Installation

`qobuz-cli` is on PyPI:

```bash
pip install qobuz-cli
```

or

```bash
uv pip install qobuz-cli
```

## Getting Started

### 1. Initialize your configuration

You need to authenticate once before downloading. Qobuz has blocked direct email and password logins for third-party applications, so `qobuz-cli` authenticates with the auth token from your browser session.

#### How to get your auth token

1. Open the [Qobuz Web Player](https://play.qobuz.com/) in your browser and log in.
2. Press `F12` to open the developer tools.
3. Go to the **Application** tab (Chrome or Edge) or the **Storage** tab (Firefox).
4. In the left sidebar, expand **Local Storage** and select `https://play.qobuz.com`.
5. Find the **`localuser`** key.
6. Expand its JSON value and copy the **`token`** string.

Then run:

```bash
qcli init <YOUR_AUTH_TOKEN>
```

This fetches the required API secrets from the Qobuz web player and writes a `config.ini` file to your system configuration directory.

<details>
<summary>Advanced: provide the app ID and secret manually</summary>

If the automatic secret fetch fails, for example after Qobuz changes their web player, you can supply the app credentials yourself. Both flags are required together:

```bash
qcli init <YOUR_AUTH_TOKEN> --app-id <APP_ID> --app-secret <APP_SECRET>
```

</details>

### 2. Start downloading

Pass any Qobuz URL to the `download` command:

```bash
qcli download https://play.qobuz.com/album/0093624949091
```

### 3. Explore the commands

```bash
qcli --help
qcli download --help
```

## Usage and Examples

### Basic downloads

```bash
# Download a single album
qcli download https://play.qobuz.com/album/abc123def456

# Download a single track
qcli download https://play.qobuz.com/track/123456789

# Download two albums with 16 workers at the highest quality,
# embedding art and using the original cover size
qcli download -w 16 -q 4 --embed-art --og-cover \
  https://play.qobuz.com/album/0093624949091 \
  https://play.qobuz.com/album/0093624949107
```

### Bulk downloads

```bash
# Download an artist's discography, filtered to remove duplicate albums
qcli download --smart https://play.qobuz.com/artist/456789

# Download a public playlist
qcli download https://play.qobuz.com/playlist/987654321

# Download every release from a record label
qcli download https://play.qobuz.com/label/112233

# Download a discography and record it in the archive
qcli download --archive https://play.qobuz.com/artist/456789
```

### Advanced downloading

```bash
# Download only full albums from a discography (skip singles and EPs)
qcli download --smart --albums-only https://play.qobuz.com/artist/456789

# Download a list of URLs from a text file, one URL per line
qcli download urls.txt

# Download URLs piped from another command
echo "https://play.qobuz.com/album/abc123def456" | qcli download --stdin

# Download only the album booklet PDF, skipping audio
qcli download --booklet-only https://play.qobuz.com/album/abc123def456
```

### Customizing your downloads

```bash
# Choose a quality (1: MP3 320, 2: CD 16/44.1, 3: Hi-Res 24/96, 4: Hi-Res+ 24/192)
qcli download -q 3 https://play.qobuz.com/album/abc123def456

# Set the output folder and file name structure
qcli download -o "{albumartist}/{album} ({year})/{tracknumber}. {tracktitle}.{ext}" \
  https://play.qobuz.com/album/abc123def456

# List every path placeholder and the conditional syntax
qcli --output-help
```

### Lyrics and ReplayGain

```bash
# Fetch synced lyrics from LRCLIB and embed them in tags
qcli download --lyrics https://play.qobuz.com/album/abc123def456

# Write lyrics as both embedded tags and a separate .lrc file
qcli download --lyrics --lyrics-mode both https://play.qobuz.com/album/abc123def456

# Write Qobuz ReplayGain tags to the downloaded files
qcli download --replaygain https://play.qobuz.com/album/abc123def456
```

### File and artwork options

```bash
# Embed cover art in each file and skip the separate cover.jpg
qcli download --embed-art --no-cover https://play.qobuz.com/album/abc123def456

# Download cover art at its original resolution instead of 600x600
qcli download --og-cover https://play.qobuz.com/album/abc123def456
```

### Simulate a download

Use `--dry-run` to see what the app would do without writing files. This is useful for testing output templates or checking what `--smart` or `--albums-only` will filter.

```bash
qcli download --dry-run https://play.qobuz.com/artist/456789
```

## Commands Reference

- `qcli init <TOKEN>`: Set up the configuration with your Qobuz auth token.
  - `--force`: Overwrite an existing configuration file without asking.
  - `--app-id` / `--app-secret`: Provide the API credentials manually instead of fetching them (both required together).
- `qcli download [URLS...]`: Download music from Qobuz URLs or from files containing URLs.
  - `-q, --quality`: Set the audio quality (1 to 4).
  - `-w, --workers`: Number of simultaneous downloads (default 8).
  - `-o, --output`: Set the output path template.
  - `-s, --smart`: Filter discographies to remove duplicate albums.
  - `--albums-only`: Download only full albums from discographies.
  - `--embed-art` / `--no-cover` / `--og-cover`: Control cover art handling.
  - `--lyrics` and `--lyrics-mode`: Fetch synced lyrics (embed, lrc, or both).
  - `--replaygain`: Write ReplayGain tags.
  - `--booklet-only`: Download only the album booklet PDF.
  - `--no-fallback`: Skip a track if the requested quality is unavailable instead of downgrading.
  - `--no-m3u`: Do not create a `.m3u` file when downloading a playlist.
  - `--archive / --no-archive`: Enable or disable the download archive.
  - `--dry-run`: Simulate the download without writing files.
  - `--stdin`: Read URLs from standard input.
- `qcli validate`: Check that the current configuration is valid and can be loaded.
- `qcli stats`: Show archive statistics, such as total tracks and top artists.
- `qcli vacuum`: Optimize the archive database file.
- `qcli clear-archive`: Delete all records from the download archive.
  - `--force`: Skip the confirmation prompt.
- `qcli diagnose`: Run checks for common configuration and connectivity issues.

## Output Path Templating

Use the `-o` or `--output` option with placeholders to control file paths.

Example template:

`{albumartist}/{album} ({year})/%{?is_multidisc,Disc {media_number}/|}{tracknumber}. {tracktitle}.{ext}`

Result for a multi-disc album:

`The Beatles/The Beatles (White Album) (1968)/Disc 1/01. Back in the U.S.S.R..flac`

Result for a single-disc album:

`Pink Floyd/The Dark Side of the Moon (1973)/01. Speak to Me.flac`

For the full list of placeholders and the conditional syntax, run:

```bash
qcli --output-help
```

## Acknowledgements

This project was built with reference to the following repositories, which were helpful for understanding the Qobuz API:

- [vitiko98/qobuz-dl](https://github.com/vitiko98/qobuz-dl)
- [bbye98/minim](https://github.com/bbye98/minim)

## License

This project is licensed under the GPL-3.0-or-later. See the [LICENSE](LICENSE) file for details.
