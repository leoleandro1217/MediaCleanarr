"""MediaCleanarr: local-first media filename cleaner, with explicit review before renaming."""
import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request
from guessit import guessit

app = Flask(__name__)
ROOT = Path(os.getenv("MEDIA_ROOT", "/media")).resolve()
DB = Path(os.getenv("DATABASE_PATH", "/data/history.sqlite3"))
EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".wmv", ".ts", ".m2ts", ".webm", ".mpg", ".mpeg", ".iso"}
LOCK = threading.RLock()
OMDB_KEY = os.getenv("OMDB_API_KEY", "").strip()
TVDB_KEY = os.getenv("TVDB_API_KEY", "").strip()
TVDB_PIN = os.getenv("TVDB_SUBSCRIBER_PIN", "").strip()
TMDB_KEY = os.getenv("TMDB_API_KEY", "").strip()
LANGUAGES = {"en": "eng", "fr": "fra", "de": "deu", "es": "spa", "it": "ita", "pt": "por", "ja": "jpn", "ko": "kor", "zh": "zho", "nl": "nld", "pl": "pol"}
TVDB_TOKEN = None
TVDB_TOKEN_TIME = 0
TVDB_AUTH_LOCK = threading.Lock()


def normalize(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def clean_title(s):
    s = str(s or "").replace("_", " ").replace(".", " ")
    s = re.sub(r"\s+", " ", s).strip(" -._")
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", s).strip(" .")


def safe_path(rel=""):
    if not isinstance(rel, str) or "\x00" in rel:
        raise ValueError("Invalid path")
    path = (ROOT / rel.lstrip("/")).resolve(strict=False)
    if not path.is_relative_to(ROOT):
        raise ValueError("Path outside the media share")
    return path


def relative(path):
    return path.relative_to(ROOT).as_posix() if path != ROOT else ""


@lru_cache(maxsize=2048)
def omdb_lookup(title, year=None):
    """OMDb Title is the catalogue title; it is not guaranteed to be original-language."""
    if not OMDB_KEY or not title:
        return None
    try:
        params = {"apikey": OMDB_KEY, "s": title, "type": "movie"}
        if year:
            params["y"] = str(year)
        r = requests.get("https://www.omdbapi.com/", params=params, timeout=8)
        r.raise_for_status()
        candidates = r.json().get("Search", [])
        if not candidates:
            return None
        best = max(candidates, key=lambda x: similarity(title, x.get("Title", "")))
        yr = str(best.get("Year", ""))[:4]
        if similarity(title, best.get("Title")) < .82 or (year and yr.isdigit() and abs(int(yr) - year) > 1):
            return None
        r = requests.get("https://www.omdbapi.com/", params={"apikey": OMDB_KEY, "i": best.get("imdbID"), "type": "movie"}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if data.get("Response") != "True" or data.get("Type") != "movie":
            return None
        yr = str(data.get("Year", ""))[:4]
        return {"title": data.get("Title"), "year": int(yr) if yr.isdigit() else None, "source": "OMDb catalogue", "id": data.get("imdbID")}
    except (requests.RequestException, ValueError, TypeError):
        return None


def tvdb_auth():
    global TVDB_TOKEN, TVDB_TOKEN_TIME
    if not TVDB_KEY:
        return None
    with TVDB_AUTH_LOCK:
        if TVDB_TOKEN and time.time() < TVDB_TOKEN_TIME + 24 * 3600:
            return TVDB_TOKEN
        credentials = {"apikey": TVDB_KEY}
        if TVDB_PIN:
            credentials["pin"] = TVDB_PIN
        r = requests.post("https://api4.thetvdb.com/v4/login", json=credentials, timeout=8)
        r.raise_for_status()
        token = (r.json().get("data") or {}).get("token")
        if not token:
            raise ValueError("TheTVDB login failed")
        TVDB_TOKEN, TVDB_TOKEN_TIME = token, time.time()
        return token


def tvdb_get(endpoint, params=None):
    token = tvdb_auth()
    if not token:
        return None
    r = requests.get("https://api4.thetvdb.com/v4" + endpoint, params=params,
                     headers={"Authorization": "Bearer " + token}, timeout=8)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("data")


@lru_cache(maxsize=2048)
def tvdb_lookup(title, language="original"):
    if not TVDB_KEY or not title:
        return None
    try:
        candidates = tvdb_get("/search", {"query": title, "type": "series", "limit": 20}) or []
        if not isinstance(candidates, list) or not candidates:
            return None

        def score(item):
            names = [item.get("name"), item.get("nameTranslations")]
            names += item.get("aliases", []) if isinstance(item.get("aliases"), list) else []
            matches = []
            for name in names:
                if isinstance(name, str):
                    matches.append(name)
                elif isinstance(name, dict):
                    matches.extend(v for v in name.values() if isinstance(v, str))
                elif isinstance(name, list):
                    matches.extend(v for v in name if isinstance(v, str))
            return max((similarity(title, n) for n in matches), default=0)

        best = max(candidates, key=score)
        if score(best) < .82:
            return None
        series_id = best.get("tvdb_id") or best.get("id")
        if not series_id or not str(series_id).isdigit():
            return None
        record = tvdb_get(f"/series/{series_id}") or {}
        name = record.get("name") or best.get("name")
        source = "TheTVDB default title"
        if language != "original":
            translated = tvdb_get(f"/series/{series_id}/translations/{language}") or {}
            if not translated.get("name"):
                return None
            name = translated["name"]
            source = f"TheTVDB {language}"
        return {"title": name, "source": source, "id": series_id} if name else None
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


@lru_cache(maxsize=2048)
def tmdb_lookup(title, kind, year=None):
    if not TMDB_KEY or not title:
        return None
    endpoint = "tv" if kind == "episode" else "movie"
    params = {"api_key": TMDB_KEY, "query": title, "language": "en-US"}
    if year and kind == "movie":
        params["year"] = year
    try:
        r = requests.get(f"https://api.themoviedb.org/3/search/{endpoint}", params=params, timeout=8)
        r.raise_for_status()
        results = r.json().get("results", [])[:10]
        if not results:
            return None
        best = max(results, key=lambda item: similarity(title, item.get("name") or item.get("title")))
        name = best.get("name") or best.get("title")
        if similarity(title, name) < .84:
            return None
        release = best.get("first_air_date") if kind == "episode" else best.get("release_date")
        return {"title": name, "year": int(release[:4]) if release and release[:4].isdigit() else None, "source": "TMDB English"}
    except (requests.RequestException, ValueError, TypeError):
        return None


def proposal(path, category="auto", provider="none", language="original"):
    parsed = guessit(path.name)
    kind = "episode" if "episode" in parsed or "season" in parsed else "movie"
    if category in {"series", "anime-series"}:
        kind = "episode"
    elif category == "movies":
        kind = "movie"
    title = clean_title(parsed.get("title") or path.stem)
    if not title:
        return None, "Title not detected", None
    try:
        year = int(parsed["year"]) if parsed.get("year") else None
    except (ValueError, TypeError):
        year = None
    metadata = None
    if category != "anime-series":
        if provider == "omdb" and kind == "movie":
            metadata = omdb_lookup(title, year)
        elif provider == "tvdb" and kind == "episode":
            metadata = tvdb_lookup(title, language)
        elif provider == "tmdb":
            metadata = tmdb_lookup(title, kind, year)
    if metadata:
        title = clean_title(metadata["title"])
        if kind == "movie" and not year:
            year = metadata.get("year")
    if kind == "episode":
        season, episode = parsed.get("season"), parsed.get("episode")
        if isinstance(episode, list):
            return None, "Multiple episodes: manual naming required", metadata
        if season is None or episode is None:
            return None, "Season or episode not detected", metadata
        try:
            name = f"{title} - S{int(season):02d}E{int(episode):02d}{path.suffix}"
        except (ValueError, TypeError):
            return None, "Invalid episode number", metadata
    else:
        if not year:
            return None, "Year not detected", metadata
        name = f"{title} ({year}){path.suffix}"
    return name, None, metadata


def initialize_database():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, time TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0)")


initialize_database()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/browse")
def browse():
    try:
        directory = safe_path(request.args.get("path", ""))
        if not directory.is_dir():
            return jsonify(error="Folder not found"), 404
        folders = sorted((p for p in directory.iterdir() if p.is_dir() and not p.is_symlink()), key=lambda p: p.name.casefold())
        return jsonify(path=relative(directory),
                       parent=relative(directory.parent) if directory != ROOT else None,
                       directories=[{"name": p.name, "path": relative(p)} for p in folders])
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/scan")
def scan():
    params = request.get_json(silent=True) or {}
    try:
        directory = safe_path(params.get("path", ""))
        if not directory.is_dir():
            return jsonify(error="Folder not found"), 404
        recursive = bool(params.get("recursive", True))
        category = params.get("category", "auto")
        provider = params.get("provider", "none")
        language = params.get("language", "original")
        if category not in {"auto", "movies", "series", "anime-series"}:
            return jsonify(error="Invalid category"), 400
        if provider not in {"none", "omdb", "tvdb", "tmdb"} or language not in {"original", *LANGUAGES.values()}:
            return jsonify(error="Invalid metadata provider or language"), 400
        if provider == "omdb" and category not in {"movies", "auto"}:
            return jsonify(error="OMDb supports movies"), 400
        if provider == "tvdb" and category not in {"series", "auto"}:
            return jsonify(error="TheTVDB supports series"), 400
        keys = {"omdb": OMDB_KEY, "tvdb": TVDB_KEY, "tmdb": TMDB_KEY}
        if provider != "none" and not keys[provider]:
            return jsonify(error="The selected provider needs an API key"), 400
        files = directory.rglob("*") if recursive else directory.iterdir()
        rows = []
        for path in files:
            if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                continue
            effective = provider
            if category == "auto" and provider in {"omdb", "tvdb"}:
                guessed = guessit(path.name)
                is_episode = "episode" in guessed or "season" in guessed
                if (provider == "omdb" and is_episode) or (provider == "tvdb" and not is_episode):
                    effective = "none"
            name, error, metadata = proposal(path, category, effective, language)
            target = path.with_name(name) if name else None
            status = "skip" if error or name == path.name else "ready"
            if target and target != path and target.exists():
                status, error = "conflict", "Destination already exists"
            rows.append({"source": relative(path), "name": path.name, "proposed": name,
                         "status": status, "reason": error or ("Already clean" if name == path.name else ""),
                         "metadata": metadata,
                         "lookup": "not_found" if effective != "none" and not metadata else "matched" if metadata else "off"})
            if len(rows) >= 10000:
                return jsonify(error="Scan limit of 10,000 videos reached; select a smaller folder"), 400
        return jsonify(rows=rows, total=len(rows))
    except (ValueError, OSError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/rename")
def rename():
    params = request.get_json(silent=True) or {}
    items = params.get("items", [])
    if not isinstance(items, list) or len(items) > 10000:
        return jsonify(error="Invalid selection"), 400
    batch = uuid.uuid4().hex[:12]
    successes, errors = [], []
    with LOCK, sqlite3.connect(DB) as conn:
        for item in items:
            try:
                if not isinstance(item, dict):
                    raise ValueError("Invalid item")
                source = safe_path(item.get("source"))
                name = item.get("proposed")
                if not isinstance(name, str) or name in {"", ".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
                    raise ValueError("Invalid destination filename")
                if not source.is_file() or source.is_symlink() or source.suffix.lower() not in EXTENSIONS:
                    raise ValueError("Video not found")
                if Path(name).suffix.lower() != source.suffix.lower():
                    raise ValueError("Video extension cannot be changed")
                target = source.with_name(name)
                if target == source:
                    continue
                # Linux hardlink creation fails when target exists, preventing overwrites.
                os.link(source, target, follow_symlinks=False)
                try:
                    os.unlink(source)
                except Exception:
                    os.unlink(target)
                    raise
                conn.execute("INSERT INTO history(batch,time,source,target) VALUES(?,?,?,?)",
                             (batch, datetime.now(timezone.utc).isoformat(), relative(source), relative(target)))
                conn.commit()
                successes.append({"source": relative(source), "target": relative(target)})
            except (ValueError, OSError, TypeError) as exc:
                errors.append({"source": item.get("source", "") if isinstance(item, dict) else "", "error": str(exc)})
    return jsonify(batch=batch, renamed=successes, errors=errors)


@app.get("/api/history")
def history():
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        entries = conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT 500").fetchall()
    return jsonify(rows=[dict(row) for row in entries])


@app.post("/api/undo")
def undo():
    params = request.get_json(silent=True) or {}
    batch = params.get("batch")
    if not isinstance(batch, str) or not re.fullmatch(r"[0-9a-f]{12}", batch):
        return jsonify(error="Invalid batch"), 400
    successes, errors = [], []
    with LOCK, sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM history WHERE batch=? AND undone=0 ORDER BY id DESC", (batch,)).fetchall():
            try:
                original, current = safe_path(row["source"]), safe_path(row["target"])
                if not current.is_file() or current.is_symlink():
                    raise ValueError("Renamed file not found")
                os.link(current, original, follow_symlinks=False)
                try:
                    os.unlink(current)
                except Exception:
                    os.unlink(original)
                    raise
                conn.execute("UPDATE history SET undone=1 WHERE id=?", (row["id"],))
                conn.commit()
                successes.append(row["source"])
            except (ValueError, OSError) as exc:
                errors.append({"target": row["target"], "error": str(exc)})
    return jsonify(restored=successes, errors=errors)


@app.get("/api/health")
def health():
    return jsonify(ok=ROOT.is_dir(), media_root=str(ROOT)), 200 if ROOT.is_dir() else 503


@app.get("/api/providers")
def providers():
    return jsonify(omdb=bool(OMDB_KEY), tvdb=bool(TVDB_KEY), tmdb=bool(TMDB_KEY), languages=LANGUAGES)
