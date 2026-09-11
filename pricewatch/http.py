"""One HTTP client for the whole swarm.

Responsibilities: browser-like headers, cookie persistence per host, a polite per-host
throttle, and retries on transient failures. Every agent goes through `Client.get`.
"""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 PriceWatch/0.1",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class Client:
    def __init__(
        self,
        min_interval: float = 0.0,
        timeout: float = 10.0,
        retries: int = 2,
        *,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=32)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.min_interval = min_interval  # seconds between requests to the same host
        self.timeout = timeout
        self.retries = retries
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        throttle_key = host
        interval = self.min_interval
        if "/stores/zon" in url:
            throttle_key = f"{host}/zon"
            interval = max(interval, 1.0)
        elif "/stores/shield" in url:
            throttle_key = f"{host}/shield"
            interval = max(interval, 1.0)

        with self._lock:
            wait = self._last.get(throttle_key, 0) + interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last[throttle_key] = self._clock()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        kw.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle(url)
            try:
                r = self.session.request(method, url, **kw)
            except requests.RequestException as e:  # network blip
                last_exc = e
                self._sleep(0.5 * (attempt + 1))
                continue
            
            if r.status_code == 503 and "Checking your browser before accessing Shield" in r.text and attempt < self.retries:
                import hashlib
                from bs4 import BeautifulSoup
                from urllib.parse import urljoin
                soup = BeautifulSoup(r.text, "html.parser")
                cf = soup.find(id="cf-c")
                if cf and "data-s" in cf.attrs and "data-p" in cf.attrs:
                    s = cf["data-s"]
                    p = cf["data-p"]
                    a = hashlib.sha256(f"{s}|{p}".encode()).hexdigest()[:16]
                    
                    self._sleep(float(r.headers.get("Retry-After", "1")))
                    challenge_url = urljoin(url, "/stores/shield/challenge")
                    post_r = self.session.post(challenge_url, json={"s": s, "p": p, "a": a})
                    continue

            if r.status_code in (429, 503) and attempt < self.retries:
                self._sleep(float(r.headers.get("Retry-After", "1")))
                continue
            return r
        if last_exc:
            raise last_exc
        return r  # type: ignore[possibly-undefined]

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> requests.Response:
        return self.request("POST", url, **kw)
