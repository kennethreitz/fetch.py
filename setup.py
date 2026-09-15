"""Package the canonical module with discoverable inline types.

Runtime code lives only in fetch.py. Normal builds install those exact bytes
as fetch/__init__.py beside py.typed; editable installs use the source directly.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildModule(build_py):
    def find_modules(self):
        return [("fetch", "__init__", "fetch.py")]

    def run(self):
        super().run()
        target = Path(self.build_lib) / "fetch" / "py.typed"
        self.mkpath(str(target.parent))
        self.copy_file("py.typed", str(target))


setup(cmdclass={"build_py": BuildModule})
