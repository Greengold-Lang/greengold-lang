"""std.fs (Result API, directories, metadata) and std.io (IoError, Reader/Writer features, Cursor)."""
from tests.helpers import run_gg_source


def _run(tmp_path, src):
    r = run_gg_source(tmp_path, src)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_fs_directory_tree_and_files(tmp_path):
    root = (tmp_path / "t").as_posix()
    out = _run(tmp_path, f"""import std.fs

fn main():
    root = "{root}"
    deep = fs.path_join(root, "a/b")
    print(fs.create_dir_all(deep.as_str()).is_ok(), fs.is_dir(deep.as_str()))
    f1 = fs.path_join(root, "z.txt")
    fs.write_text(f1.as_str(), "hello").value_or_panic()
    fs.append_text(f1.as_str(), " world").value_or_panic()
    print(fs.read_text(f1.as_str()).value_or("?"))
    f2 = fs.path_join(deep.as_str(), "x.txt")
    fs.write_atomic(f2.as_str(), "one").value_or_panic()
    fs.write_atomic(f2.as_str(), "two").value_or_panic()
    print(fs.read_text(f2.as_str()).value_or("?"))
    m = fs.metadata(f1.as_str()).value_or_panic()
    print(m.size, m.is_file, m.is_dir)
    for e in fs.read_dir(root).value_or_panic():
        print(e.name, e.is_dir)
    for w in fs.walk(root).value_or_panic():
        print(fs.path_name(w.as_str()))
    print(fs.list_dir(root).value_or("none"))
    print(fs.remove_dir_all(root).is_ok(), fs.path_exists(root))
""")
    assert out[:4] == ["true true", "hello world", "two", "11 true false"]
    assert out[4:6] == ["a true", "z.txt false"]
    assert out[6:8] == ["x.txt", "z.txt"]
    assert out[-1] == "true false"


def test_fs_errors_say_why(tmp_path):
    out = _run(tmp_path, """import std.fs
import std.io

fn main():
    match consume fs.read_text("/no/such/dir/file.txt"):
        Ok(t): print("??")
        Err(e): print(e.is_not_found(), e.kind == io.IoErrorKind.NotFound)
    print(fs.create_dir("/no/such/dir/sub").is_err(), fs.read_dir("/no/such/dir").is_err())
    print(fs.read_file_to_string("/no/such").is_none(), fs.make_dir("/no/such/x"))
""")
    assert out == ["true true", "true true", "true false"]


def test_io_features_cursor_and_files(tmp_path):
    path = (tmp_path / "f.txt").as_posix()
    out = _run(tmp_path, f"""import std.io {{ File, Reader, Writer, cursor_new }}

fn dump[W: Writer](out: lend W):
    out.write_line("hello").value_or_panic()
    out.write("a,b").value_or_panic()

fn slurp[R: Reader](r: lend R) -> string:
    return r.read_rest().value_or_panic()

fn main():
    f = File.create("{path}").value_or_panic()
    dump(f)
    f.flush().value_or_panic()
    g = File.open("{path}").value_or_panic()
    print(g.size().value_or_panic())
    print(slurp(g))
    c = cursor_new("abcdef")
    print(slurp(c))
    w = cursor_new("")
    dump(w)
    print(w.text())
    h = File.open("{path}").value_or_panic()
    print(h.read_exact(3).value_or("?"), h.read_exact(100).is_err())
""")
    assert out == ["9", "hello", "a,b", "abcdef", "hello", "a,b", "hel true"]
