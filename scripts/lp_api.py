"""Small client for Liquipedia's LiquipediaDB API (v3), used by fetch_cs2.py.

Rules it enforces (Liquipedia API terms: at most 60 requests per hour, cache everything, no scraping):
- a hard cap on requests per run (max_requests) and a rolling per-hour limit (per_hour) with a short gap
  between requests;
- HTTP 429: wait (Retry-After, else 15 minutes) and try again, at most `retries_429` times, then stop the run
  with RateLimited so the caller keeps what it has and continues next time;
- the key is read from LIQUIPEDIA_API_KEY and is never printed.
"""
import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

BASE = "https://api.liquipedia.net/api/v3/"
PAGE = 1000  # rows per request (the API's maximum page size)


class StopRun(Exception):
    """The run should stop now and keep what it has (budget used up or rate limited)."""


class BudgetUsed(StopRun):
    pass


class RateLimited(StopRun):
    pass


class ApiError(Exception):
    pass


def _decode(body):
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body.decode("utf-8", "replace")


class Client:
    def __init__(self, wiki, key=None, contact=None, max_requests=40, per_hour=45, min_gap=2.0,
                 retries_429=2, sleep=time.sleep, clock=time.monotonic, opener=None, log=print, max_seconds=None):
        self.wiki = wiki
        self.key = key if key is not None else os.environ.get("LIQUIPEDIA_API_KEY", "")
        if not self.key:
            raise ApiError("LIQUIPEDIA_API_KEY is not set")
        contact = contact if contact is not None else os.environ.get("CONTACT_EMAIL", "")
        self.ua = ("techrul.github.io rankings (https://github.com/Techrul/techrul.github.io"
                   + (f"; {contact}" if contact else "") + ")")
        self.max_requests, self.per_hour, self.min_gap, self.retries_429 = max_requests, per_hour, min_gap, retries_429
        self.sleep, self.clock, self.log = sleep, clock, log
        self.opener = opener or urllib.request.urlopen
        self.sent = 0
        self._times = deque()
        self.deadline = clock() + max_seconds if max_seconds else None

    def _sleep_until(self, seconds):
        if self.deadline is not None and self.clock() + seconds > self.deadline:
            raise BudgetUsed("time limit for this run reached")
        self.sleep(seconds)

    # -- pacing -------------------------------------------------------------------------------------------
    def _wait_turn(self):
        if self.sent >= self.max_requests:
            raise BudgetUsed(f"request budget for this run used ({self.max_requests})")
        now = self.clock()
        while self._times and now - self._times[0] >= 3600:
            self._times.popleft()
        if len(self._times) >= self.per_hour:
            wait = 3600 - (now - self._times[0]) + 1
            self.log(f"  pacing: {self.per_hour} requests in the last hour, waiting {wait / 60:.0f} min")
            self._sleep_until(wait)
            return self._wait_turn()
        if self._times and now - self._times[-1] < self.min_gap:
            self._sleep_until(self.min_gap - (now - self._times[-1]))
        if self.deadline is not None and self.clock() > self.deadline:
            raise BudgetUsed("time limit for this run reached")

    # -- one request ----------------------------------------------------------------------------------------
    def get(self, datapoint, **params):
        params = {"wiki": self.wiki, **{k: v for k, v in params.items() if v is not None}}
        url = BASE + datapoint + "?" + urllib.parse.urlencode(params)
        headers = {"Authorization": f"Apikey {self.key}", "Accept-Encoding": "gzip", "User-Agent": self.ua}
        for attempt in range(self.retries_429 + 1):
            self._wait_turn()
            self.sent += 1
            self._times.append(self.clock())
            try:
                with self.opener(urllib.request.Request(url, headers=headers), timeout=90) as r:
                    text = _decode(r.read())
            except urllib.error.HTTPError as e:
                text = _decode(e.read())
                if e.code == 429:
                    retry = e.headers.get("Retry-After")
                    wait = int(retry) if retry and retry.isdigit() else 900
                    if attempt < self.retries_429:
                        self.log(f"  HTTP 429 (rate limited), waiting {wait / 60:.0f} min before retrying")
                        self._sleep_until(wait)
                        continue
                    raise RateLimited(f"HTTP 429 after {self.retries_429} retries: {text[:200]}")
                raise ApiError(f"HTTP {e.code} for {datapoint}: {text[:500]}")
            except (urllib.error.URLError, TimeoutError) as e:
                raise ApiError(f"network error for {datapoint}: {e}")
            try:
                data = json.loads(text)
            except ValueError:
                raise ApiError(f"not JSON from {datapoint}: {text[:300]}")
            if isinstance(data, dict) and data.get("error"):
                raise ApiError(f"API error for {datapoint}: {data['error']}")
            for w in (data.get("warning") or []) if isinstance(data, dict) else []:
                self.log(f"  API warning: {w}")
            return data.get("result", []) if isinstance(data, dict) else data
        raise RateLimited("rate limited")  # not reached

    # -- all pages ------------------------------------------------------------------------------------------
    def get_all(self, datapoint, conditions, query=None, order="objectname ASC"):
        """Every row matching `conditions`, paging by PAGE. Raises StopRun if the budget runs out mid-way
        (the caller then keeps nothing from this call, so a half-fetched window is never saved as complete)."""
        rows, offset = [], 0
        while True:
            page = self.get(datapoint, conditions=conditions, query=query, order=order, limit=PAGE, offset=offset)
            rows.extend(page)
            if len(page) < PAGE:
                return rows
            offset += PAGE
