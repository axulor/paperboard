"""Find links to code, models and datasets in text, and reduce them to one URL per repository."""

import re
from collections.abc import Iterable
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel

CodeKind = Literal["repository", "model", "dataset", "space"]


class CodeLink(BaseModel):
    url: str
    host: str
    kind: CodeKind


_GIT_HOSTS = {
    "github.com": "github",
    "gitlab.com": "gitlab",
    "gitee.com": "gitee",
    "codeberg.org": "codeberg",
    "bitbucket.org": "bitbucket",
}
_HOSTS = "|".join(re.escape(h) for h in [*_GIT_HOSTS, "huggingface.co", "hf.co"])
_URL_RE = re.compile(
    rf"(?:https?://)?(?:www\.)?(?:{_HOSTS})/[^\s<>\"'(){{}}\[\]\\]+",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?'\"`"
# Paths on github.com that are not owner/repository.
_GITHUB_RESERVED = {
    "about", "collections", "contact", "customer-stories", "enterprise", "events", "explore",
    "features", "login", "marketplace", "new", "notifications", "orgs", "pricing", "search",
    "settings", "site", "sponsors", "topics", "trending",
}  # fmt: skip
_HF_NOT_REPOS = {"api", "blog", "docs", "join", "learn", "login", "models", "papers", "pricing",
                 "settings", "tasks"}  # fmt: skip


def _canonical(raw: str) -> CodeLink | None:
    url = raw.rstrip(_TRAILING)
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    segments = [s for s in parts.path.split("/") if s]

    if host in _GIT_HOSTS:
        if host == "gitlab.com":
            # GitLab groups can nest; the repository path ends where "/-/" begins.
            segments = segments[: segments.index("-")] if "-" in segments else segments
            segments = [s for s in segments if s not in {"tree", "blob"}][:3]
        else:
            segments = segments[:2]
        if len(segments) < 2:
            return None
        if host == "github.com" and segments[0].lower() in _GITHUB_RESERVED:
            return None
        segments[-1] = segments[-1].removesuffix(".git")
        path = "/".join(segments)
        return CodeLink(url=f"https://{host}/{path}", host=_GIT_HOSTS[host], kind="repository")

    if host in {"huggingface.co", "hf.co"}:
        kind: CodeKind = "model"
        if segments and segments[0] in {"datasets", "spaces"}:
            kind = "dataset" if segments[0] == "datasets" else "space"
            segments = segments[1:]
            prefix = f"{'datasets' if kind == 'dataset' else 'spaces'}/"
        else:
            prefix = ""
        if len(segments) < 2 or segments[0] in _HF_NOT_REPOS:
            return None
        path = prefix + "/".join(segments[:2])
        return CodeLink(url=f"https://huggingface.co/{path}", host="huggingface", kind=kind)

    return None


def extract_code_links(texts: Iterable[str]) -> list[CodeLink]:
    """Repository, model, dataset and space links found in `texts`, first mention first."""
    found: dict[str, CodeLink] = {}
    for text in texts:
        for match in _URL_RE.finditer(text):
            link = _canonical(match.group(0))
            if link is not None:
                found.setdefault(link.url.lower(), link)
    return list(found.values())
