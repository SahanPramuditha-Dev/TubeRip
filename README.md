# TubeRip Pro – The Professional Media Acquisition CLI

A high-performance, command-line-first YouTube downloader built with Python, yt-dlp, and SQLite. Designed for users who want power, persistence, and a clean interface without the bloat of a GUI.

## 🚀 Key Features

### 💻 Professional CLI Shell
- **ANSI Color Matrix**: Beautiful, high-contrast status reporting.
- **Interactive Shell**: A dedicated shell with command history and real-time feedback.
- **Live Progress Bars**: Multi-stage progress tracking with speed and ETA estimation.

### 🧠 Intelligence Layer
- **Smart Recommendations**: Auto-selects the best 1080p/balanced quality for any video.
- **Interruption Recovery**: Interrupted downloads can be resumed even after a system crash.
- **Clipboard Monitoring**: Automatically detects and enqueues YouTube URLs from your clipboard.
- **Analytics Dashboard**: Detailed reports on data usage, speed trends, and format popularity.

### ⚙️ Power User Tools
- **GPU Acceleration**: Hardware-accelerated video merging using NVENC/VAAPI.
- **Download Profiles**: Pre-configured presets (Best Quality, Music MP3, 1080p MP4, etc.).
- **Scheduler**: Queue downloads for a specific time in the future.
- **Playlists**: Full support for enqueuing entire playlists with one command.

---

## 🛠️ Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/TubeRip_Pro.git
cd TubeRip_Pro

# Install the package
python -m pip install --upgrade pip
python -m pip install -e .

# Optional extras
python -m pip install -e .[clipboard]  # clipboard monitoring
python -m pip install -e .[dev]        # development tools and tests
```

Alternatively, install with requirements files:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

> Note: FFmpeg is required for merging high-quality video/audio streams.

---

## 📖 Usage

Start the interactive shell after installation:
```bash
tuberip shell
```

If you prefer a direct repository invocation:
```bash
python main.py shell
```

### Common Commands
- `search "query"`: Find videos and pick one to download.
- `download <URL> --interactive`: Pick format and settings manually.
- `monitor`: Start the background clipboard listener.
- `resume`: Interactively pick and resume interrupted jobs.
- `analytics`: View your download statistics.

---

## 🏗️ Architecture
- `models/`: Typed dataclasses for Jobs and Metadata.
- `database/`: SQLite layer for history, profiles, and state.
- `downloader/`: Multi-threaded engine with retry logic and GPU support.
- `metadata/`: Robust extraction layer using yt-dlp.

---

## 📜 License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
