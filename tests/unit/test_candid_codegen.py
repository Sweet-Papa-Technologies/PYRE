import hashlib
import runpy

from pyre import cli
from pyre._candid_codegen import generate


DID = "service : { z : (nat8) -> (); a : () -> (text) query; }"


def test_generation_is_byte_deterministic_sorted_and_loadable(tmp_path):
    first = generate(DID, "DemoService")
    second = generate(DID, "DemoService")
    assert first == second
    assert hashlib.sha256(DID.encode()).hexdigest() in first
    assert first.index("MethodSpec('a'") < first.index("MethodSpec('z'")
    output = tmp_path / "service.py"
    output.write_text(first)
    generated = runpy.run_path(str(output))
    assert generated["DemoService"].method("a").mode == "query"


def test_cli_check_and_generate(tmp_path, capsys):
    source = tmp_path / "demo.did"; source.write_text(DID)
    output = tmp_path / "generated" / "demo.py"
    assert cli.main(["candid", "check", str(source)]) == 0
    assert cli.main(["candid", "generate", str(source), "--name", "Demo", "--output", str(output)]) == 0
    before = output.read_bytes()
    assert cli.main(["candid", "generate", str(source), "--name", "Demo", "--output", str(output)]) == 0
    assert output.read_bytes() == before
