"""
Background jobs for the connections module.

run_follow_count_reconciliation_job() – runs nightly
"""
import logging

log = logging.getLogger(__name__)


def run_follow_count_reconciliation_job(repo) -> dict:
    """Correct any profile.followers_count / following_count that has drifted
    from the real user_connections rows.

    add_follow/remove_follow keep these in step on the follow/unfollow path,
    but anything that writes user_connections directly — a seed script, a
    load-test cleanup — bypasses them and the stored counters silently drift.
    This is the safety net: it doesn't replace the hand-maintained counters,
    it catches what they miss.
    """
    corrected = repo.reconcile_follow_counts()
    if corrected:
        log.warning("follow-count reconciliation corrected %d profile(s)", corrected)
    return {"corrected": corrected}
