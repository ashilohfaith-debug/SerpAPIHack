"""Tests for Perplexity Computer knowledge engine and offline research fallback."""

from unittest.mock import patch

from relay.intent import Kind, parse
from relay.session import Session
from relay.system.knowledge import KnowledgeEngine, _clean_for_speech, _clean_query


def test_clean_query_strips_fillers():
    assert _clean_query("who is Albert Einstein") == "Albert Einstein"
    assert _clean_query("what is photosynthesis?") == "photosynthesis"
    assert _clean_query("tell me about the moon.") == "the moon"
    assert _clean_query("research quantum computing") == "quantum computing"
    assert _clean_query("google latest news") == "latest news"


def test_clean_for_speech_normalizes_unicode():
    assert _clean_for_speech("Sk\u0142odowska") == "Sklodowska"
    assert _clean_for_speech("caf\u00e9") == "cafe"


def test_summarize_text_extractive():
    engine = KnowledgeEngine()
    text = (
        "Quantum computing is a rapidly-emerging technology that harnesses the laws of quantum mechanics to solve problems too complex for classical computers. "
        "These machines are very different from the classical computers that have been around for more than half a century. "
        "Here is some unrelated fluff. And another random line. "
        "Quantum processors can evaluate massive computational spaces simultaneously."
    )
    summary = engine.summarize_text(text, max_sentences=2)
    assert "Quantum" in summary
    assert len(summary) > 30


def test_knowledge_grammar_routing():
    p1 = parse("who is Albert Einstein")
    assert p1.kind == Kind.ASK
    assert "Albert Einstein" in p1.slots.get("text", "")

    p2 = parse("what is the capital of France")
    assert p2.kind == Kind.ASK

    p3 = parse("research quantum computers")
    assert p3.kind == Kind.ASK


def test_session_ask_knowledge_fallback():
    spoken = []
    session = Session(speak=lambda t: spoken.append(t), db_path=":memory:", assistant=None)
    try:
        # Mock knowledge engine answer
        with patch.object(session.knowledge, "answer", return_value="Albert Einstein was a physicist who developed relativity."):
            session.handle("who is Albert Einstein")
            assert any("Albert Einstein was a physicist" in t for t in spoken)
    finally:
        session.close()


def test_session_summarize_fallback():
    spoken = []
    session = Session(speak=lambda t: spoken.append(t), db_path=":memory:", assistant=None)
    try:
        page_content = (
            "Relay is an accessibility-first voice computer designed for blind users. "
            "It controls native Windows applications, web services, and systems through pure voice. "
            "It never requires looking at the screen."
        )
        with patch.object(session.skills, "_document", return_value=("Relay Page", page_content)):
            session.handle("summarize this page")
            assert any("Here is a summary" in t for t in spoken)
    finally:
        session.close()
