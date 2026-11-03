"""Public catalogue metadata; no Apple account/token is used here."""
import json
import re
import subprocess
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


def request_json(endpoint, parameters):
    url = "https://itunes.apple.com/" + endpoint + "?" + urlencode(parameters)
    request = Request(url, headers={"User-Agent": "MusicWorkbench/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read(8 * 1024 * 1024).decode("utf-8"))


def lookup(query, country="us", entity="album"):
    query = query.strip()
    if query.startswith("https://"):
        parts = urlsplit(query)
        if parts.netloc.lower() != "music.apple.com":
            raise ValueError("请使用 music.apple.com 的链接")
        if "/playlist/" in parts.path:
            return {"mode": "playlist", "items": [], "country": country, "url": query}
        match = re.search(r"/(album|song)/(?:[^/]+/)?(\d+)(?:/|$)", parts.path)
        if not match:
            raise ValueError("无法识别专辑或单曲 ID")
        parts_country = parts.path.strip("/").split("/")[0]
        if re.fullmatch(r"[a-z]{2}", parts_country):
            country = parts_country
        single = parse_qs(parts.query).get("i", [None])[0]
        identifier = single or match[2]
        kind = "song" if single or match[1] == "song" else "album"
        results = request_json("lookup", {"id": identifier, "country": country, "entity": "song", "limit": 200}).get("results", [])
        return {"mode": kind, "items": results, "country": country, "url": query}
    results = request_json("search", {"term": query, "country": country, "entity": entity, "media": "music", "limit": 40}).get("results", [])
    return {"mode": "search", "items": results, "country": country, "url": ""}


def item_url(item, country="us", track=False):
    key = "trackId" if track else "collectionId"
    identifier = item.get(key)
    if not identifier:
        raise ValueError("目录没有返回可用的音乐 ID")
    if track:
        album = item.get("collectionId")
        if album:
            return f"https://music.apple.com/{country}/album/id/{album}?i={identifier}"
        return f"https://music.apple.com/{country}/song/id/{identifier}"
    return f"https://music.apple.com/{country}/album/id/{identifier}"


def artwork_png(item, ffmpeg, size=180):
    url = item.get("artworkUrl100", "")
    if not url:
        return None
    url = re.sub(r"\d+x\d+bb", "400x400bb", url).replace("http://", "https://", 1)
    host = urlsplit(url).hostname or ""
    if not host.endswith(".mzstatic.com"):
        return None
    with urlopen(Request(url, headers={"User-Agent": "MusicWorkbench/1.0"}), timeout=20) as response:
        data = response.read(12 * 1024 * 1024)
    result = subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-i", "pipe:0",
                             "-vf", f"scale={size}:{size}", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                            input=data, capture_output=True, timeout=25,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.stdout if result.returncode == 0 else None
