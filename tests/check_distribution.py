"""Check built artifacts, dependency-free wheel behavior, and installed types.

Run after uv build: uv run --locked python tests/check_distribution.py
The temporary test directory contains no source module to shadow the wheel.
"""

import email
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def run(*args: str | Path, cwd: Path) -> None:
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True, timeout=120)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / "dist").glob("*.whl"))
    sdists = list((root / "dist").glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SystemExit("Build into a clean dist/ directory: expected one wheel and one sdist")
    source = (root / "fetch.py").read_bytes()
    with zipfile.ZipFile(wheels[0]) as wheel:
        assert wheel.read("fetch/__init__.py") == source
        assert "fetch/py.typed" in wheel.namelist()
        metadata_path = next(name for name in wheel.namelist() if name.endswith("/METADATA"))
        metadata = email.message_from_bytes(wheel.read(metadata_path))
        assert not metadata.get_all("Requires-Dist"), "Unexpected runtime dependency"
    with tarfile.open(sdists[0]) as sdist:
        for name in ("fetch.py", "uv.lock"):
            member = next(item for item in sdist.getmembers() if item.name.endswith("/" + name))
            contents = sdist.extractfile(member)
            assert contents is not None and contents.read() == (root / name).read_bytes()

    with tempfile.TemporaryDirectory(prefix="fetch-wheel-") as directory:
        tmp = Path(directory)
        environment = tmp / "venv"
        run("uv", "venv", "--python", sys.executable, environment, cwd=tmp)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        run("uv", "pip", "install", "--no-deps", "--python", python, wheels[0], cwd=tmp)
        run(
            python,
            "-I",
            "-c",
            (
                "import fetch, importlib.util; from pathlib import Path; "
                "assert Path(fetch.__file__).name == '__init__.py'; "
                "assert importlib.util.find_spec('pydantic') is None"
            ),
            cwd=tmp,
        )

        tests = tmp / "tests"
        tests.mkdir()
        for name in ("test_fetch.py", "test_sessions.py", "test_streaming.py"):
            shutil.copyfile(root / "tests" / name, tests / name)
        run(python, "-I", "-m", "unittest", "discover", "-s", tests, "-q", cwd=tmp)

        checks = tmp / "check_installed_types.py"
        shutil.copyfile(root / "tests" / checks.name, checks)
        run(
            sys.executable,
            "-m",
            "mypy",
            "--warn-unused-ignores",
            "--python-executable",
            python,
            checks,
            cwd=tmp,
        )
        run(sys.executable, "-m", "pyright", "--pythonpath", python, checks, cwd=tmp)
    print("Source, wheel, and sdist match; isolated runtime and installed types verified.")


if __name__ == "__main__":
    main()
