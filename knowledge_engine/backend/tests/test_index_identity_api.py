from app.services.fusion import RetrievalHit

def test_retrieval_api_preserves_model_identity_in_response_schema():
    from app.api.query import _to_chunk_result
    from app.schemas.query import QueryRetrieveResponse
    hit = RetrievalHit(chunk_id="chunk-1", score=0.8, source="vector",chunk_text="policy",
        document_id="doc-1",version_id="v1",doc_title="Policy",doc_type="standard",
        metadata={"embedding_identity": "bge-base-en:768:revision"})
    serialized = QueryRetrieveResponse(query="policy",top_k=1,chunks=[_to_chunk_result(hit)]).model_dump()
    assert serialized["chunks"][0]["index_identity"] == "bge-base-en:768:revision"
    hit.metadata = {}
    assert _to_chunk_result(hit,index_identity="verified-service-identity").index_identity == "verified-service-identity"
