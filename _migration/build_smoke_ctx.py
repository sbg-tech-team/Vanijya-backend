"""Mint a real JWT via /auth/dev-token and write the smoke context."""
import json, sys
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
prof, aid, postid, gid, other = open("/tmp/seed_ids.txt").read().strip().split("|")
tok = httpx.get(f"{BASE}/auth/dev-token", params={"name": "Alice"}, timeout=20).json()
json.dump({"token": tok["access_token"], "profile_id": int(prof), "article_id": aid,
           "post_id": int(postid), "group_id": gid, "other_user_id": other,
           "my_user_id": tok["user_id"]}, open("/tmp/smoke_ctx.json", "w"))
print(f"smoke context written (profile {prof}, user {tok['user_id'][:8]}…)")
