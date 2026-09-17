import base64

from hazzel import mentions as M
from hazzel.providers import anthropic as AP
from hazzel.tokens import estimate_messages

# 1x1 transparent PNG
PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_BYTES = base64.b64decode(PNG_B64)


def _write_img(tmp_path, monkeypatch, name="shot.png", data=PNG_BYTES):
    p = tmp_path / name
    p.write_bytes(data)
    import hazzel.config as cfg

    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    return p


def test_is_image_path():
    assert M.is_image_path("shot.png")
    assert M.is_image_path("PHOTO.JPG")
    assert M.is_image_path("a/b/c.webp")
    assert not M.is_image_path("main.py")
    assert not M.is_image_path("notes.png.txt")


def test_guess_media_type():
    assert M.guess_media_type("a.png") == "image/png"
    assert M.guess_media_type("a.jpg") == "image/jpeg"
    assert M.guess_media_type("a.jpeg") == "image/jpeg"
    assert M.guess_media_type("a.gif") == "image/gif"
    assert M.guess_media_type("a.webp") == "image/webp"


def test_expand_mentions_image(tmp_path, monkeypatch):
    _write_img(tmp_path, monkeypatch, "shot.png")
    ctx, attached, contents, errors, skills = M.expand_mentions("@shot.png explain this")
    assert "shot.png" in attached
    assert not errors
    assert "<image" in ctx
    assert "shot.png" in contents


def test_expand_mentions_image_missing(tmp_path, monkeypatch):
    import hazzel.config as cfg

    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    ctx, attached, _, errors, _ = M.expand_mentions("@missing.png what is this")
    assert attached == []
    assert errors


def test_collect_images_data_url(tmp_path, monkeypatch):
    _write_img(tmp_path, monkeypatch, "shot.png")
    imgs = M.collect_mention_images(["shot.png"])
    assert len(imgs) == 1
    assert imgs[0]["data_url"].startswith("data:image/png;base64,")
    assert imgs[0]["media_type"] == "image/png"


def test_collect_images_skips_text(tmp_path, monkeypatch):
    p = tmp_path / "a.txt"
    p.write_text("hi")
    import hazzel.config as cfg

    monkeypatch.setattr(cfg, "PROJECT_ROOT", tmp_path)
    assert M.collect_mention_images(["a.txt"]) == []


def test_build_user_content():
    text = "hello"
    assert M.build_user_content(text, []) == "hello"
    imgs = [{"path": "s.png", "media_type": "image/png", "data_url": "data:image/png;base64,AAA", "bytes": 3}]
    out = M.build_user_content(text, imgs)
    assert isinstance(out, list)
    assert out[0] == {"type": "text", "text": "hello"}
    assert out[1]["type"] == "image_url"


def test_anthropic_image_conversion():
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "see this"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{PNG_B64}"}},
        ],
    }
    system, msgs = AP._messages_to_anthropic([msg])
    assert len(msgs) == 1
    blocks = msgs[0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/png"
    assert blocks[1]["source"]["data"] == PNG_B64


def test_estimate_messages_ignores_b64():
    big = "A" * 100000
    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{big}"}},
        ],
    }
    total = estimate_messages([msg], tools=[])
    assert total < 5000


def test_session_clean_drops_image():
    from hazzel import session as S

    msg = {
        "role": "user",
        "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ],
    }
    cleaned = S._clean_message(msg)
    assert cleaned["content"] == "look"
    assert "AAA" not in cleaned["content"]
