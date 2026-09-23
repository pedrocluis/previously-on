"""``previously-on check``: the report the Windows bundle is tested with."""

from previously_on import doctor
from previously_on.cli import main


def test_failed_only_counts_required_checks():
    ok = doctor.Check("ocr", True, "read 'YOU DIED'")
    warn = doctor.Check("capture (mss)", False, "no display", required=False)
    fail = doctor.Check("ui files", False, "missing")
    assert not doctor.failed([ok, warn])
    assert doctor.failed([ok, warn, fail])
    text = doctor.report([ok, warn, fail])
    assert "ok   ocr" in text and "warn capture (mss)" in text and "FAIL ui files" in text


def test_run_reports_an_exception_instead_of_raising():
    def boom() -> str:
        raise FileNotFoundError("config.yaml")

    check = doctor._run("ocr", boom)
    assert not check.ok and check.detail == "FileNotFoundError: config.yaml"


def test_ui_files_and_profiles_present():
    assert doctor._run("ui files", doctor._ui_files).ok
    assert "eldenring" in doctor._profiles()


def test_check_command_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "run_checks", lambda: [doctor.Check("ocr", False, "boom")])
    assert main(["check"]) == 1
    assert "FAIL ocr: boom" in capsys.readouterr().out
    monkeypatch.setattr(doctor, "run_checks", lambda: [doctor.Check("ocr", True, "fine")])
    assert main(["check"]) == 0
