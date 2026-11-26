import pytest

from app.sources.codelinks import extract_code_links


@pytest.mark.parametrize(
    ("text", "url", "host", "kind"),
    [
        (
            "Code: https://github.com/mistralai/mistral-src",
            "https://github.com/mistralai/mistral-src",
            "github",
            "repository",
        ),
        (
            "see https://github.com/org/repo/tree/main/src.",
            "https://github.com/org/repo",
            "github",
            "repository",
        ),
        (
            "(https://www.github.com/Org/Repo.git)",
            "https://github.com/Org/Repo",
            "github",
            "repository",
        ),
        (
            "available at github.com/org/repo, and",
            "https://github.com/org/repo",
            "github",
            "repository",
        ),
        (
            "https://gitlab.com/group/sub/project/-/blob/main/x.py",
            "https://gitlab.com/group/sub/project",
            "gitlab",
            "repository",
        ),
        ("https://gitee.com/owner/name", "https://gitee.com/owner/name", "gitee", "repository"),
        (
            "https://huggingface.co/mistralai/Mixtral-8x7B-v0.1",
            "https://huggingface.co/mistralai/Mixtral-8x7B-v0.1",
            "huggingface",
            "model",
        ),
        (
            "https://huggingface.co/datasets/org/data/viewer",
            "https://huggingface.co/datasets/org/data",
            "huggingface",
            "dataset",
        ),
        (
            "https://hf.co/spaces/org/demo",
            "https://huggingface.co/spaces/org/demo",
            "huggingface",
            "space",
        ),
    ],
)
def test_extracts_and_canonicalizes(text: str, url: str, host: str, kind: str) -> None:
    [link] = extract_code_links([text])
    assert (link.url, link.host, link.kind) == (url, host, kind)


@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/mistralai",
        "https://github.com/features/copilot",
        "https://huggingface.co/papers/2401.04088",
        "https://huggingface.co/docs/transformers",
        "https://mistral.ai/news/mixtral-of-experts/",
        "https://example.github.io/project",
    ],
)
def test_ignores_links_that_are_not_repositories(text: str) -> None:
    assert extract_code_links([text]) == []


def test_keeps_first_mention_once() -> None:
    links = extract_code_links(
        [
            "https://github.com/org/repo and https://github.com/org/repo/issues/1",
            "also https://GitHub.com/org/repo.git and https://huggingface.co/org/model",
        ]
    )
    assert [link.url for link in links] == [
        "https://github.com/org/repo",
        "https://huggingface.co/org/model",
    ]
