from app.core.security import create_access_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip() -> None:
    encoded = hash_password("a-long-production-password")
    assert encoded != "a-long-production-password"
    assert verify_password("a-long-production-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_access_token_contains_tenant_boundary() -> None:
    token = create_access_token(user_id="user-1", tenant_id="tenant-1", role="OWNER")
    claims = decode_token(token)
    assert claims.user_id == "user-1"
    assert claims.tenant_id == "tenant-1"
    assert claims.role == "OWNER"

