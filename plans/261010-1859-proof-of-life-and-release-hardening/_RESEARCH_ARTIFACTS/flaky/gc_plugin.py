"""pytest plugin (use: gcrun.sh / repeat.sh). Makes the cycle collector run at arbitrary points (every few
allocations) and before every test. This only moves the moment at which already-unreachable enforcer modules
are freed (a long full run frees them at moments that vary with allocation history), so their addresses can
be handed to the next module a test loads."""
import gc


def pytest_configure(config):
    gc.set_threshold(7, 1, 1)


def pytest_runtest_setup(item):
    gc.collect()
