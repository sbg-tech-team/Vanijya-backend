"""
Background jobs for the post recommendation engine.

run_expiry_job()         – runs every hour
run_popular_posts_sync() – runs every 15 minutes
"""




def run_expiry_job(repo) -> dict:
    """Expire embeddings past their category window and demote hot -> warm -> cold."""
    return repo.run_embedding_expiry()


def run_popular_posts_sync(repo) -> dict:
    """Rebuild the popular_posts snapshot from recent engagement."""
    return repo.rebuild_popular_posts()
