"""Setuptools command customization for optional PYRE wheel profiles.

The source tree and default wheel always remain complete. Setting
PYRE_BUILD_PROFILE=slim filters opt-in vNext modules from the wheel's build
file list without deleting or modifying their sources.
"""

import os

from setuptools import setup
from setuptools.command.build_py import build_py


SLIM_EXCLUDED_MODULES = frozenset({
    "pyre._asset_store",
    "pyre._audit",
    "pyre._candid_codegen",
    "pyre._candid_parser",
    "pyre.analytics",
    "pyre.assets",
    "pyre.candid",
    "pyre.tasks",
    "pyre.testing",
    "pyre.xnet",
})


class ProfileBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if os.environ.get("PYRE_BUILD_PROFILE", "full").lower() != "slim":
            return modules
        return [
            item for item in modules
            if "%s.%s" % (item[0], item[1]) not in SLIM_EXCLUDED_MODULES
        ]

    def run(self):
        super().run()
        if os.environ.get("PYRE_BUILD_PROFILE", "full").lower() != "slim":
            return
        # A prior full build may have populated build/lib. Remove only those
        # generated build copies so a slim wheel cannot accidentally retain
        # stale optional modules; repository sources are never touched.
        for module in SLIM_EXCLUDED_MODULES:
            path = os.path.join(self.build_lib, *module.split(".")) + ".py"
            if os.path.isfile(path):
                os.remove(path)


setup(cmdclass={"build_py": ProfileBuildPy})
