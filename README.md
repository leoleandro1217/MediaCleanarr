# 🎬 MediaCleanarr

**Clean media filenames. Keep your library organized. Stay in control.**

MediaCleanarr is a self-hosted, Docker-ready web application for cleaning **movie and TV-series release filenames** on your NAS. Browse your existing folders, preview the proposed filenames, make corrections, and apply only the renames you approve.

Built with **UGREEN NAS** in mind, but designed to work with any Linux Docker host that can mount a media directory.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Version](https://img.shields.io/badge/version-0.2.0--alpha-orange)
![License](https://img.shields.io/badge/license-not%20yet%20selected-lightgrey)

> **Development preview (v0.2 alpha).** Test on a small, backed-up directory first. The project has not yet been validated on an actual UGREEN NAS. **No rename happens without your explicit confirmation.**

## ✨ Features

- 📁 **Built-in folder explorer:** browse Movies, Series, Anime, or any other directories mounted under `/media`.
- 🎞️ **Release-name cleanup:** remove the clutter from scene/release names using filename parsing.
- 🌍 **Optional metadata lookups:**
  - **OMDb** for movie catalogue titles, using your API key.
  - **TheTVDB** for TV-series names, with a default-title option or requested translation (English, French, German, Spanish, Italian, Portuguese, Japanese, Korean, Chinese, Dutch, Polish).
  - **TMDB** retained as an optional additional provider.
- 👀 **Review before rename:** scan a selected folder, inspect/edit candidates, and select which files to rename.
- 🛡️ **No overwrite:** the rename operation attempts an exclusive hardlink before deleting the original filename. If the destination already exists or hardlinks are unsupported, it fails instead of replacing a file.
- ↩️ **History and batch undo:** store renaming history in a local SQLite database; undo when the original filename is still available.
- 🗂️ **Files only:** no folder moves or folder renaming. No transcoding.
- 🐳 **Docker Compose:** persistent local data and configurable NAS media mount.

## 🔎 Before and after

| Release filename | Proposed cleaned filename |
|---|---|
| `The.Dark.Knight.2008.1080p.BluRay.x264-GROUP.mkv` | `The Dark Knight (2008).mkv` |
| `Breaking.Bad.S01E02.1080p.BluRay-GROUP.mkv` | `Breaking Bad - S01E02.mkv` |

The examples illustrate intended results, **not guaranteed automatic recognition**. Metadata matches are conservative, and titles in other languages may not be found.

## 🚀 Quick start (Docker / UGREEN NAS)

**1. Clone**

```bash
git clone https://github.com/leoleandro1217/MediaCleanarr.git
cd MediaCleanarr
```

**2. Configure**

```bash
cp .env.example .env
```

Edit `docker-compose.yml` to change the host path **`/volume1/media`** to the real absolute media-share path on your NAS.

For example, mount a common parent containing:

```text
/media/
├── Films/
├── Series/
├── Anime/
└── Series Anime/
```

The path inside the container is always `/media`. Only the source path on the left of the volume mapping needs to match your NAS.

Add optional API credentials to `.env`; **never commit your real `.env` file**.

**3. Build and start**

```bash
docker compose up -d --build
```

**4. Open the web interface**

```text
http://YOUR-NAS-IP:8088
```

Browse to a folder, choose a content type and an optional metadata provider, click **Analyser ce dossier**, review/edit the results, and explicitly confirm the selected renames.

You can also import the Compose configuration in a Docker-compatible NAS management interface.

## 🔑 Optional metadata configuration

In your local `.env`:

```dotenv
OMDB_API_KEY=
TVDB_API_KEY=
TVDB_SUBSCRIBER_PIN=
TMDB_API_KEY=
SECRET_KEY=replace-with-a-long-random-string
```

| Provider | Intended use | Important limitations |
|---|---|---|
| **OMDb** | Movie titles and year | Its `Title` is the **catalogue title**, *not* a reliable original-language-title field. Foreign-language aliases may not match. |
| **TheTVDB** | TV-series titles by preferred language | `original` uses the **default/main series title**, which is not guaranteed to be the original broadcast-language title. Unavailable translations do not silently fall back. |
| **TMDB** | Additional movie/series lookups | Matches are conservative; check all proposed names. |

TheTVDB API access may be subject to account, subscriber PIN or licensing requirements. Only configured and selected providers are queried. Your API keys stay on the server.

**Anime-series metadata integration is postponed**; simple season/episode parsing is supported where the source filename contains recognizable episode tags. Files using absolute episode numbering may require manual handling.

## 🧰 Usage and safety

1. Start with a **small backup/test folder**.
2. Browse to the folder you want; scanning subfolders is optional.
3. Pick **Movies**, **Series**, **Anime series**, or **Auto**.
4. Pick **No metadata** for local parsing, or OMDb/TheTVDB/TMDB when configured.
5. Inspect matches and correct any wrong filenames.
6. Confirm selected items only. See **History** to reverse a batch if the files have not moved or been renamed again.

**Important limitations:**
- Supports common video extensions only. Subtitles, extras and folder names are not renamed or synchronized.
- The rename method requires source and target to support **hardlinks on the same filesystem**. Unsupported NAS shares will report an error.
- There is no login/authentication in this alpha. **Trusted LAN only. Never expose port 8088 directly to the public internet.** Add access control before remote access.
- Scans are limited to 10,000 video files per request.
- The history database lives in `./data/history.sqlite3` and should be backed up if you need to retain the undo history.
- Lookups, parsing and translations are imperfect. **This is not a fully automated catalogue manager.**

## 🗺️ Roadmap

- [x] Docker web UI and folder explorer
- [x] Simple movie / TV naming
- [x] Preview, selective apply, batch undo
- [x] Optional OMDb and TheTVDB lookup
- [ ] Automated tests and NAS compatibility verification
- [ ] Better ambiguous-title matching and manual catalogue selection
- [ ] Improved anime episode numbering and metadata
- [ ] Authentication and safer remote access
- [ ] Additional configurable naming templates

## 🤝 Contributing

Bug reports, feature ideas and pull requests are welcome. Please avoid including personal media paths, API credentials, or copyrighted media files in issues and commits.

**Maintained in:** [leoleandro1217/MediaCleanarr](https://github.com/leoleandro1217/MediaCleanarr)

**License:** Not selected yet. Until a license is added, repository visibility does not grant general redistribution or modification rights.
