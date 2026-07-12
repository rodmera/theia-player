import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from theiaplayer.api import SubsonicClient


@pytest.fixture
def temp_cache_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.mark.asyncio
async def test_cover_art_cmyk_to_rgb_conversion(temp_cache_dir):
    # 1. Create a dummy CMYK image bytes to simulate server response
    cmyk_image_path = temp_cache_dir / "cmyk_source.jpg"
    with Image.new("CMYK", (10, 10), (0, 100, 100, 0)) as img:
        img.save(cmyk_image_path, "JPEG")
    cmyk_bytes = cmyk_image_path.read_bytes()

    # 2. Instantiate client with dummy arguments and mock HTTP response
    client = SubsonicClient(
        server="https://example.com",
        username="rodmera",
        token="test_token",
        salt="test_salt",
        art_dir=temp_cache_dir,
    )
    client._http = MagicMock()
    
    # Mock httpx response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "image/jpeg"}
    mock_resp.content = cmyk_bytes
    mock_resp.raise_for_status = MagicMock()
    
    client._http.get = AsyncMock(return_value=mock_resp)

    # 3. Call cover_art (this should download, detect CMYK, convert to RGB, and save)
    cover_id = "test_cmyk_album"
    saved_path = await client.cover_art(cover_id)

    # 4. Assertions for downloaded conversion
    assert saved_path.exists()
    with Image.open(saved_path) as saved_img:
        assert saved_img.mode == "RGB"
        print("Success: Downloaded CMYK cover art converted to RGB!")

    # 5. Test Cache Auto-Repair:
    # If the file on disk were to somehow become CMYK again (e.g. simulation of legacy cache),
    # calling cover_art should repair it upon reading the cached path.
    with Image.new("CMYK", (10, 10), (0, 100, 100, 0)) as corrupt_img:
        corrupt_img.save(saved_path, "JPEG")
        
    # Verify it is initially back to CMYK
    with Image.open(saved_path) as verify_corrupt:
        assert verify_corrupt.mode == "CMYK"

    # Call cover_art (hits cache directly since path.exists())
    re_saved_path = await client.cover_art(cover_id)

    # Assert it was auto-repaired to RGB
    assert re_saved_path == saved_path
    with Image.open(re_saved_path) as repaired_img:
        assert repaired_img.mode == "RGB"
        print("Success: Cache auto-repair corrected CMYK to RGB!")
