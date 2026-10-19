"""While SESSIONS_SUSPENDED is set, run_daily_sessions() must start nothing: no session claim,
no orphan check, no runner imports. Every entry point (cron, startup auto-trigger, POST /trigger,
--run-now) calls this one function."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api import session_job  # noqa: E402


def test_suspended_run_daily_sessions_starts_nothing(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError('touched live-session state while suspended')

    monkeypatch.setattr(session_job, 'SESSIONS_SUSPENDED', True)
    monkeypatch.setattr(session_job, '_claim_session_today', boom)
    monkeypatch.setattr(session_job, '_check_orphaned_positions', boom)
    monkeypatch.setattr(session_job, '_is_market_holiday_today', boom)
    assert session_job.run_daily_sessions() is None


def test_sessions_are_suspended_by_default():
    assert session_job.SESSIONS_SUSPENDED is True
