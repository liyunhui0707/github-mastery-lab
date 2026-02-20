import json
from hashlib import sha256

from typer.testing import CliRunner

from shipshape.cli import app, scan

runner = CliRunner()


def test_scan_outputs_json():
    result = runner.invoke(app, ["scan", "."])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "path" in payload


def test_scan_compact_outputs_minified_json(tmp_path):
    (tmp_path / "a.txt").write_text("TODO\n", encoding="utf-8")

    result = runner.invoke(app, ["scan", str(tmp_path), "--compact"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert result.stdout.strip() == json.dumps(payload, separators=(",", ":"))


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "shipshape" in result.stdout.lower()


def test_scan_counts_todo_and_fixme(tmp_path):
    (tmp_path / "root.txt").write_text("TODO one\n", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text(
        "# TODO: refactor\n# FIXME: edge case\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "b.txt").write_text(
        "todo later\nfixme now\nTODO again\n", encoding="utf-8"
    )

    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["todo_total"] == 6
    assert payload["todo_by_dir"] == {".": 1, "pkg": 5}


def test_scan_ignores_non_utf8_files(tmp_path):
    (tmp_path / "notes.txt").write_text("TODO: task\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00TODO")

    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["todo_total"] == 1


def test_scan_ignores_configured_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# TODO: keep\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.txt").write_text("TODO in git\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.txt").write_text("TODO in venv\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.py").write_text("TODO in pycache\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("TODO in node\n", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "ignored.txt").write_text("TODO in cache\n", encoding="utf-8")

    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["todo_total"] == 1
    assert payload["todo_by_dir"] == {"src": 1}


def test_scan_largest_files_defaults_to_top_10(tmp_path):
    for i in range(12):
        (tmp_path / f"f{i:02}.txt").write_bytes(b"x" * (i + 1))

    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    largest_files = payload["largest_files"]
    assert len(largest_files) == 10
    assert largest_files[0] == {"path": "f11.txt", "bytes": 12}
    assert largest_files[-1] == {"path": "f02.txt", "bytes": 3}


def test_scan_largest_files_respects_top_and_ignored_dirs(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"a" * 10)
    (tmp_path / "b.bin").write_bytes(b"b" * 5)
    (tmp_path / "c.bin").write_bytes(b"c" * 7)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.bin").write_bytes(b"z" * 100)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "ignored.pyc").write_bytes(b"y" * 90)

    result = runner.invoke(app, ["scan", str(tmp_path), "--top", "2"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["largest_files"] == [
        {"path": "a.bin", "bytes": 10},
        {"path": "c.bin", "bytes": 7},
    ]


def test_scan_respects_ignore_pattern_for_files_and_dirs(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("# TODO: keep\n", encoding="utf-8")
    (tmp_path / "src" / "skip.skip").write_text("TODO skip\n", encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "ignored.txt").write_text("TODO ignored\n", encoding="utf-8")
    (tmp_path / "big.keep").write_bytes(b"a" * 10)
    (tmp_path / "big.skip").write_bytes(b"b" * 20)

    result = runner.invoke(
        app,
        [
            "scan",
            str(tmp_path),
            "--ignore-pattern",
            "*.skip",
            "--ignore-pattern",
            "tmp*",
            "--top",
            "2",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["todo_total"] == 1
    assert payload["todo_by_dir"] == {"src": 1}
    assert payload["largest_files"] == [
        {"path": "src/keep.py", "bytes": 13},
        {"path": "big.keep", "bytes": 10},
    ]


def test_scan_reports_ignore_patterns_field(tmp_path):
    (tmp_path / "a.txt").write_text("TODO\n", encoding="utf-8")

    default_result = runner.invoke(app, ["scan", str(tmp_path)])
    assert default_result.exit_code == 0
    default_payload = json.loads(default_result.stdout)
    assert default_payload["ignore_patterns"] == []

    result = runner.invoke(
        app, ["scan", str(tmp_path), "--ignore-pattern", "*.txt", "--ignore-pattern", "docs/*"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ignore_patterns"] == ["*.txt", "docs/*"]


def test_scan_respects_extra_ignore_dir(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "keep.py").write_text("# TODO: keep\n", encoding="utf-8")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "ignored.txt").write_text("TODO ignored\n", encoding="utf-8")
    (tmp_path / "small.bin").write_bytes(b"a" * 5)
    (tmp_path / "build" / "big.bin").write_bytes(b"z" * 100)

    result = runner.invoke(
        app,
        ["scan", str(tmp_path), "--ignore-dir", "build", "--top", "2"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["todo_total"] == 1
    assert payload["todo_by_dir"] == {"src": 1}
    assert payload["largest_files"] == [
        {"path": "src/keep.py", "bytes": 13},
        {"path": "small.bin", "bytes": 5},
    ]


def test_scan_groups_duplicate_candidates_by_sha256(tmp_path):
    dup_content = b"same-content\n"
    expected_hash = sha256(dup_content).hexdigest()

    (tmp_path / "a.txt").write_bytes(dup_content)
    (tmp_path / "b.txt").write_bytes(dup_content)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.txt").write_bytes(dup_content)
    (tmp_path / "unique.txt").write_bytes(b"unique")

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored.txt").write_bytes(dup_content)

    if hasattr((tmp_path / "link.txt"), "symlink_to"):
        try:
            (tmp_path / "link.txt").symlink_to(tmp_path / "a.txt")
        except OSError:
            pass

    large = b"x" * (5 * 1024 * 1024 + 1)
    (tmp_path / "large1.bin").write_bytes(large)
    (tmp_path / "large2.bin").write_bytes(large)

    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["duplicate_candidates"] == [
        {"hash": expected_hash, "files": ["a.txt", "b.txt", "sub/c.txt"]}
    ]


def test_scan_json_schema_stability(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "file.py").write_text("# TODO: keep\n", encoding="utf-8")
    (tmp_path / "copy_a.txt").write_text("same\n", encoding="utf-8")
    (tmp_path / "copy_b.txt").write_text("same\n", encoding="utf-8")

    result = runner.invoke(app, ["scan", str(tmp_path)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "path" in payload

def test_scan_programmatic_end_to_end_json_structure(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "nested" / "deeper").mkdir(parents=True)

    (tmp_path / "README.md").write_text("TODO at root\n", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text("# FIXME: handle edge\n", encoding="utf-8")
    (tmp_path / "docs" / "notes.md").write_text("TODO docs item\n", encoding="utf-8")

    dup_content = b"duplicate-content\n"
    expected_hash = sha256(dup_content).hexdigest()
    (tmp_path / "src" / "dup.txt").write_bytes(dup_content)
    (tmp_path / "nested" / "deeper" / "dup.txt").write_bytes(dup_content)

    json_out = tmp_path / "report.json"
    scan(path=tmp_path, json_out=json_out, top=5, ignore_patterns=None, ignore_dirs=None)

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert set(payload) == {
        "path",
        "todo_total",
        "todo_by_dir",
        "largest_files",
        "duplicate_candidates",
        "ignore_patterns",
    }
    assert payload["todo_by_dir"]["src"] == 1
    assert payload["todo_by_dir"]["docs"] == 1
    assert payload["todo_by_dir"]["."] == 1


    assert isinstance(payload["largest_files"], list)
    assert payload["largest_files"]
    assert set(payload["largest_files"][0]) == {"path", "bytes"}

    assert isinstance(payload["duplicate_candidates"], list)
    assert payload["duplicate_candidates"]
    assert set(payload["duplicate_candidates"][0]) == {"hash", "files"}
    assert payload["path"] == str(tmp_path.resolve())
    assert payload["todo_total"] == 3
    assert payload["todo_by_dir"] == {".": 1, "docs": 1, "src": 1}
    assert payload["ignore_patterns"] == []
    assert isinstance(payload["largest_files"], list)
    assert payload["duplicate_candidates"] == [
        {
            "hash": expected_hash,
            "files": ["nested/deeper/dup.txt", "src/dup.txt"],
        }
    ]
