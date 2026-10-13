"""Greengold Language Server (LSP) unit tests."""
from __future__ import annotations

import io
from pathlib import Path

from greengold.lsp import LanguageServer, format_greengold_source, path_to_uri


class DummyServer(LanguageServer):
    """In-memory I/O LSP server for testing."""

    def __init__(self) -> None:
        super().__init__(in_stream=io.BytesIO(), out_stream=io.BytesIO())
        self.published_diagnostics: list[dict] = []

    def send_notification(self, method: str, params: dict) -> None:
        if method == "textDocument/publishDiagnostics":
            self.published_diagnostics.append(params)
        super().send_notification(method, params)


def test_lsp_initialize():
    server = DummyServer()
    resp = server.m_initialize({"rootUri": "file:///c:/project"})
    assert "capabilities" in resp
    caps = resp["capabilities"]
    assert caps["hoverProvider"] is True
    assert caps["inlayHintProvider"]["resolveProvider"] is False
    assert caps["definitionProvider"] is True
    assert caps["documentSymbolProvider"] is True
    assert caps["completionProvider"] is not None
    assert caps["documentFormattingProvider"] is True
    assert caps["signatureHelpProvider"] is not None


def test_lsp_prelude_file_has_no_duplicate_errors():
    """Opening greengold/core/core.gg must not treat the prelude as a second copy of itself."""
    server = DummyServer()
    path = Path(__file__).resolve().parents[1] / "greengold" / "core" / "core.gg"
    uri = path_to_uri(path)
    server.m_textDocument_didOpen({
        "textDocument": {"uri": uri, "text": path.read_text(encoding="utf-8")},
    })
    diags = server.published_diagnostics[0]["diagnostics"]
    assert diags == [], [d["message"] for d in diags]


def test_lsp_diagnostics_clean_code():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn topla(a: i32, b: i32) -> i32:
    return a + b
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    assert len(server.published_diagnostics) == 1
    diags = server.published_diagnostics[0]
    assert diags["uri"] == uri
    assert len(diags["diagnostics"]) == 0


def test_lsp_diagnostics_syntax_and_type_error():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn main():
    x: i32 = "metin"
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    assert len(server.published_diagnostics) == 1
    diags = server.published_diagnostics[0]["diagnostics"]
    assert len(diags) > 0
    # Error line should be 2 (0-indexed line: 1)
    assert diags[0]["range"]["start"]["line"] == 1
    assert "i32" in diags[0]["message"] or "string" in diags[0]["message"]


def test_lsp_hover():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """struct Nokta:
    x: i32
    y: i32

fn hesapla(p: Nokta) -> i32:
    return p.x + p.y
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Keyword hover: 'struct'
    h_struct = server.m_textDocument_hover({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 2},
    })
    assert h_struct is not None
    assert "**struct**" in h_struct["contents"]["value"]

    # User-defined struct hover: 'Nokta'
    h_nokta = server.m_textDocument_hover({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 8},
    })
    assert h_nokta is not None
    assert "struct Nokta" in h_nokta["contents"]["value"]

    # User-defined function hover: 'hesapla'
    h_fn = server.m_textDocument_hover({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 4},
    })
    assert h_fn is not None
    assert "fn hesapla(p: Nokta) -> i32" in h_fn["contents"]["value"]

    # Parameter hover: 'p'
    h_p = server.m_textDocument_hover({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 11},
    })
    assert h_p is not None
    assert "p: Nokta" in h_p["contents"]["value"]


def test_lsp_definition():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn topla(a: i32, b: i32) -> i32:
    return a + b

fn main():
    s = topla(10, 20)
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Go to definition from 'topla' call (line 4, column 10)
    defn = server.m_textDocument_definition({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 10},
    })
    assert defn is not None
    assert defn["uri"] == uri
    # 'fn topla' should be on line 0
    assert defn["range"]["start"]["line"] == 0



def test_lsp_document_symbols():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """struct Nokta:
    x: i32
    y: i32

enum Renk:
    Kirmizi
    Mavi

fn topla(a: i32, b: i32) -> i32:
    return a + b
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    symbols = server.m_textDocument_documentSymbol({"textDocument": {"uri": uri}})

    names = [s["name"] for s in symbols]
    assert "Nokta" in names
    assert "Renk" in names
    assert "topla" in names

    nokta_sym = next(s for s in symbols if s["name"] == "Nokta")
    assert len(nokta_sym["children"]) == 2
    assert nokta_sym["children"][0]["name"] == "x"


def test_lsp_completion():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """struct Oyuncu:
    can: i32

fn main():
    p = Oyuncu(100)
    p.
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Completion after 'p.'
    comp = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 5, "character": 6},
    })
    labels = [item["label"] for item in comp["items"]]
    assert "len" in labels
    assert "value_or_panic()" in labels
    assert "can" in labels
    value_or_panic_item = next(item for item in comp["items"] if item["label"] == "value_or_panic()")
    assert value_or_panic_item["insertText"] == "value_or_panic()$0"
    assert value_or_panic_item["insertTextFormat"] == 2


def test_lsp_completes_declared_attributes_after_at():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """attribute replicated(mode: ident, reliable: bool = false) on fn
attribute tag on struct
@rep
fn f():
    pass

fn main():
    pass
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    comp = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 2, "character": 4},
    })
    items = {item["label"]: item for item in comp["items"]}
    assert set(items) == {"replicated", "tag"}
    assert items["replicated"]["insertText"] == "replicated($0)"
    assert items["tag"]["insertText"] == "tag"
    assert items["replicated"]["detail"] == (
        "attribute replicated(mode: ident, reliable: bool = ...) on fn")


def test_lsp_formatting():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = "fn test():\npass\n"
    res = server.m_textDocument_formatting({"textDocument": {"uri": uri}})
    # unformatted 'pass' should indent to '    pass'
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    res = server.m_textDocument_formatting({"textDocument": {"uri": uri}})
    assert len(res) == 1
    assert "    pass" in res[0]["newText"]


def test_lsp_signature_help():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn topla(a: i32, b: i32) -> i32:
    return a + b

fn main():
    topla(10, 
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    sig = server.m_textDocument_signatureHelp({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 14},
    })
    assert sig is not None
    assert sig["activeParameter"] == 1
    assert "topla" in sig["signatures"][0]["label"]


def test_lsp_jsonrpc_null_params():
    server = DummyServer()
    # params explicitly null/None
    server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "shutdown", "params": None})
    # Response should have id 1 and result None without exception
    out = server.out_stream.getvalue()
    assert b'"id": 1' in out
    assert b'"result": null' in out


def test_lsp_header_parsing():
    msg_body = b'{"jsonrpc":"2.0","id":1,"method":"shutdown"}'
    input_data = (
        b"Content-Type: application/vscode-jsonrpc\r\n"
        + f"content-length: {len(msg_body)}\r\n\r\n".encode("ascii")
        + msg_body
    )
    in_buf = io.BytesIO(input_data)
    out_buf = io.BytesIO()
    server = LanguageServer(in_stream=in_buf, out_stream=out_buf)
    server.run()
    out = out_buf.getvalue()
    assert b'"id": 1' in out
    assert b'"result": null' in out


def test_lsp_initialize_workspace_folders():
    server = DummyServer()
    resp = server.m_initialize({
        "workspaceFolders": [{"uri": "file:///c:/my_project", "name": "my_project"}]
    })
    assert server.root_path == Path("c:/my_project")
    assert "capabilities" in resp


def test_lsp_hover_nested_scope():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn f1(x: i32) -> i32:
    return x

fn f2(x: string) -> string:
    if true:
        local: f64 = 3.14
        return x
    return x
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # x in f2 declaration (line 3, column 6): should be f2's string, not f1's i32
    h_x = server.m_textDocument_hover({
        "textDocument": {"uri": uri},
        "position": {"line": 3, "character": 6},
    })
    assert h_x is not None
    assert "str" in h_x["contents"]["value"]
    assert "i32" not in h_x["contents"]["value"]

    # local variable inside if (line 5, column 10)
    h_local = server.m_textDocument_hover({
        "textDocument": {"uri": uri},
        "position": {"line": 5, "character": 10},
    })
    assert h_local is not None
    # nothing changes `local`, so the hover shows it as `fixed`
    assert "fixed local: f64" in h_local["contents"]["value"]


def test_lsp_definition_nested_and_struct_field():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """struct Nokta:
    x: i32
    y: i32

fn test():
    if true:
        nested: i32 = 42
        print(nested)
    p = Nokta(1, 2)
    print(p.x)
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Go to nested variable inside if (line 7, column 16)
    d_nested = server.m_textDocument_definition({
        "textDocument": {"uri": uri},
        "position": {"line": 7, "character": 16},
    })
    assert d_nested is not None
    assert d_nested["range"]["start"]["line"] == 6  # var nested line (0-based)

    # Go to field x in p.x (line 9, column 12)
    d_field = server.m_textDocument_definition({
        "textDocument": {"uri": uri},
        "position": {"line": 9, "character": 12},
    })
    assert d_field is not None
    assert d_field["range"]["start"]["line"] == 1  # x: i32 line (0-based)


def test_lsp_features_and_externs_document_symbols():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """feature Cizilebilir:
    fn ciz(self: Self)

extern "math.h" fn sqrt(x: f64) -> f64

fn test():
    pass
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    symbols = server.m_textDocument_documentSymbol({"textDocument": {"uri": uri}})
    names = [s["name"] for s in symbols]
    assert "Cizilebilir" in names
    assert "sqrt" in names
    assert "test" in names

    feature_sym = next(s for s in symbols if s["name"] == "Cizilebilir")
    assert len(feature_sym["children"]) == 1
    assert feature_sym["children"][0]["name"] == "ciz"

    # Verify symbol ranges do not overlap
    ciz_sym = feature_sym
    sqrt_sym = next(s for s in symbols if s["name"] == "sqrt")
    test_sym = next(s for s in symbols if s["name"] == "test")
    assert ciz_sym["range"]["end"]["line"] < sqrt_sym["range"]["start"]["line"]
    assert sqrt_sym["range"]["end"]["line"] < test_sym["range"]["start"]["line"]



def test_lsp_formatting_multiple_functions():
    code = """fn a():
    return 1

fn b():
    if true:
        return 2
    else:
        return 0
"""
    formatted = format_greengold_source(code)
    # fn b should be at column 0, indent should not accumulate
    lines = formatted.splitlines()
    assert lines[0] == "fn a():"
    assert lines[1] == "    return 1"
    assert lines[3] == "fn b():"
    assert lines[4] == "    if true:"
    assert lines[5] == "        return 2"
    assert lines[6] == "    else:"
    assert lines[7] == "        return 0"


def test_lsp_signature_help_strings_and_nesting():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn topla(a: i32, b: string, c: f64) -> i32:
    return a

fn main():
    topla(10, "virgul, iceren, metin", 
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    sig = server.m_textDocument_signatureHelp({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 40},
    })
    assert sig is not None
    # 2 commas (excluding inside string literal) passed -> parameter 2 (c: f64)
    assert sig["activeParameter"] == 2


def test_lsp_type_completion_after_colon():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """struct Kisi:
    yas: i32

fn main():
    x: 
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})
    comp = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 11},
    })
    labels = [it["label"] for it in comp["items"]]
    assert "i32" in labels
    assert "str" in labels
    assert "Kisi" in labels
    assert "Optional" in labels
    # Statement keywords (while, for, if) should not be in type completion list
    assert "while" not in labels
    assert "for" not in labels
    assert "if" not in labels


def test_lsp_multifile_definition_and_diagnostics(tmp_path):
    sub = tmp_path / "sub.gg"
    sub.write_text("fn yardimci() -> i32:\n    return 42\n", encoding="utf-8")
    main = tmp_path / "main.gg"
    main.write_text(f'import "{sub.name}"\n\nfn main():\n    yardimci()\n', encoding="utf-8")

    server = DummyServer()
    main_uri = path_to_uri(main)
    server.m_textDocument_didOpen({"textDocument": {"uri": main_uri, "text": main.read_text("utf-8")}})

    defn = server.m_textDocument_definition({
        "textDocument": {"uri": main_uri},
        "position": {"line": 3, "character": 7},
    })
    assert defn is not None
    # Should jump to sub.gg file
    assert "sub.gg" in defn["uri"]
    assert defn["range"]["start"]["line"] == 0


def test_lsp_no_completion_after_block_colon():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn main():
if x > 0:
while running:
struct Nokta:
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # After 'fn main():' completion should return empty (should not suggest bool etc.)
    comp1 = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 10},
    })
    assert comp1["items"] == []

    # After 'if x > 0:' should return empty
    comp2 = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 1, "character": 9},
    })
    assert comp2["items"] == []

    # After 'while running:' should return empty
    comp3 = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 2, "character": 14},
    })
    assert comp3["items"] == []

    # After 'struct Nokta:' should return empty
    comp4 = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 3, "character": 13},
    })
    assert comp4["items"] == []


def test_lsp_completion_finished_word_false_and_true():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn main():
    fal
    false
    false 
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # When typing 'fal', false should be suggested
    comp_prefix = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 1, "character": 7},
    })
    labels_prefix = [it["label"] for it in comp_prefix["items"]]
    assert "false" in labels_prefix

    # When 'false' is typed completely (no longer alternatives), should return empty,
    # suggestion popup should close
    comp_exact = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 2, "character": 9},
    })
    assert comp_exact["items"] == []

    # When space is typed after 'false ', expression ended so should return empty
    comp_space = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 3, "character": 10},
    })
    assert comp_space["items"] == []


def test_lsp_completion_in_comment_and_string():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """# bool or fn should not appear here
s = "fn should not appear inside string"
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    comp_comment = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 10},
    })
    assert comp_comment["items"] == []

    comp_str = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 1, "character": 12},
    })
    assert comp_str["items"] == []


def test_lsp_completion_param_and_return_type():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn topla(a: 
fn carp(a: i32) -> 
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Parameter type (a:)
    comp_param = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 11},
    })
    labels_param = [it["label"] for it in comp_param["items"]]
    assert "i32" in labels_param
    assert "bool" in labels_param

    # Return type (->)
    comp_ret = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 1, "character": 19},
    })
    labels_ret = [it["label"] for it in comp_ret["items"]]
    assert "i32" in labels_ret
    assert "bool" in labels_ret


def test_lsp_completion_function_parentheses():
    server = DummyServer()
    uri = "file:///c:/test.gg"
    code = """fn topla(a: i32, b: i32) -> i32:
    return a + b

fn main():
    top
    top(1, 2)
    pri
    inp
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # When 'top' is typed and no '(' on right, topla($0) and snippet format should be returned
    comp = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 4, "character": 7},
    })
    topla_item = next(it for it in comp["items"] if it["label"] == "topla")
    assert topla_item["insertText"] == "topla($0)"
    assert topla_item["insertTextFormat"] == 2

    # If '(' already exists on right, prevent double parentheses, return plain name
    comp_paren = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 5, "character": 7},
    })
    topla_paren_item = next(it for it in comp_paren["items"] if it["label"] == "topla")
    assert topla_paren_item["insertText"] == "topla"

    # Prelude function (print) should return print($0)
    comp_pri = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 6, "character": 7},
    })
    print_item = next(it for it in comp_pri["items"] if it["label"] == "print")
    assert print_item["insertText"] == "print($0)"
    assert print_item["insertTextFormat"] == 2

    # Parameterless function (input) should return input()$0
    comp_inp = server.m_textDocument_completion({
        "textDocument": {"uri": uri},
        "position": {"line": 7, "character": 7},
    })
    input_item = next(it for it in comp_inp["items"] if it["label"] == "input")
    assert input_item["insertText"] == "input()$0"
    assert input_item["insertTextFormat"] == 2


def test_lsp_references():
    server = DummyServer()
    uri = "file:///c:/test_refs.gg"
    code = """fn topla(a: i32, b: i32) -> i32:
    return a + b

fn main():
    x = topla(10, 20)
    y = topla(x, 30)
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Find references for 'topla' (line 0, col 3)
    refs = server.m_textDocument_references({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 3},
        "context": {"includeDeclaration": True},
    })
    # Should find declaration (line 0) + 2 call sites (line 4 and line 5)
    assert len(refs) == 3
    lines = [r["range"]["start"]["line"] for r in refs]
    assert 0 in lines
    assert 4 in lines
    assert 5 in lines


def test_lsp_rename():
    server = DummyServer()
    uri = "file:///c:/test_rename.gg"
    code = """fn add(a: i32, b: i32) -> i32:
    return a + b

fn main():
    res = add(1, 2)
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    # Prepare rename on 'add'
    prep = server.m_textDocument_prepareRename({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 3},
    })
    assert prep is not None
    assert prep["placeholder"] == "add"

    # Cannot rename keyword 'return'
    prep_kw = server.m_textDocument_prepareRename({
        "textDocument": {"uri": uri},
        "position": {"line": 1, "character": 4},
    })
    assert prep_kw is None

    # Perform rename 'add' -> 'calculate_sum'
    res = server.m_textDocument_rename({
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": 3},
        "newName": "calculate_sum",
    })
    assert "changes" in res
    assert uri in res["changes"]
    edits = res["changes"][uri]
    assert len(edits) == 2
    for edit in edits:
        assert edit["newText"] == "calculate_sum"


def test_lsp_workspace_symbol():
    server = DummyServer()
    uri = "file:///c:/test_ws.gg"
    code = """struct Hero:
    hp: i32

enum Role:
    Warrior
    Mage

fn attack():
    pass
"""
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": code}})

    symbols = server.m_workspace_symbol({"query": "her"})
    assert len(symbols) >= 1
    assert any(s["name"] == "Hero" for s in symbols)

    symbols_all = server.m_workspace_symbol({"query": ""})
    names = [s["name"] for s in symbols_all]
    assert "Hero" in names
    assert "Role" in names
    assert "attack" in names


def test_lsp_document_symbols_range_containment():
    server = DummyServer()
    uri = "file:///c:/test_symbols_containment.gg"

    # 1. Normal declarations
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": """struct SuperLongTypeName:
    first_field: i32
    second_field: str

fn compute():
    pass
"""}})
    syms = server.m_textDocument_documentSymbol({"textDocument": {"uri": uri}})
    assert len(syms) == 2

    def check_containment(s):
        r = s["range"]
        sr = s["selectionRange"]
        r_start = (r["start"]["line"], r["start"]["character"])
        r_end = (r["end"]["line"], r["end"]["character"])
        sr_start = (sr["start"]["line"], sr["start"]["character"])
        sr_end = (sr["end"]["line"], sr["end"]["character"])
        assert r_start <= sr_start, f"r_start {r_start} must be <= sr_start {sr_start} for {s['name']}"
        assert sr_end <= r_end, f"sr_end {sr_end} must be <= r_end {r_end} for {s['name']}"
        for child in s.get("children", []):
            check_containment(child)
            c_r = child["range"]
            c_r_start = (c_r["start"]["line"], c_r["start"]["character"])
            c_r_end = (c_r["end"]["line"], c_r["end"]["character"])
            assert r_start <= c_r_start, f"parent start {r_start} must be <= child start {c_r_start}"
            assert c_r_end <= r_end, f"child end {c_r_end} must be <= parent end {r_end}"

    for s in syms:
        check_containment(s)

    # 2. In-progress typing: user deletes/changes text to incomplete short code, cached AST active
    server.m_textDocument_didChange({
        "textDocument": {"uri": uri, "version": 2},
        "contentChanges": [{"text": "str"}]
    })
    syms_typing = server.m_textDocument_documentSymbol({"textDocument": {"uri": uri}})
    for s in syms_typing:
        check_containment(s)








def _hover_text(server, uri, line, ch):
    h = server.m_textDocument_hover({"textDocument": {"uri": uri}, "position": {"line": line, "character": ch}})
    return h["contents"]["value"] if h else ""


INFER_SRC = """fn add(xs: List[i32]):
    xs.push(1)

fn main():
    v = List[i32]()
    add(v)
    k = 3
    out = List[i32]()
    collect = fn(x: i32) => out.push(x + k)
    collect(1)
    inc = fn(x: i32) -> i32 => x + 1
    print(inc(v.len))
"""


def test_lsp_uses_the_full_checker_pipeline():
    server = DummyServer()
    uri = "file:///c:/infer.gg"
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": INFER_SRC.replace("inc(v.len)", "inc(1)")}})
    assert server.published_diagnostics[-1]["diagnostics"] == []  # inferred `lend` is not an error in the editor


def test_lsp_hover_shows_inferred_modes():
    server = DummyServer()
    uri = "file:///c:/infer.gg"
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": INFER_SRC}})
    fn_hover = _hover_text(server, uri, 0, 4)
    assert "fn add(xs: lend List[i32])" in fn_hover and "inferred `lend`" in fn_hover
    assert "inferred `lend`" in _hover_text(server, uri, 1, 5)


def test_lsp_hover_shows_closure_captures():
    server = DummyServer()
    uri = "file:///c:/infer.gg"
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": INFER_SRC}})
    at_lambda = _hover_text(server, uri, 8, 15)
    assert "*(closure)* `fn(i32)`" in at_lambda
    assert "`out: List[i32]`: borrowed `lend`" in at_lambda and "`k: i32`: copied" in at_lambda
    assert at_lambda in _hover_text(server, uri, 9, 6)  # hover on a use of the closure variable
    assert "captures nothing" in _hover_text(server, uri, 10, 11)


def _inlay(server: DummyServer, uri: str, text: str) -> list[dict]:
    server.m_textDocument_didOpen({"textDocument": {"uri": uri, "text": text}})
    return server.m_textDocument_inlayHint({
        "textDocument": {"uri": uri},
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 400, "character": 0}},
    })


def _hint_at(hints: list[dict], line: int, character: int) -> list[str]:
    return [h["label"] for h in hints if h["position"] == {"line": line, "character": character}]


def test_lsp_inlay_hints_modes_and_types():
    """Inferred modes and omitted types are shown inline; written ones are not repeated."""
    server = DummyServer()
    uri = "file:///c:/infer.gg"
    hints = _inlay(server, uri, INFER_SRC)
    # fn add(xs: List[i32]) — `lend` sits where the type starts
    assert _hint_at(hints, 0, 11) == ["lend"]
    lend = next(h for h in hints if h["position"] == {"line": 0, "character": 11})
    assert "inferred `lend`" in lend["tooltip"]["value"]
    assert lend["paddingRight"] is True
    # v = ... / k = 3 / out = ... — the type sits right after the variable name
    assert _hint_at(hints, 4, 5) == [": List[i32]"]
    assert _hint_at(hints, 6, 5) == [": i32"]
    assert _hint_at(hints, 7, 7) == [": List[i32]"]
    typed = next(h for h in hints if h["position"] == {"line": 6, "character": 5})
    assert "inferred `i32`" in typed["tooltip"]["value"]
    # nothing changes `k`, `collect`, or `inc`: they are `fixed`. `add` lends `v`, the lambda lends `out`.
    assert _hint_at(hints, 6, 4) == ["fixed"]
    assert _hint_at(hints, 8, 4) == ["fixed"]
    assert _hint_at(hints, 10, 4) == ["fixed"]
    assert _hint_at(hints, 4, 4) == [] and _hint_at(hints, 7, 4) == []
    fixed = next(h for h in hints if h["position"] == {"line": 6, "character": 4})
    assert "inferred `fixed`" in fixed["tooltip"]["value"]
    assert fixed["paddingRight"] is True
    assert _hint_at(hints, 8, 11) == [": fn(i32)"]
    assert _hint_at(hints, 8, 16) == ["[lend out]"]
    assert "borrowed `lend`" in next(h for h in hints if h["label"] == "[lend out]")["tooltip"]["value"]
    assert _hint_at(hints, 10, 7) == [": fn(i32) -> i32"]
    # the parameter type is already written; i32 is copied, so no mode hint
    assert not any(h["label"] in ("read", "lend", "consume") and h["position"]["line"] == 8 for h in hints)


TYPES_SRC = """enum Shape:
    Rect(f32, f32)
    Empty

struct Entity:
    hp: i32

struct Bag:
    items: List[i32]

impl Entity:
    fn hp_of(self) -> i32:
        return self.hp

impl Bag:
    fn add(self):
        self.items.push(1)

fn keep(xs: read List[i32]):
    pass

const LIMIT = 4

fn area(s: Shape) -> f32:
    match s:
        Rect(w, h):
            return w * h
        Empty:
            return 0.0

fn main():
    n: i32 = 1
    k = 2
    for t in 0..3:
        pass
    ents = [Entity{hp: 1}, Entity{hp: 2}]
    for e in ents:
        pass
    for y in ents:
        y.hp = y.hp + 1
    for i, e in ents:
        pass
    s = Shape.Rect(2.0, 3.0)
    match lend s:
        Rect(w, h):
            w = w + 1.0
        Empty:
            pass
    keep(List[i32]())
"""


def test_lsp_inlay_hints_loops_patterns_and_written_annotations():
    server = DummyServer()
    uri = "file:///c:/hints.gg"
    hints = _inlay(server, uri, TYPES_SRC)
    labels = {(h["position"]["line"], h["position"]["character"]): h["label"] for h in hints}

    # bare `self`: a copy struct shows its type; a heap struct also shows the inferred mode
    copy_self = TYPES_SRC.splitlines().index("    fn hp_of(self) -> i32:")
    assert any(labels.get((copy_self, col)) == ": Entity" for col in range(80))
    lend_self = TYPES_SRC.splitlines().index("    fn add(self):")
    assert any(labels.get((lend_self, col)) == ": lend Bag" for col in range(80))
    # written mode and written type produce no hint
    keep = TYPES_SRC.splitlines().index("fn keep(xs: read List[i32]):")
    assert not any(ln == keep for ln, _ in labels)
    declared = TYPES_SRC.splitlines().index("    n: i32 = 1")
    assert [label for (ln, _), label in labels.items() if ln == declared] == ["fixed"]
    # omitted types
    k = TYPES_SRC.splitlines().index("    k = 2")
    assert ": i32" in [label for (ln, _), label in labels.items() if ln == k]
    limit = TYPES_SRC.splitlines().index("const LIMIT = 4")
    assert ": i32" in [label for (ln, _), label in labels.items() if ln == limit]
    counted = TYPES_SRC.splitlines().index("    for t in 0..3:")
    assert ": i32" in [label for (ln, _), label in labels.items() if ln == counted]
    ents = TYPES_SRC.splitlines().index("    ents = [Entity{hp: 1}, Entity{hp: 2}]")
    assert ": [2]Entity" in [label for (ln, _), label in labels.items() if ln == ents]
    read_loop = TYPES_SRC.splitlines().index("    for e in ents:")
    assert ": read Entity" in [label for (ln, _), label in labels.items() if ln == read_loop]
    lend_loop = TYPES_SRC.splitlines().index("    for y in ents:")
    assert ": lend Entity" in [label for (ln, _), label in labels.items() if ln == lend_loop]
    indexed = TYPES_SRC.splitlines().index("    for i, e in ents:")
    indexed_labels = [label for (ln, _), label in labels.items() if ln == indexed]
    assert ": usize" in indexed_labels and ": read Entity" in indexed_labels
    shape = TYPES_SRC.splitlines().index("    s = Shape.Rect(2.0, 3.0)")
    assert ": Shape" in [label for (ln, _), label in labels.items() if ln == shape]
    arm = TYPES_SRC.splitlines().index("        Rect(w, h):")
    # the lend arm is the second Rect(w, h)
    lend_arm = TYPES_SRC.splitlines().index("        Rect(w, h):", arm + 1)
    lend_labels = [label for (ln, _), label in labels.items() if ln == lend_arm]
    assert lend_labels.count(": lend f32") == 2
    # a value match still shows the payload type, without a mode
    value_labels = [label for (ln, _), label in labels.items() if ln == arm]
    assert value_labels.count(": f32") == 2
    # outside the requested range, nothing is returned
    only = server.m_textDocument_inlayHint({
        "textDocument": {"uri": uri},
        "range": {"start": {"line": k, "character": 0}, "end": {"line": k + 1, "character": 0}},
    })
    assert [h["label"] for h in only] == ["fixed", ": i32"]


def test_lsp_inlay_hint_uses_source_module_spelling(tmp_path):
    """A type from another file is shown as `shapes.Rectangle`, not the internal `shapes::Rectangle`."""
    shapes = tmp_path / "shapes.gg"
    shapes.write_text(
        "struct Rectangle:\n"
        "    w: f64\n"
        "    h: f64\n",
        encoding="utf-8",
    )
    main = tmp_path / "main.gg"
    main.write_text(
        'import "shapes.gg"\n\n'
        "fn main():\n"
        "    rect = shapes.Rectangle{ w: 10.0, h: 30.0 }\n",
        encoding="utf-8",
    )
    server = DummyServer()
    uri = path_to_uri(main)
    hints = _inlay(server, uri, main.read_text("utf-8"))
    labels = [h["label"] for h in hints]
    assert ": shapes.Rectangle" in labels
    assert not any("::" in label for label in labels)
    hover = _hover_text(server, uri, 3, 6)
    assert "shapes.Rectangle" in hover
    assert "::" not in hover


def test_lsp_inlay_hints_survive_incomplete_line():
    """Opening or editing a file with an incomplete line still produces inlay hints for valid lines."""
    server = DummyServer()
    uri = "file:///c:/incomplete.gg"
    src = (
        "fn main():\n"
        "    x = 42\n"
        "    x.\n"
    )
    hints = _inlay(server, uri, src)
    labels = [h["label"] for h in hints]
    assert ": i32" in labels


def test_cli_lsp_accepts_stdio_flag(monkeypatch):
    """vscode-languageclient passes `--stdio` when TransportKind.stdio is used."""
    from greengold import cli, lsp
    called = []
    monkeypatch.setattr(lsp, "run_server", lambda: (called.append(True) or 0))
    rc = cli.main(["lsp", "--stdio"])
    assert rc == 0
    assert called == [True]



def test_lsp_inlay_hint_infers_lend_for_slice_parameter():
    """A slice written without a mode becomes `lend` when the body changes an element."""
    src = (
        "fn give_total(numbers: []i32) -> i32:\n"
        "    total = 0\n"
        "    for number in numbers:\n"
        "        total += number\n"
        "    numbers[0] = total\n"
        "    return total\n"
        "\n"
        "fn only_reads(numbers: []i32) -> i32:\n"
        "    return numbers[0]\n"
        "\n"
        "fn main():\n"
        "    xs: [3]i32 = [1, 2, 3]\n"
        "    print(give_total(xs), only_reads(xs))\n"
    )
    server = DummyServer()
    hints = _inlay(server, "file:///c:/slice_lend.gg", src)
    col = src.splitlines()[0].index("[]i32")
    assert _hint_at(hints, 0, col) == ["lend"]
    assert _hint_at(hints, 7, src.splitlines()[7].index("[]i32")) == []
