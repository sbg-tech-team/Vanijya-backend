"""Assert migrations/001_news_v1_to_v2.sql produced the right rows."""
import os, sys
import psycopg2

PORT = os.environ.get("VJ_PGPORT", "54329")
conn = psycopg2.connect(host="127.0.0.1", port=PORT, user="vanijyaa", dbname="vanijyaa_mig")
cur = conn.cursor()

fails = []
def check(label, got, want):
    if got != want: fails.append(f"  {label}\n     got:  {got!r}\n     want: {want!r}")
def one(sql, *a):
    # pass params only when there are some: psycopg2 interpolates % otherwise,
    # which breaks every LIKE 'x%' in this file.
    cur.execute(sql, a) if a else cur.execute(sql)
    r = cur.fetchone(); return r[0] if r else None
def rows(sql, *a):
    cur.execute(sql, a) if a else cur.execute(sql)
    return cur.fetchall()

# --- the third run must have changed nothing -------------------------------
log = open("/tmp/mig_run_3.log").read()
check("third run inserted nothing (idempotent)",
      [l for l in log.split("\n") if l.startswith("INSERT") and not l.endswith(" 0")], [])

# --- articles ---------------------------------------------------------------
check("duplicate article skipped", one("SELECT count(*) FROM news_articles"), 3)
check("article ids preserved (deep links keep resolving)",
      one("SELECT count(*) FROM news_articles a JOIN news_raw_articles r ON r.id=a.id"), 3)

# app_old's 10 factors map 1:1 onto app_new's 10 clusters
check("policy_regulation -> cluster 1",
      one("SELECT cluster_id FROM news_articles WHERE title LIKE 'Govt bans%'"), 1)
check("supply_disruptions -> cluster 3",
      one("SELECT cluster_id FROM news_articles WHERE title LIKE 'Brazil%'"), 3)

# is_government is INDEPENDENT of cluster - that is the whole point of the column
check("is_government carried across",
      one("SELECT is_government FROM news_articles WHERE title LIKE 'Govt bans%'"), True)
check("is_government false where app_old said false",
      one("SELECT is_government FROM news_articles WHERE title LIKE 'Brazil%'"), False)

check("geo_category domestic -> scope national",
      one("SELECT scope FROM news_articles WHERE title LIKE 'Govt bans%'"), "national")
check("geo_category global -> scope global",
      one("SELECT scope FROM news_articles WHERE title LIKE 'Brazil%'"), "global")
check("summary built from enriched bullets",
      one("SELECT summary FROM news_articles WHERE title LIKE 'Govt bans%'"),
      "India bans exports. Traders disrupted.")
check("unenriched article is not marked classified",
      one("SELECT is_classified FROM news_articles WHERE title='Unenriched filler'"), False)
check("is_active=false -> is_archived=true",
      one("SELECT is_archived FROM news_articles WHERE title='Unenriched filler'"), True)
check("missing source name falls back to the placeholder",
      one("SELECT s.name FROM news_articles a JOIN news_sources s ON s.id=a.source_id"
          " WHERE a.title='Unenriched filler'"), "Unknown (migrated)")
check("real sources normalised out of the article rows",
      sorted(r[0] for r in rows("SELECT name FROM news_sources")),
      ["PTI", "Reuters", "Unknown (migrated)"])

# --- engagement -------------------------------------------------------------
check("every v1 interaction migrated", one("SELECT count(*) FROM news_engagement"), 6)
check("action types mapped",
      sorted(r[0] for r in rows("SELECT DISTINCT action_type FROM news_engagement")),
      ["click", "dwell", "like", "save", "share_out", "view"])
check("profile_id resolved to user_id",
      one("SELECT count(*) FROM news_engagement e JOIN profile p ON p.users_id=e.user_id"), 6)
check("dwell capped at 600s (900000ms in v1)",
      one("SELECT dwell_time_s FROM news_engagement WHERE action_type='dwell'"), 600)
check("cluster_id denormalised from the article",
      one("SELECT count(*) FROM news_engagement e JOIN news_articles a ON a.id=e.article_id"
          " WHERE e.cluster_id IS DISTINCT FROM a.cluster_id"), 0)

# --- trending & taste -------------------------------------------------------
check("trending row migrated to a neutral segment",
      one("SELECT segment_id FROM news_trending"), "migrated:v1:global")
check("velocity preserved", float(one("SELECT velocity_score FROM news_trending")), 42.5)
check("only the factor dimension becomes cluster taste",
      one("SELECT count(*) FROM user_cluster_taste"), 1)
check("taste weight = (pos-neg)/max(pos,1)",
      round(float(one("SELECT taste_weight FROM user_cluster_taste")), 3), 0.875)
check("taste event count preserved",
      one("SELECT interaction_count FROM user_cluster_taste"), 12)

# --- nothing in app_old was touched ----------------------------------------
check("app_old raw articles untouched", one("SELECT count(*) FROM news_raw_articles"), 4)
check("app_old likes untouched", one("SELECT count(*) FROM news_likes"), 1)

if fails:
    print(f"FAIL ({len(fails)})\n" + "\n".join(fails)); sys.exit(1)
print("PASS - news v1->v2 migration: ids preserved, factors->clusters 1:1, is_government "
      "carried, all 6 interactions remapped, idempotent, app_old untouched")
