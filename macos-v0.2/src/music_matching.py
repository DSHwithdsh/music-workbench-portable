"""Read-only catalogue/lyrics matching. Never uploads audio or writes music."""
from __future__ import annotations

import dataclasses
from difflib import SequenceMatcher
import email.utils
import json
import random
import re
import threading
import time
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKC", str(value)).casefold() if c.isalnum())


def similarity(a, b):
    a, b = normalized(a), normalized(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def candidate_score(local, candidate):
    title = similarity(local["title"], candidate.get("title", ""))
    artist = similarity(local["artist"], candidate.get("artist", ""))
    album = similarity(local.get("album", ""), candidate.get("album", ""))
    duration = float(candidate.get("duration") or 0)
    delta = abs(float(local.get("duration") or 0) - duration) if duration else 9999
    duration_score = max(0.0, 1.0 - delta / 10)
    score = 0.50 * title + 0.30 * artist + 0.10 * album + 0.10 * duration_score
    strict = title >= 0.94 and artist >= 0.90 and delta <= 3 and score >= 0.90
    return round(score, 4), strict


def ranked(local, candidates):
    result = []
    for candidate in candidates:
        candidate = dict(candidate)
        candidate["score"], candidate["ready"] = candidate_score(local, candidate)
        result.append(candidate)
    result.sort(key=lambda x: (x["score"], bool(x.get("syncedLyrics"))), reverse=True)
    if len(result) > 1 and result[0]["score"] - result[1]["score"] < 0.02:
        # Identical duplicate records are harmless; different releases require review.
        first, second = result[:2]
        if normalized(first.get("album")) != normalized(second.get("album")) or abs(first.get("duration", 0) - second.get("duration", 0)) > 1:
            result[0]["ready"] = False
            result[0]["review_reason"] = "存在接近的其他版本，请确认候选"
    return result


class MatchCancelled(Exception):
    pass


class PublicClient:
    def __init__(self, stop=None):
        self.stop = stop or threading.Event()
        self.last_request = 0.0
        self.last_by_host = {}
        self.blocked_until = {}
        self.cache = {}

    def wait(self, seconds):
        if self.stop.wait(max(0, seconds)):
            raise MatchCancelled("已停止匹配")

    def get(self, host, path, params=None):
        url = host + path + (("?" + urlencode(params)) if params else "")
        if url in self.cache:
            return self.cache[url]
        if self.blocked_until.get(host, 0) > time.monotonic():
            raise RuntimeError("来源正在限流，请稍后重试")
        for attempt in range(2):
            interval = 3.1 if host == "https://itunes.apple.com" else 0.7
            self.wait(max(0.2 - (time.monotonic() - self.last_request),
                          interval - (time.monotonic() - self.last_by_host.get(host, 0))))
            self.last_request = time.monotonic()
            self.last_by_host[host] = self.last_request
            try:
                request = Request(url, headers={
                    "User-Agent": "MusicWorkbench/0.2 (https://github.com/DSHwithdsh/music-workbench-portable)",
                    "Accept": "application/json"})
                with urlopen(request, timeout=18) as response:
                    content_type = response.headers.get("Content-Type", "").lower()
                    if "json" not in content_type and not (host == "https://itunes.apple.com" and "javascript" in content_type):
                        raise RuntimeError("来源没有返回 JSON")
                    data = json.loads(response.read(12 * 1024 * 1024).decode("utf-8"))
                self.cache[url] = data
                return data
            except HTTPError as exc:
                if exc.code == 404:
                    self.cache[url] = None
                    return None
                if exc.code not in (429, 503):
                    raise RuntimeError(f"来源请求失败：HTTP {exc.code}") from exc
                retry = exc.headers.get("Retry-After", "2")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = email.utils.parsedate_to_datetime(retry).timestamp() - time.time()
                    except (TypeError, ValueError):
                        delay = 2
                delay = max(1, delay) * (1 + random.random() * 0.1)
                self.blocked_until[host] = time.monotonic() + delay
                if attempt or delay > 10:
                    raise RuntimeError(f"来源暂时繁忙，请在 {int(delay) + 1} 秒后重试") from exc
                self.wait(delay)
        raise RuntimeError("来源暂时不可用")


class Matcher:
    def __init__(self, country="gb", stop=None, client=None):
        self.stop = stop or threading.Event()
        self.country = country
        self.client = client or PublicClient(self.stop)

    def metadata(self, local, query=""):
        data = self.client.get("https://itunes.apple.com", "/search", {
            "term": query or (local["title"] + " " + local["artist"]).strip(),
            "country": self.country, "media": "music", "entity": "song", "limit": 20})
        candidates = []
        for item in (data or {}).get("results", []):
            if item.get("kind") != "song":
                continue
            candidates.append({"provider": "Apple 目录", "id": str(item["trackId"]),
                "title": item.get("trackName", ""), "artist": item.get("artistName", ""),
                "album": item.get("collectionName", ""), "albumartist": item.get("artistName", ""),
                "date": item.get("releaseDate", "")[:10], "genre": item.get("primaryGenreName", ""),
                "tracknumber": str(item.get("trackNumber", "")), "discnumber": str(item.get("discNumber", "")),
                "duration": (item.get("trackTimeMillis") or 0) / 1000,
                "artworkUrl100": item.get("artworkUrl100", ""), "url": item.get("trackViewUrl", "")})
        return ranked(local, candidates)

    def lyrics(self, local):
        data = self.client.get("https://lrclib.net", "/api/search", {
            "q": (local["title"] + " " + local["artist"]).strip()}) or []
        if not isinstance(data, list):
            raise RuntimeError("歌词来源返回格式异常")
        candidates = []
        for item in data:
            candidates.append({"provider": "LRCLIB", "id": str(item["id"]),
                "title": item.get("trackName", ""), "artist": item.get("artistName", ""),
                "album": item.get("albumName", ""), "duration": float(item.get("duration") or 0),
                "instrumental": bool(item.get("instrumental")),
                "syncedLyrics": item.get("syncedLyrics") or "", "plainLyrics": item.get("plainLyrics") or "",
                "url": "https://lrclib.net/api/get/" + str(item["id"])})
        return ranked(local, candidates)

    def match(self, local, query=""):
        result = {"metadata_candidates": [], "lyrics_candidates": [], "metadata": None, "lyric": None, "errors": []}
        if not local.get("title"):
            result["errors"].append("缺少歌名，请先填写检索词")
            return result
        try:
            result["metadata_candidates"] = self.metadata(local, query)
            if result["metadata_candidates"]:
                result["metadata"] = result["metadata_candidates"][0]
        except MatchCancelled:
            raise
        except Exception as exc:
            result["errors"].append("标签检索：" + str(exc))
        if local.get("lyrics") or local.get("sidecar_lyrics"):
            text = local.get("lyrics") or local["sidecar_lyrics"]
            result["lyric"] = {"provider": "现有歌词", "id": "local", "ready": True, "score": 1.0,
                               "syncedLyrics": text if is_synced(text) else "", "plainLyrics": text}
        else:
            try:
                result["lyrics_candidates"] = self.lyrics(local)
                if result["lyrics_candidates"]:
                    result["lyric"] = result["lyrics_candidates"][0]
            except MatchCancelled:
                raise
            except Exception as exc:
                result["errors"].append("歌词检索：" + str(exc))
        return result


def is_synced(text):
    return bool(re.search(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]", text or ""))


def lyric_text(candidate):
    if not candidate or candidate.get("instrumental"):
        return "", "纯音乐" if candidate and candidate.get("instrumental") else "无匹配"
    synced = candidate.get("syncedLyrics", "")
    if is_synced(synced):
        return synced, "同步 LRC"
    return candidate.get("plainLyrics", ""), "纯文本"
