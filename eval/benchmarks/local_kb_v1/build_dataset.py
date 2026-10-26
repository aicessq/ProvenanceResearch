"""Build source-anchored candidate annotations; never mark human verification true."""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent


def norm(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())


def build():
    pages = {}
    for path in (ROOT / "eval/corpus/text").glob("*.pages.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            pages[row["doc_id"], row["page"]] = row["text"]
    old = {q["id"]: q for q in map(json.loads, (ROOT / "eval/questions/questions.v1.jsonl").read_text(encoding="utf-8").splitlines())}
    rows = []
    for number in [*range(1, 11), *range(16, 22)]:
        q = old[f"q{number:03d}"]
        facts = []
        for quote in q["required_points"]:
            matches = [loc for loc in q["expected_locator"] if norm(quote) in norm(pages.get((loc["doc_id"], loc["page"]), ""))]
            assert matches, (q["id"], quote)
            facts.append({"doc_id": matches[0]["doc_id"], "page": matches[0]["page"], "quote": quote})
        rows.append({"id": f"zh-{number:03d}", "question": q["question"], "language": "zh", "category": "single" if number <= 10 else "multi_source", "expected": "answered", "facts": facts, "origin": q["id"], "human_verified": False})

    specs = [
        ("rfc_6749", 6, "Who qualifies as a resource owner in OAuth 2.0?", "An entity capable of granting access to a protected resource."),
        ("rfc_6749", 6, "Which OAuth role hosts protected resources and accepts access tokens?", "The server hosting the protected resources, capable of accepting and responding to protected resource requests using access tokens."),
        ("rfc_6749", 6, "What does an OAuth authorization server issue after authentication and authorization?", "The server issuing access tokens to the client after successfully authenticating the resource owner and obtaining authorization."),
        ("rfc_6749", 8, "How is an OAuth authorization code obtained without requesting authorization directly from the resource owner?", "The authorization code is obtained by using an authorization server as an intermediary between the client and resource owner."),
        ("rfc_6749", 10, "What are OAuth access tokens used for?", "Access tokens are credentials used to access protected resources."),
        ("rfc_6749", 10, "What is the purpose of an OAuth refresh token?", "Refresh tokens are credentials used to obtain access tokens."),
        ("rfc_6749", 11, "May OAuth refresh tokens be sent to resource servers?", "refresh tokens are intended for use only with authorization servers and are never sent to resource servers."),
        ("rfc_6749", 10, "Must an OAuth authorization server always issue a refresh token?", "Issuing a refresh token is optional at the discretion of the authorization server."),
        ("rfc_7519", 9, "What does the JWT iss claim identify?", 'The "iss" (issuer) claim identifies the principal that issued the JWT.'),
        ("rfc_7519", 9, "What is the meaning of the JWT sub claim?", 'The "sub" (subject) claim identifies the principal that is the subject of the JWT.'),
        ("rfc_7519", 9, "Which recipients are identified by a JWT aud claim?", 'The "aud" (audience) claim identifies the recipients that the JWT is intended for.'),
        ("rfc_7519", 9, "Can a JWT be accepted on or after its exp time?", 'The "exp" (expiration time) claim identifies the expiration time on or after which the JWT MUST NOT be accepted for processing.'),
        ("rfc_7519", 10, "What acceptance restriction is specified by the JWT nbf claim?", 'The "nbf" (not before) claim identifies the time before which the JWT MUST NOT be accepted for processing.'),
        ("rfc_7519", 10, "What timestamp does the JWT iat claim identify?", 'The "iat" (issued at) claim identifies the time at which the JWT was issued.'),
        ("rfc_7519", 10, "What is supplied by the JWT jti claim?", 'The "jti" (JWT ID) claim provides a unique identifier for the JWT.'),
        ("rfc_7519", 6, "How are the URL-safe parts of a compact JWT separated?", "URL-safe parts separated by period ('.') characters."),
        ("rfc_8446", 19, "Does TLS 1.3 early data provide forward secrecy?", "This data is not forward secret, as it is encrypted solely under keys derived using the offered PSK."),
        ("rfc_8446", 19, "Does TLS 1.3 guarantee non-replay for 0-RTT across connections?", "There are no guarantees of non-replay between connections."),
        ("rfc_8446", 19, "What random value protects ordinary TLS 1.3 1-RTT data against replay?", "Protection against replay for ordinary TLS 1.3 1-RTT data is provided via the server's Random value"),
        ("rfc_8446", 8, "Which TLS handshake messages are encrypted after ServerHello in TLS 1.3?", "All handshake messages after the ServerHello are now encrypted."),
        ("rfc_8446", 9, "Which ClientHello extension negotiates the TLS version instead of legacy_version?", 'The "supported_versions" ClientHello extension can be used to negotiate the version of TLS to use, in preference to the legacy_version field of the ClientHello.'),
        ("rfc_8446", 8, "Which primitive underlies the redesigned TLS 1.3 key derivation?", "HKDF) is used as an underlying primitive."),
        ("us_nist_sp800_207", 15, "Does enterprise network location exempt communication from security protections in zero trust?", "All communication is secured regardless of network location."),
        ("us_nist_sp800_207", 15, "On what session basis does zero trust grant access to individual enterprise resources?", "Access to individual enterprise resources is granted on a per-session basis."),
        ("us_nist_ai100_1", 25, "What are the four high-level functions of the NIST AI RMF Core?", "the Core is composed of four functions: GOVERN, MAP, MEASURE, and MANAGE."),
        ("us_nist_ai100_1", 7, "Is NIST AI RMF intended to be voluntary and specific to one sector?", "The Framework is intended to be voluntary, rights-preserving, non-sector-specific, and use-case agnostic"),
    ]
    en = []
    for i, (doc, page, question, quote) in enumerate(specs, 1):
        assert norm(quote) in norm(pages[doc, page]), (i, doc, quote)
        en.append({"id": f"en-{i:03d}", "question": question, "language": "en", "category": "single", "expected": "answered", "facts": [{"doc_id": doc, "page": page, "quote": quote}], "human_verified": False})
    pairs = [(4, 11), (6, 16), (0, 8), (12, 23), (19, 24), (10, 25)]
    for i, (a, b) in enumerate(pairs, 27):
        en.append({"id": f"en-{i:03d}", "question": "Answer both using the specified documents: " + en[a]["question"] + " Also, " + en[b]["question"], "language": "en", "category": "multi_source", "expected": "answered", "facts": en[a]["facts"] + en[b]["facts"], "human_verified": False})
    rows.extend(en)
    for number in range(39, 51):
        q = old[f"q{number:03d}"]
        rows.append({"id": f"negative-{number:03d}", "question": q["question"], "language": "zh", "category": "insufficient", "expected": "refused", "facts": [], "reason": q["refuse_reason"], "origin": q["id"], "human_verified": False})
    assert len(rows) == 60
    data = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    (OUT / "questions.jsonl").write_text(data, encoding="utf-8", newline="\n")
    manifest = [r for r in map(json.loads, (ROOT / "eval/corpus/manifest.jsonl").read_text(encoding="utf-8").splitlines()) if r["in_repo"] and r["text_layer_ok"]]
    config = {"version": "local-kb-v1", "questions_sha256": hashlib.sha256(data.encode()).hexdigest(), "documents": [{k: r[k] for k in ["doc_id", "filename", "sha256", "lang", "source_url", "title"]} for r in manifest], "retrieval_repeats": 3, "retrieval_k": [1, 5, 10], "agent_repeats": 1, "agent_variants": ["reference", "current"], "budget": {"max_rounds": 3, "max_tool_calls": 5, "max_tokens": 8000, "deadline_seconds": 120}, "max_output_tokens_per_call": 1024, "temperature": 0, "concurrency": 3, "human_verified": 0, "gold_policy": "source-span anchored candidate annotations, not human-adjudicated semantic gold", "negative_policy": "closed corpus only; no web, memory, prediction or inferred missing facts", "languages": {"en_answerable": 32, "zh_answerable": 16, "zh_insufficient": 12}}
    (OUT / "freeze.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("Built", len(rows), "questions and", len(manifest), "fixed documents")


if __name__ == "__main__":
    build()
