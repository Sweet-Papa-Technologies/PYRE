"""`pyre dev` footgun scan: naive random/uuid/time source warnings."""

from pyre.cli import RESERVED_BASENAMES, check_footguns, warn_footguns

NAIVE_SOURCE = """\
import random
import uuid
import time
from datetime import datetime

def handler(req):
    t = time.time()
    u = uuid.uuid4()
    d = datetime.now()
    return {"r": random.random()}
"""

BLESSED_SOURCE = """\
from pyre import random as prandom
from pyre import time as ptime
from pyre import uuid as puuid

# import random  <- commented-out footguns never warn
def handler(req):
    return {"id": prandom.uuid4(), "at": ptime.now(), "u": puuid.uuid4()}
"""


def write(tmp_path, name, source):
    path = tmp_path / name
    path.write_text(source)
    return str(path)


def test_naive_source_triggers_warnings(tmp_path):
    path = write(tmp_path, "app.py", NAIVE_SOURCE)
    findings = {(lineno, message) for _p, lineno, message in check_footguns(str(tmp_path))}
    lines = {lineno for lineno, _m in findings}
    assert 1 in lines  # import random
    assert 2 in lines  # import uuid
    assert 7 in lines  # time.time()
    assert 8 in lines  # uuid.uuid4()
    assert 9 in lines  # datetime.now()
    messages = " ".join(m for _l, m in findings)
    assert "pyre.random" in messages
    assert "pyre.time" in messages
    assert "uuid4" in messages
    assert all(p == path for p, _l, _m in check_footguns(str(tmp_path)))


def test_import_random_alone_warns(tmp_path):
    write(tmp_path, "app.py", "import random\n")
    findings = check_footguns(str(tmp_path))
    assert len(findings) == 1
    assert "breaks consensus" in findings[0][2]


def test_datetime_utcnow_warns(tmp_path):
    write(tmp_path, "app.py", "stamp = datetime.utcnow()\n")
    assert len(check_footguns(str(tmp_path))) == 1


def test_pyre_blessed_source_is_silent(tmp_path):
    write(tmp_path, "app.py", BLESSED_SOURCE)
    assert check_footguns(str(tmp_path)) == []


def test_prandom_is_not_mistaken_for_random(tmp_path):
    write(tmp_path, "app.py", "import prandom\nvalue = prandom.random()\n")
    assert check_footguns(str(tmp_path)) == []


def test_comments_and_non_python_files_ignored(tmp_path):
    write(tmp_path, "notes.txt", "import random\n")
    write(tmp_path, "app.py", "# import random\n#import uuid\nx = 1\n")
    assert check_footguns(str(tmp_path)) == []


def test_pyre_framework_dirs_and_reserved_basenames_skipped(tmp_path):
    vendored = tmp_path / "pyre"
    vendored.mkdir()
    (vendored / "helpers.py").write_text("import random\n")
    write(tmp_path, "prandom.py", "import random\n")  # reserved basename
    assert check_footguns(str(tmp_path)) == []


def test_warn_footguns_prints_to_stderr(tmp_path, capsys):
    write(tmp_path, "app.py", "import random\n")
    warn_footguns(str(tmp_path))
    err = capsys.readouterr().err
    assert "pyre: WARNING" in err
    assert "app.py:1" in err
    assert "from pyre import random as prandom" in err


def test_warn_footguns_silent_on_clean_source(tmp_path, capsys):
    write(tmp_path, "app.py", BLESSED_SOURCE)
    warn_footguns(str(tmp_path))
    assert capsys.readouterr().err == ""


def test_new_framework_basenames_are_reserved():
    assert {"prandom", "ptime", "puuid"} <= RESERVED_BASENAMES
