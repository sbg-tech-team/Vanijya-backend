# Audio Calling — Frontend Contract (SUPERSEDED)

> **Do not build against this document.** It is the pre-implementation design note,
> kept only so old links resolve. Parts of it describe behaviour that was never built.
>
> **Use [`calling_api_contract.md`](calling_api_contract.md) instead** — captured from
> the running service, not from the plan.

Known ways this document is wrong:

- **§8 shows a `direction` field on the in-chat call card.** It does not exist. One
  message row is shared by both participants, so direction is derived client-side by
  comparing `sender` to your own user id.
- **§4 implies only an accepted participant may mint a Stream token.** The caller is
  `joined` from the moment the call is created and can re-mint at any time, which is how
  a caller rejoins after an app restart.
- **The status header says calling is pending credentials.** It has been implemented,
  deployed and tested since.
- Device push tokens are now one row per device (`POST /calls/devices`), not one per user.

The original text is in git history: `git show HEAD:documentation/audio_calling_contract.md`
