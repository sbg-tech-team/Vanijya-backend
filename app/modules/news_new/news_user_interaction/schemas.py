# Schemas:
#   NewsInteractionEventItem   — single event in a batch (article_id, event_type, value_ms?, occurred_at)
#   NewsInteractionBatchPayload — list of NewsInteractionEventItem (1-200 per batch)
#   NewsInteractionBatchResult  — {accepted: int, dropped: int}
#   NewsLikeOut, NewsSaveOut, NewsShareOut
