async def test_approved_import_requires_import_id(client, actor_headers) -> None:
    brand_response = await client.post(
        "/api/v1/brand-profiles",
        headers=actor_headers,
        json={
            "name": "Import Brand",
            "language": "en",
            "caption_style_defaults": {},
            "overlay_policy": {},
            "music_policy": {},
            "platform_defaults": {},
        },
    )
    assert brand_response.status_code == 200

    response = await client.post(
        "/api/v1/source-videos",
        headers=actor_headers,
        json={
            "brand_profile_id": brand_response.json()["id"],
            "rights_attestation": True,
            "source_type": "approved_import",
            "provenance": {
                "provenance_type": "approved_import",
                "provider": "manual",
                "source_uri": "https://example.com/video",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
