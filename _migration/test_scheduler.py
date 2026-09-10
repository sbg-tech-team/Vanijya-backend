"""Scheduler gate — the shadowing bugs made every cron job unreachable.
    python3.12 _migration/test_scheduler.py
"""
import _boot  # noqa: F401
import os, sys

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")

# a package of the same name shadows the module, so these must not come back
for dead in ["../app/core/scheduler", "../app/core/redis",
             "../app/modules/post/recommendation/jobs"]:
    check(f"shadowing package {os.path.basename(dead)}/ removed", os.path.isdir(dead), False)

import app.core.scheduler as sched
check("app.core.scheduler resolves to the module", sched.__file__.replace("\\", "/").endswith("core/scheduler.py"), True)
check("start() reachable", hasattr(sched, "start"), True)

sched.start()
ids = sorted(jid for _, jid in sched.scheduler.jobs)
check("all app_old jobs registered", ids, sorted([
    "news_new.pipeline", "news_new.trending", "news_new.archive",
    "posts.expiry", "posts.popular", "posts.taste_update", "posts.ignore_detect",
    "recommendation.global_taste_promotion", "server.keepalive"]))

# app_old guarded the news jobs against overlapping runs
src = open("../app/core/scheduler.py").read()
for jid in ["news_new.pipeline", "news_new.trending"]:
    i = src.index(f'id="{jid}"')
    blk = src[max(0, i - 260): i + 140]
    check(f"{jid} has max_instances=1", "max_instances=1" in blk, True)
    check(f"{jid} has coalesce=True", "coalesce=True" in blk, True)

from app.modules.post.recommendation import jobs
check("post jobs resolves to jobs.py", jobs.__file__.replace("\\", "/").endswith("recommendation/jobs.py"), True)
check("run_expiry_job reachable", hasattr(jobs, "run_expiry_job"), True)
check("run_popular_posts_sync reachable", hasattr(jobs, "run_popular_posts_sync"), True)

from app.core.redis_client import get_redis
check("single redis client module", callable(get_redis), True)

if fails:
    print("FAIL\n" + "\n".join(fails)); sys.exit(1)
print("PASS - scheduler: 10 jobs registered, shadowing packages gone, news job guards restored")
