"""
Offline checks for the caption content filter (no Google calls).

Run from backend/:  python tests/test_content_filter.py
Run this after every edit to blocklist.json.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from content_filter import content_filter  # noqa: E402

MUST_BLOCK = [
    # Sinhala: formal sexual terms, every form and compound
    "ලිංගිකත්වය පිළිබඳ දේශනය", "ලිංගිකව", "ලිංගික අධ්‍යාපනය", "ලිංගය", "ලිංගභේදය",
    "සමලිංගික", "ද්විලිංගික", "ස්ත්‍රී ලිංගය", "පුරුෂ ලිංගය", "ලිංගේන්ද්‍රිය",
    "සංසර්ගය", "සම්භෝගය", "මෛථුනය", "රමණය", "කාමුකත්වය", "කාමය", "කාමාතුර",
    "යෝනිය", "ශිෂ්නය", "පියයුරු", "තනපුඩු", "ශුක්‍රාණු", "නිරුවත්", "නග්න", "නිර්වස්ත්‍ර",
    "ස්වයංවින්දනය", "අසභ්‍ය", "අශ්ලීල", "අතවරය", "ස්ත්‍රී දූෂණය", "ළමා දූෂණය", "රති ක්‍රීඩා",
    "වේශ්‍යාවක්", "ගණිකාව", "සෙක්ස්", "පෝර්න්", "නිල් චිත්‍රපට",
    # Sinhala: profanity and insults
    "ඔයා පකයා", "පකෝ", "පුකේ", "හුත්තා", "හුත්තිගෙ", "හුකන්න", "හුකපන්", "අම්මට හුකන",
    "වේසිගේ පුතා", "කැරියා", "ලබ්බ", "කිම්බ", "පයිය", "බැල්ලි", "පොන්නයා", "සල්ලාලයා",
    "මෝඩයා", "බූරුවා", "තක්කඩියා", "අවජාතකයා",
    # Sinhala: recogniser spelling variants, invisible joiners, split words
    "ළිංගික", "ලීංගික", "ලිඟික", "වේෂ්‍යා", "වේශ්යාවක්", "ස්ත්රී දූෂණය", "හුත් තා", "ලිං ගික", "සම ලිංගික",
    # Tamil
    "இது பாலியல் கல்வி", "பாலுறவு", "உடலுறவு", "ஆணுறுப்பு", "மார்பகம்", "விந்து", "யோனி",
    "ஓரினச்சேர்க்கை", "கள்ளக்காதல்", "விபச்சாரம்", "நிர்வாணம்", "கற்பழிப்பு", "பலாத்காரம்", "ஆபாசம்",
    "தேவடியா மகன்", "புண்டை", "ஓத்த", "சுன்னி", "கூதி", "முட்டாள்", "தகாத உறவு", "பாலியள்",
    # English and romanised
    "what the fuck", "motherfucker", "f*** this", "sexual harassment", "sexuality", "homosexual",
    "naked", "bullshit", "porn", "huththa", "pakaya", "pundai", "lingika", "blow job", "stupid",
]

MUST_PASS = [
    # Event and everyday Sinhala
    "විභාග දෙපාර්තමේන්තුවේ 75 වන සංවත්සරය", "හැත්තෑපස්වන සංවත්සරය", "ආයුබෝවන්", "සුභ උදෑසනක්",
    "ගරු මහාචාර්යතුමනි", "දේශපාලන පක්ෂය", "පක්ෂපාතී", "ගණිතය", "කාමරය", "රමණීය පරිසරය",
    "ශුක්‍රවාදා", "සිකුරාදා", "අතවැසියා", "යෝජනාව", "ශිෂ්‍යයා", "ශිෂ්‍යත්ව විභාගය", "නගරය",
    "තනතුර", "තනිකර", "පියවර", "වෙසක්", "සල්ලි", "කැරැල්ල", "අධ්‍යාපනය", "ප්‍රශ්න පත්‍රය",
    "පුතා", "පුතුනි", "ලංකාව", "ලඟදී", "සංගමය", "සාදරයෙන් පිළිගනිමු", "කළමනාකරණය", "හුස්ම",
    "හුකුම", "පකිස්තානය", "මෝඩර්න්", "උසස් පෙළ", "සාමාන්‍ය පෙළ", "කථිකාචාර්ය", "උපකුලපති",
    # Tamil
    "வணக்கம்", "பரீட்சைத் திணைக்களம்", "பேராசிரியர்", "சூத்திரம்", "காமன்வெல்த்", "ஒத்த கருத்து",
    "பண்ணி", "பன்னிரண்டு", "கல்வி", "விந்தை", "மூளை", "புனர்வாழ்வு", "புனரமைப்பு", "ஓலை",
    "லிங்க்", "மார்ச்", "நன்றி", "கௌரவ அமைச்சர்", "முன்னேற்றம்", "பல்கலைக்கழகம்",
    # English
    "assessment of candidates", "condominium", "class", "Sussex", "Essex", "classic", "lustre",
    "his hit song", "this hit", "Professor", "assistant commissioner", "therapist", "grapes",
    "Dickens", "cocktail", "analysis", "phone", "Good morning, distinguished guests",
]

# Formality is the LLM cleaner's responsibility. These common words must reach
# it rather than being suppressed by the safety blocklist.
MUST_PASS.extend([
    "you are welcome", "please stop at the next slide", "come and go as scheduled",
    "உங்களை வரவேற்கிறோம்", "நீங்கள் செல்லலாம்",
    "ඔබට ස්තුතියි", "ඔබලා පැමිණෙන්න",
])


def main() -> int:
    fails = 0
    for action in ("drop", "mask"):
        config.FILTER_ACTION = action
        for text in MUST_BLOCK:
            if not content_filter.check(text).blocked:
                fails += 1
                print(f"[{action}] NOT BLOCKED: {text}")
        for text in MUST_PASS:
            r = content_filter.check(text)
            if r.blocked or r.text != text:
                fails += 1
                print(f"[{action}] FALSE POSITIVE: {text} -> {r.text}")

    config.FILTER_ACTION = "drop"
    hints = json.loads(config.PHRASES_PATH.read_text(encoding="utf-8"))["phrases"]
    for hint in hints:
        if content_filter.check(hint["value"]).blocked:
            fails += 1
            print(f"EVENT PHRASE BLOCKED: {hint['value']}")

    # Unfinished last word in a live preview is held, but not in a final.
    held = content_filter.check("இன்று நாம் பாலிய", interim=True)
    if not held.blocked or held.confirmed:
        fails += 1
        print("Unfinished preview word not held")
    if content_filter.check("இன்று நாம் பாலிய", interim=False).blocked:
        fails += 1
        print("Final with harmless short word was blocked")
    for preview in (
        "this talk covers homosex", "This talk covers homose.", "අද අපි සමලිං", "අද අපි ලිංගි.",
        "ladies and gentlemen fuc", "இன்று நாம் பாலிய.",
    ):
        if not content_filter.check(preview, interim=True).blocked:
            fails += 1
            print(f"Unfinished preview word not held: {preview}")

    sentence = "අද අපි විභාග දෙපාර්තමේන්තුවේ හැත්තෑපස්වන සංවත්සරය සමරන මේ උත්සවයට සියලු දෙනා සාදරයෙන් පිළිගනිමු"
    n = 2000
    t0 = time.perf_counter()
    for _ in range(n):
        content_filter.check(sentence, interim=True)
    per_ms = (time.perf_counter() - t0) / n * 1000

    print(
        f"{len(MUST_BLOCK)} must-block, {len(MUST_PASS)} must-pass, {len(hints)} event phrases checked; "
        f"{per_ms:.3f} ms per caption; failures: {fails}"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
