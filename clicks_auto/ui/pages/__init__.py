"""Application pages."""

from .dashboard import DashboardPage  # noqa: F401
from .history import HistoryPage  # noqa: F401
from .recorder import RecorderPage  # noqa: F401
from .run import RunPage  # noqa: F401
from .schedules import SchedulesPage  # noqa: F401
from .scripts import ScriptsPage  # noqa: F401
from .settings import SettingsPage  # noqa: F401

__all__ = [
    "DashboardPage", "HistoryPage", "RecorderPage", "RunPage", "SchedulesPage",
    "ScriptsPage", "SettingsPage",
]
