"""
Offline checks for the Gemini context cleaner. No Google calls.

Run from backend/:  python tests/test_llm_context.py
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import llm_context  # noqa: E402


def test_prompt_keeps_five_sentences_and_the_new_one():
    context = [f"sentence {i}" for i in range(1, 8)]
    prompt = llm_context.build_prompt("ubata kiyanna", "si-LK", context)
    assert "ubata kiyanna" in prompt
    assert "sentence 3" in prompt
    assert "sentence 7" in prompt
    assert "sentence 1" not in prompt
    assert "sentence 2" not in prompt
    assert "ubata" in prompt
    assert "preserve uncertainty rather than guessing" in prompt
    assert '"sinhala"' in prompt and '"english"' in prompt and '"tamil"' in prompt


def test_parse_plain_and_fenced_json():
    plain = llm_context.parse_caption(
        '{"sinhala": "ඔබට කියන්න", "english": "Let me tell you", "tamil": "உங்களிடம் சொல்கிறேன்"}'
    )
    assert plain is not None
    assert plain.sinhala.startswith("ඔබට")
    fenced = llm_context.parse_caption(
        '```json\n{"sinhala": "ආයුබෝවන්", "english": "Hello", "tamil": "வணக்கம்"}\n```'
    )
    assert fenced is not None and fenced.english == "Hello"


def test_parse_rejects_garbage_and_empty():
    assert llm_context.parse_caption("not json") is None
    assert llm_context.parse_caption('{"sinhala": "", "english": "", "tamil": ""}') is None
    assert llm_context.parse_caption("") is None
    assert llm_context.parse_caption('["nope"]') is None


def test_clean_sentence_returns_model_json_without_calling_google():
    llm_context._generate_sync = lambda prompt: (
        '{"sinhala": "නිල වාක්‍යය", "english": "A formal sentence", "tamil": "முறையான வாக்கியம்"}'
    )
    caption = asyncio.run(llm_context.clean_sentence("ubata", "si-LK", ["පෙර වාක්‍යය"]))
    assert caption is not None
    assert caption.english == "A formal sentence"
    assert "පෙර වාක්‍යය" in llm_context.build_prompt("ubata", "si-LK", ["පෙර වාක්‍යය"])


def test_clean_sentence_failure_is_none():
    def boom(_prompt):
        raise TimeoutError("slow")

    llm_context._generate_sync = boom
    assert asyncio.run(llm_context.clean_sentence("hello", "en-US", [])) is None


def test_permission_denied_does_not_retry_every_sentence():
    llm_context._down_until = 0.0
    llm_context._down_logged = False
    calls = {"n": 0}

    def denied(_prompt):
        calls["n"] += 1
        raise RuntimeError("403 PERMISSION_DENIED SERVICE_DISABLED")

    llm_context._generate_sync = denied
    try:
        assert asyncio.run(llm_context.clean_sentence("one", "en-US", [])) is None
        assert asyncio.run(llm_context.clean_sentence("two", "en-US", [])) is None
        assert calls["n"] == 1
    finally:
        llm_context._down_until = 0.0
        llm_context._down_logged = False


def test_disabled_or_blank_skips_the_model():
    called = {"n": 0}

    def spy(_prompt):
        called["n"] += 1
        return '{"sinhala": "x", "english": "y", "tamil": "z"}'

    llm_context._generate_sync = spy
    assert asyncio.run(llm_context.clean_sentence("   ", "si-LK", [])) is None
    llm_context.config.LLM_ENABLED = False
    try:
        assert asyncio.run(llm_context.clean_sentence("hello", "en-US", [])) is None
    finally:
        llm_context.config.LLM_ENABLED = True
    assert called["n"] == 0


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"{len(tests)} passed")


if __name__ == "__main__":
    main()
