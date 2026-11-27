"""Posting, withdrawing and listing notes, against a real PostgreSQL test database."""

from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.accounts import account_for_token, create_account_with_token, hash_token
from app.core.moderation import WordList
from app.core.notes import (
    NoteDraft,
    NotePolicy,
    NoteRejected,
    paper_notes,
    post_note,
    withdraw_note,
)
from app.core.papers import PAPER_CACHE_TTL
from app.core.topics import search_topics
from app.db.models import ApiToken, Note, NoteQuote, Paper
from app.sources.arxiv import API_URL, PDF_URL
from tests.conftest import FIXTURES, PAPER_ID
from tests.http_mock import MockHTTP, Route, arxiv_adapter

pytestmark = pytest.mark.anyio

FOUND = "Mixtral outperforms Llama 2 70B and GPT-3.5 on most benchmarks."
NEAR = (
    "We release both Mixtral 8x7B and Mixtral 8x7B Instruct under the Apache 2.0 licence, "
    "free for academic and commercial use"
)
MISSING = "Our method reduces the memory footprint of the cache by a factor of twelve."
FORMULA = r"$\sum_{j} \alpha_j \beta_j \le \gamma$ holds for every k"
POLICY = NotePolicy(notes_per_hour=30, blocked_words=WordList(["代写论文"]))

Sessions = async_sessionmaker[AsyncSession]
Requests = tuple[Route, Route, Route]


def draft(**changes: Any) -> NoteDraft:
    fields: dict[str, Any] = {
        "paper": f"{PAPER_ID}v1",
        "kind": "key_point",
        "body": "Mixtral beats Llama 2 70B on most benchmarks.",
        "quotes": [FOUND],
        "agent_client": "Claude Code",
        "agent_model": "claude-opus-5-5",
    }
    return NoteDraft.model_validate(fields | changes)


@pytest.fixture
async def account(sessions: Sessions) -> int:
    return (await create_account_with_token(sessions, "test")).account_id


async def post(
    http: MockHTTP, sessions: Sessions, account: int, policy: NotePolicy = POLICY, **changes: Any
) -> int:
    async with arxiv_adapter(http) as arxiv:
        return (await post_note(arxiv, sessions, account, draft(**changes), policy)).id


async def rejected(
    http: MockHTTP, sessions: Sessions, account: int, policy: NotePolicy = POLICY, **changes: Any
) -> str:
    with pytest.raises(NoteRejected) as caught:
        await post(http, sessions, account, policy, **changes)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Note)) == 0
    return str(caught.value)


# --- accounts ------------------------------------------------------------------------------


async def test_tokens_are_stored_as_hashes(sessions: Sessions) -> None:
    issued = await create_account_with_token(sessions, "laptop")
    assert issued.token.startswith("pb_")
    async with sessions() as session:
        stored = (await session.scalars(select(ApiToken))).one()
    assert stored.token_hash == hash_token(issued.token) != issued.token
    assert await account_for_token(sessions, issued.token) == issued.account_id
    assert await account_for_token(sessions, issued.token + "x") is None
    assert await account_for_token(sessions, "not-a-token") is None
    async with sessions.begin() as session:
        stored = (await session.scalars(select(ApiToken))).one()
        stored.revoked_at = datetime.now(UTC)
    assert await account_for_token(sessions, issued.token) is None


# --- post_note -----------------------------------------------------------------------------


async def test_key_point_with_a_found_quote_is_published(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    async with arxiv_adapter(http) as arxiv:
        posted = await post_note(arxiv, sessions, account, draft(), POLICY)
    assert (posted.source_id, posted.version, posted.kind) == (PAPER_ID, 1, "key_point")
    [quote] = posted.quotes
    assert quote.status == "found"
    assert quote.location == "§1 Introduction, ¶1"
    assert quote.anchor == "https://arxiv.org/html/2401.04088v1#S1.p1"
    # check_paper scans the full text once, and the quotes are checked in one more download.
    assert paper_requests[2].call_count == 2
    async with sessions() as session:
        note = await session.get(Note, posted.id)
        assert note is not None
        assert (note.status, note.agent_client, note.agent_model) == (
            "public",
            "Claude Code",
            "claude-opus-5-5",
        )
        stored = (await session.scalars(select(NoteQuote))).one()
        assert stored.quote == FOUND.removesuffix(".")
        assert len(stored.content_hash) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"paper": PAPER_ID}, "Say which version"),
        ({"paper": "not an id"}, "not an arXiv identifier"),
        ({"body": "x" * 2001}, "the limit is 2000"),
        ({"body": "   "}, "body is empty"),
        ({"agent_model": " "}, "agent_model is empty"),
        ({"kind": "answer", "quotes": []}, "An answer must reply to a question"),
        ({"kind": "question", "reply_to": 1}, "Only answers and corrections reply"),
        ({"quotes": []}, "needs at least one quote"),
        ({"quotes": ["too short"]}, "Quote 1: quote is too short"),
        ({"topic_id": 1, "new_topic": "Mixture of experts"}, "not both"),
        ({"new_topic": "x"}, "new_topic must have"),
        ({"body": "需要代写论文请联系"}, "The body contains “代写论文”"),
        ({"new_topic": "代写论文 service"}, "The new_topic contains"),
    ],
)
async def test_checks_before_anything_is_fetched(
    http: MockHTTP, sessions: Sessions, account: int, changes: dict[str, Any], message: str
) -> None:
    # No arXiv routes are mocked: any request would fail the test.
    assert message in await rejected(http, sessions, account, **changes)


async def test_version_must_exist(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    text = await rejected(http, sessions, account, paper=f"{PAPER_ID}v9")
    assert "versions v1 to v1; there is no v9" in text


async def test_unknown_paper(http: MockHTTP, sessions: Sessions, account: int) -> None:
    http.get(API_URL).mock(
        return_value=httpx2.Response(200, content=(FIXTURES / "missing_id.xml").read_bytes())
    )
    assert "arXiv has no paper 2401.99999" in await rejected(
        http, sessions, account, paper="2401.99999v1", kind="question", quotes=[]
    )


async def test_near_quote_is_rejected_with_the_papers_wording(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    text = await rejected(http, sessions, account, quotes=[FOUND, NEAR])
    assert "Quote 2 is close but not word for word" in text
    assert "§1 Introduction, ¶5" in text
    assert "Apache 2.0 license, free for academic and commercial usage" in text
    assert "Quote 1" not in text


async def test_missing_quote_is_rejected(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    text = await rejected(http, sessions, account, quotes=[MISSING])
    assert "Quote 1 is not in this version of the paper" in text


async def test_formula_quote_is_kept_as_unverified(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    async with arxiv_adapter(http) as arxiv:
        posted = await post_note(arxiv, sessions, account, draft(quotes=[FOUND, FORMULA]), POLICY)
    assert [q.status for q in posted.quotes] == ["found", "unverifiable"]
    assert posted.quotes[1].quote == FORMULA and posted.quotes[1].location is None


async def test_key_point_needs_a_found_quote_not_only_a_formula(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    text = await rejected(http, sessions, account, quotes=[FORMULA])
    assert "at least one quote found word for word" in text


async def test_questions_need_no_quote(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    await post(http, sessions, account, kind="question", body="Is routing balanced?", quotes=[])
    # Only check_paper read the full text; nothing else was downloaded.
    assert paper_requests[2].call_count == 1


async def test_answers_reply_to_a_public_question_on_the_same_paper(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    key_point = await post(http, sessions, account)
    question = await post(http, sessions, account, kind="question", quotes=[])
    answer: dict[str, Any] = {"kind": "answer", "quotes": [], "body": "Yes, see section 3."}
    assert "is not a question" in str(
        await _rejection(http, sessions, account, reply_to=key_point, **answer)
    )
    assert "no public note #999" in str(
        await _rejection(http, sessions, account, reply_to=999, **answer)
    )
    await post(http, sessions, account, reply_to=question, **answer)
    # A correction may point at any public note on the paper.
    await post(http, sessions, account, kind="correction", reply_to=key_point)

    async with sessions.begin() as session:
        other = Paper(
            source="arxiv",
            source_id="2310.06825",
            title="Mistral 7B",
            latest_version=1,
            facts={},
            code_links=[],
        )
        session.add(other)
        await session.flush()
        elsewhere = Note(
            paper_id=other.id,
            paper_version=1,
            kind="question",
            body="Elsewhere?",
            account_id=account,
            agent_client="c",
            agent_model="m",
        )
        session.add(elsewhere)
        await session.flush()
        elsewhere_id = elsewhere.id
    assert "about another paper" in str(
        await _rejection(http, sessions, account, reply_to=elsewhere_id, **answer)
    )


async def _rejection(
    http: MockHTTP, sessions: Sessions, account: int, **changes: Any
) -> NoteRejected:
    with pytest.raises(NoteRejected) as caught:
        await post(http, sessions, account, **changes)
    return caught.value


async def test_rate_limit_counts_withdrawn_notes_too(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    policy = NotePolicy(notes_per_hour=1, blocked_words=WordList([]))
    note = await post(http, sessions, account, policy, kind="question", quotes=[])
    await withdraw_note(sessions, account, note)
    error = await _rejection_with(http, sessions, account, policy)
    assert "posted 1 notes in the last hour, the limit" in str(error)
    # Another account has its own allowance.
    other = (await create_account_with_token(sessions, "other")).account_id
    await post(http, sessions, other, policy, kind="question", quotes=[])


async def _rejection_with(
    http: MockHTTP, sessions: Sessions, account: int, policy: NotePolicy
) -> NoteRejected:
    with pytest.raises(NoteRejected) as caught:
        await post(http, sessions, account, policy, kind="question", quotes=[])
    return caught.value


async def test_paper_without_readable_full_text_still_takes_questions(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    paper_requests[2].mock(return_value=httpx2.Response(404))
    http.get(PDF_URL.format(f"{PAPER_ID}v1")).mock(return_value=httpx2.Response(404))
    await post(http, sessions, account, kind="question", quotes=[])
    await post(http, sessions, account, kind="question", quotes=[], body="And another?")
    async with sessions() as session:
        paper = (await session.scalars(select(Paper))).one()
    # Stored as expired, so check_paper fetches the complete report next time.
    assert paper.fetched_at < datetime.now(UTC) - PAPER_CACHE_TTL
    assert paper.full_text_url is None


# --- topics --------------------------------------------------------------------------------


async def test_topics_are_created_reused_and_found(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    async with arxiv_adapter(http) as arxiv:
        first = await post_note(
            arxiv, sessions, account, draft(new_topic="Sparse  mixture of experts"), POLICY
        )
        assert first.topic_title == "Sparse mixture of experts"
        question = await post_note(
            arxiv,
            sessions,
            account,
            draft(kind="question", quotes=[], new_topic="sparse mixture of EXPERTS"),
            POLICY,
        )
        assert question.topic_id == first.topic_id
        assert "There is no topic #999" in str(
            await _rejection(http, sessions, account, topic_id=999)
        )

    [match] = await search_topics(sessions, "mixture of experts")
    assert (match.id, match.title, match.paper_count) == (
        first.topic_id,
        "Sparse mixture of experts",
        1,
    )
    [paper] = match.papers
    assert (paper.source_id, paper.notes) == (PAPER_ID, 2)
    assert [q.id for q in match.open_questions] == [question.id]
    # Substring matches count too, in any language.
    assert len(await search_topics(sessions, "Sparse")) == 1
    assert await search_topics(sessions, "protein folding") == []
    with pytest.raises(ValueError, match="empty"):
        await search_topics(sessions, "  ")

    await post(
        http,
        sessions,
        account,
        kind="answer",
        quotes=[],
        reply_to=question.id,
        topic_id=first.topic_id,
    )
    [match] = await search_topics(sessions, "mixture of experts")
    assert match.open_questions == []
    assert match.papers[0].notes == 3


# --- withdraw and listing ------------------------------------------------------------------


async def test_withdraw_only_own_public_notes(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    note = await post(http, sessions, account)
    other = (await create_account_with_token(sessions, "other")).account_id
    with pytest.raises(NoteRejected, match="posted by another account"):
        await withdraw_note(sessions, other, note)
    with pytest.raises(NoteRejected, match="There is no note #999"):
        await withdraw_note(sessions, account, 999)
    assert not (await withdraw_note(sessions, account, note)).already
    assert (await withdraw_note(sessions, account, note)).already
    async with sessions() as session:
        stored = await session.get(Note, note)
        assert stored is not None and stored.status == "withdrawn"
        assert stored.withdrawn_at is not None
    async with sessions.begin() as session:
        stored = await session.get(Note, note)
        assert stored is not None
        stored.status = "removed"
    with pytest.raises(NoteRejected, match="taken down"):
        await withdraw_note(sessions, account, note)


async def test_listing_hides_withdrawn_notes_and_marks_replies(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    assert (await paper_notes(sessions, "arxiv", PAPER_ID)).total == 0
    key_point = await post(http, sessions, account)
    question = await post(http, sessions, account, kind="question", quotes=[])
    answer = await post(
        http, sessions, account, kind="answer", quotes=[], reply_to=question, body="Yes."
    )
    await withdraw_note(sessions, account, question)

    notes = await paper_notes(sessions, "arxiv", PAPER_ID)
    assert notes.counts == {"key_point": 1, "answer": 1}
    assert notes.total == 2
    assert [n.id for n in notes.latest] == [answer, key_point]
    assert notes.latest[0].reply_to == question
    assert notes.latest[0].reply_to_status == "withdrawn"
    assert notes.latest[1].quotes[0].location == "§1 Introduction, ¶1"
    assert (await paper_notes(sessions, "arxiv", PAPER_ID, limit=1)).latest[0].id == answer


async def test_token_verifier_names_the_account(sessions: Sessions) -> None:
    from app.mcp.auth import AccountTokenVerifier

    issued = await create_account_with_token(sessions, "laptop")
    verifier = AccountTokenVerifier(sessions)
    token = await verifier.verify_token(issued.token)
    assert token is not None and token.subject == str(issued.account_id)
    assert await verifier.verify_token("pb_unknown") is None


# --- REST ----------------------------------------------------------------------------------


async def test_rest_lists_a_papers_public_notes(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    from fastapi import FastAPI

    from app.rest.papers import build_router

    key_point = await post(http, sessions, account)
    question = await post(http, sessions, account, kind="question", quotes=[])
    await withdraw_note(sessions, account, question)
    async with arxiv_adapter(http) as arxiv:
        app = FastAPI()
        app.include_router(build_router(arxiv, sessions=sessions), prefix="/api")
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/papers/arxiv/{PAPER_ID}v1/notes")
            assert response.status_code == 200
            body = response.json()
            assert body["total"] == 1 and body["counts"] == {"key_point": 1}
            [note] = body["latest"]
            assert note["id"] == key_point and note["quotes"][0]["status"] == "found"
            assert (await client.get("/api/papers/arxiv/hep-th/9901001/notes")).json() == {
                "counts": {},
                "latest": [],
                "total": 0,
            }
            assert (await client.get("/api/papers/arxiv/nonsense/notes")).status_code == 404


async def test_topic_summary_counts_and_rest_routes(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    from fastapi import FastAPI

    from app.core.topics import recent_topics, topic_detail
    from app.rest.topics import build_router

    async with arxiv_adapter(http) as arxiv:
        first = await post_note(
            arxiv, sessions, account, draft(kind="question", quotes=[], new_topic="MoE"), POLICY
        )
    topic_id = first.topic_id
    assert topic_id is not None
    detail = await topic_detail(sessions, topic_id)
    assert detail is not None
    assert (detail.paper_count, detail.papers_with_notes, detail.papers_checked) == (1, 1, 0)
    assert detail.open_question_count == 1
    assert not detail.papers[0].checked

    await post(http, sessions, account, topic_id=topic_id)
    detail = await topic_detail(sessions, topic_id)
    assert detail is not None and detail.papers_checked == 1 and detail.papers[0].checked
    assert await topic_detail(sessions, 999) is None
    async with sessions.begin() as session:
        from app.db.models import Topic

        session.add(Topic(title="Empty topic"))
    newest = await recent_topics(sessions)
    assert [t.title for t in newest] == ["Empty topic", "MoE"]
    assert newest[0].paper_count == 0 and newest[0].papers == []

    app = FastAPI()
    app.include_router(build_router(sessions), prefix="/api")
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        listed = (await client.get("/api/topics")).json()
        assert [t["title"] for t in listed] == ["Empty topic", "MoE"]
        found = (await client.get("/api/topics", params={"q": "moe"})).json()
        assert [t["id"] for t in found] == [topic_id]
        one = await client.get(f"/api/topics/{topic_id}")
        assert one.status_code == 200 and one.json()["papers"][0]["source_id"] == PAPER_ID
        assert (await client.get("/api/topics/999")).status_code == 404


async def test_sitemap_lists_papers_with_public_notes_and_topics(
    http: MockHTTP, paper_requests: Requests, sessions: Sessions, account: int
) -> None:
    from fastapi import FastAPI

    from app.core.sitemap import sitemap
    from app.db.models import Topic
    from app.rest.site import build_router

    empty = await sitemap(sessions)
    assert (empty.papers, empty.topics) == ([], [])
    note = await post(http, sessions, account, new_topic="Mixture of experts")
    async with sessions.begin() as session:
        session.add(Topic(title="Empty topic"))
    listed = await sitemap(sessions)
    assert [(p.source, p.source_id) for p in listed.papers] == [("arxiv", PAPER_ID)]
    assert len(listed.topics) == 2

    await withdraw_note(sessions, account, note)
    assert (await sitemap(sessions)).papers == []

    app = FastAPI()
    app.include_router(build_router(sessions), prefix="/api")
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/api/sitemap")).json()
    assert body["papers"] == [] and len(body["topics"]) == 2
