"""Stand-in for the network in tests, built on httpx2.MockTransport.

    def test_x(http: MockHTTP) -> None:
        route = http.get(API_URL).mock(return_value=httpx2.Response(200, text="..."))
        async with arxiv_adapter(http) as arxiv: ...
        assert route.last_request.url.params["id_list"] == "..."

A request to a URL with no route, or to a route with nothing left to answer, fails the test.
"""

from collections.abc import Sequence
from typing import Any

import httpx2

from app.sources.arxiv import ArxivAdapter


class Route:
    def __init__(self, url: str) -> None:
        self.url = url
        self.calls: list[httpx2.Request] = []
        self._outcomes: list[httpx2.Response | Exception] = []
        self._repeat_last = False

    def mock(
        self,
        return_value: httpx2.Response | None = None,
        side_effect: Sequence[httpx2.Response | Exception] | None = None,
    ) -> "Route":
        """Answer every request with `return_value`, or the requests in turn with `side_effect`."""
        if return_value is not None:
            self._outcomes = [return_value]
            self._repeat_last = True
        elif side_effect is not None:
            self._outcomes = list(side_effect)
            self._repeat_last = False
        return self

    @property
    def called(self) -> bool:
        return bool(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def last_request(self) -> httpx2.Request:
        return self.calls[-1]

    def answer(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if not self._outcomes:
            raise AssertionError(f"no answer left for {request.method} {request.url}")
        outcome = self._outcomes[0] if self._repeat_last else self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        # A fresh copy each time: a response body can only be read once.
        return httpx2.Response(
            outcome.status_code, headers=outcome.headers, content=outcome.content
        )


class MockHTTP:
    def __init__(self) -> None:
        self.routes: dict[str, Route] = {}

    def get(self, url: str) -> Route:
        """The route for GET requests to `url`, ignoring the query string."""
        return self.routes.setdefault(url, Route(url))

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        key = f"{request.url.scheme}://{request.url.host}{request.url.path}"
        route = self.routes.get(key) if request.method == "GET" else None
        if route is None:
            raise AssertionError(f"unexpected request {request.method} {request.url}")
        return route.answer(request)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handler)


def arxiv_adapter(http: MockHTTP, **options: Any) -> ArxivAdapter:
    """An ArxivAdapter on the mock network, without waiting between requests or retries."""
    return ArxivAdapter(min_interval=0, retry_backoff=0, transport=http.transport(), **options)
