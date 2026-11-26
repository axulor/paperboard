"""XML from the network is parsed with the standard library. Expat 2.4.1 and later refuse the
entity-expansion attacks, and ElementTree never loads external entities; these tests keep it so."""

import pyexpat

import pytest

from app.sources import SourceError
from app.sources.arxiv import parse_feed, parse_oai_record

ENTITIES = "".join(f'<!ENTITY e{i} "{f"&e{i - 1};" * 10}">' for i in range(1, 10))
BILLION_LAUGHS = f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e0 "lol">{ENTITIES}]><d>&e9;</d>'
EXTERNAL_ENTITY = (
    '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
    "<d>&secret;</d>"
)


def test_expat_is_recent_enough() -> None:
    assert pyexpat.version_info >= (2, 4, 1)


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, EXTERNAL_ENTITY])
@pytest.mark.parametrize("parse", [parse_feed, parse_oai_record])
def test_hostile_xml_is_rejected(parse: object, payload: str) -> None:
    assert callable(parse)
    with pytest.raises(SourceError, match="not valid XML"):
        parse(payload)
