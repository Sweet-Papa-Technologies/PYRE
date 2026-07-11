from pyre import errors
from pyre._asset_store import AssetStoreError
from pyre._platform import PlatformUnavailable
from pyre.analytics import AnalyticsLimitError
from pyre.candid import CandidError
from pyre.tasks import TaskError
from pyre.xnet import XNetError


def walk(base):
    found = []
    for child in base.__subclasses__():
        found.append(child); found.extend(walk(child))
    return found


def test_all_existing_pyre_errors_have_stable_machine_codes():
    for error in [errors.PyreError] + walk(errors.PyreError):
        assert isinstance(error.code, str)
        assert error.code.startswith("PYRE-")


def test_vnext_error_families_have_stable_machine_codes():
    for error in (AssetStoreError, PlatformUnavailable, AnalyticsLimitError,
                  CandidError, TaskError, XNetError):
        assert isinstance(error.code, str)
        assert error.code.startswith("PYRE-")
