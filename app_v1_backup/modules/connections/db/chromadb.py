# app/db/chromadb.py — REPLACED by app/db/pgvector.py
# Vectors now live in the Postgres "Users" table (embedding vector(11) column)
# with an HNSW index via pgvector. ChromaDB is no longer used.

# import os
# import chromadb
# from dotenv import load_dotenv

# load_dotenv()

# _client = chromadb.HttpClient(
#     ssl=True,
#     host=os.getenv("CHROMA_HOST"),
#     tenant=os.getenv("CHROMA_TENANT"),
#     database=os.getenv("CHROMA_DATABASE"),
#     headers={"x-chroma-token": os.getenv("CHROMA_API_KEY")}
# )

# _collection = _client.get_or_create_collection(
#     name="commodity_users",
#     metadata={"hnsw:space": "cosine"}
# )

# def get_chroma_collection():
#     return _collection
