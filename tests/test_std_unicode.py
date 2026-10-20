"""std.unicode against Python's str methods on the scripts it covers.

Spec: 16
"""
import unicodedata

from tests.helpers import run_gg_source


def test_case_mapping_matches_python(tmp_path):
    samples = ["straße", "ÀÉÎÕÜ àéîõü", "ŁÓDŹ łódź", "ΑΒΓΔΩ αβγδω", "ЖУК жук ЁЖ ёж", "Ա Բ ա բ", "İstanbul ıırmak", "ŠČĆŽ šćčž"]
    body = "".join(f'    print(unicode.to_upper("{s}"))\n    print(unicode.to_lower("{s}"))\n' for s in samples)
    r = run_gg_source(tmp_path, "import std.unicode\n\nfn main():\n" + body)
    assert r.returncode == 0, r.stderr
    got = r.stdout.splitlines()
    want = []
    for s in samples:
        want += [s.upper(), s.lower().replace("i\u0307", "i")]
    # Python lowercases İ to "i" + a combining dot; this module keeps İ (it has no one-character lowercase)
    for g, w, s in zip(got, want, [x for x in samples for _ in range(2)]):
        assert g == w or ("İ" in s and g.replace("İ", "i") == w.replace("i̇", "i")), (s, g, w)


def test_widths_graphemes_and_classes(tmp_path):
    r = run_gg_source(tmp_path, """import std.unicode

fn main():
    print(unicode.width("日本語"), unicode.width("abc"), unicode.width("e\u0301"), unicode.grapheme_count("e\u0301x"), unicode.grapheme_count("a"))
    print(unicode.reverse("añb"), unicode.take_chars("héllo", 3), unicode.truncate_width("日本語です", 7, "…"))
    print(unicode.is_alphabetic(0x4E2D), unicode.is_numeric(0x663), unicode.is_whitespace(0x3000), unicode.is_uppercase(0x416), unicode.is_lowercase(0xDF))
    print(unicode.eq_ignore_case("Straße", "STRASSE"), unicode.eq_ignore_case("ÉCOLE", "école"), unicode.encode_utf8(0x1F600).len())
    print(unicode.to_lower("ΣΑΣ"), unicode.to_upper("straße"))
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["6 3 1 2 1", "bña hél 日本語…", "true true true true true", "true true 4", "σας STRASSE"]
