"""std.mmio registers and bit fields, std.hal interfaces with their test doubles (features across modules)."""
from pathlib import Path

from tests.helpers import run_gg_source

PROGRAM = (Path(__file__).parent / "fixtures" / "mmio_hal_program.gg").read_text(encoding="utf-8")


def test_mmio_and_hal(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "207 true false", "2748 703695 1048320", "7 7", "true false", "95", "true 5 50000", "300 1", "-1", "131"]


def test_default_method_of_an_imported_feature_sees_the_users_methods(tmp_path):
    (tmp_path / "shapes.gg").write_text("feature Named:\n    fn name(self: Self) -> i32\n    fn twice(self: Self) -> i32:\n        return self.name() * 2\n",
                                        encoding="utf-8")
    r = run_gg_source(tmp_path, "import shapes { Named }\n\nstruct A:\n    v: i32\n\nimpl A:\n    fn name(self) -> i32:\n        return self.v\n\n"
                                "fn show[T: Named](x: T) -> i32:\n    return x.twice()\n\nfn main():\n    print(show(A{ v: 4 }), A{ v: 5 }.twice())\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "8 10"
