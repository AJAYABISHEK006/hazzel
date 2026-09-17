import os
import re

from hazzel.config import resolve_project_path
from hazzel.tools.search_files import missing_file_message

MENTION_RE = re.compile(r'(?:^|(?<=\s))@(?:"([^"]+)"|\'([^\']+)\'|`([^`]+)`|(\S+))')

MAX_MENTION_FILES = 5
MAX_MENTION_CHARS = 3000
TRAILING_PUNCT = ".,!?;:)]"

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
MAX_IMAGE_BYTES = 8_000_000
IMAGE_TOKEN_ESTIMATE = 1500

_MEDIA_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def is_image_path(target):
    name = (target or "").lower().strip()
    for ext in IMAGE_EXTS:
        if name.endswith(ext):
            return True
    return False


def guess_media_type(filename):
    name = (filename or "").lower()
    for ext, media in _MEDIA_BY_EXT.items():
        if name.endswith(ext):
            return media
    return None


def load_image_data_url(resolved):
    media = guess_media_type(str(resolved)) or "image/png"
    try:
        data = resolved.read_bytes()
    except OSError:
        return None, None, "unreadable"
    if not data:
        return None, None, "empty file"
    if len(data) > MAX_IMAGE_BYTES:
        return None, None, f"image too large ({len(data)} bytes, max {MAX_IMAGE_BYTES})"
    try:
        import base64

        b64 = base64.b64encode(data).decode("ascii")
    except Exception:
        return None, None, "unreadable"
    return f"data:{media};base64,{b64}", media, None


def collect_mention_images(targets):
    images = []
    for target in targets or []:
        if not is_image_path(target):
            continue
        try:
            resolved = resolve_project_path(target)
        except ValueError:
            continue
        try:
            if not resolved.exists() or not resolved.is_file():
                continue
        except OSError:
            continue
        try:
            if os.path.getsize(resolved) > MAX_IMAGE_BYTES or os.path.getsize(resolved) == 0:
                continue
        except OSError:
            continue
        data_url, media, err = load_image_data_url(resolved)
        if err or not data_url:
            continue
        try:
            size = os.path.getsize(resolved)
        except OSError:
            size = len(data_url)
        images.append({"path": target, "media_type": media, "data_url": data_url, "bytes": size})
        if len(images) >= MAX_MENTION_FILES:
            break
    return images


def build_user_content(text, images):
    if not images:
        return text
    parts = [{"type": "text", "text": text or ""}]
    for img in images or []:
        url = img.get("data_url") if isinstance(img, dict) else None
        if not url:
            continue
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts


def content_text_len(content):
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += len(part)
            elif isinstance(part, dict):
                if isinstance(part.get("text"), str):
                    total += len(part["text"])
                elif part.get("type") == "image_url":
                    total += IMAGE_TOKEN_ESTIMATE * 4
        return total
    return len(str(content or ""))


def parse_mentions(text):
    seen = []
    for match in MENTION_RE.finditer(text or ""):
        raw = match.group(1) or match.group(2) or match.group(3) or match.group(4) or ""
        raw = raw.strip().rstrip(TRAILING_PUNCT)
        if not raw or raw == "@":
            continue
        if raw not in seen:
            seen.append(raw)
    return seen[:MAX_MENTION_FILES]


def _read_capped(resolved):
    try:
        data = resolved.read_bytes()
    except OSError:
        return None, "unreadable"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "binary"
    lines = text.splitlines()
    numbered = [f"{i + 1:6d}| {line[:240]}" for i, line in enumerate(lines)]
    body = "\n".join(numbered)[:MAX_MENTION_CHARS]
    more = ""
    if len("\n".join(numbered)) > MAX_MENTION_CHARS or len(lines) > 80:
        more = f"\n[…{len(lines)} lines total; use read_file offset for more…]"
    return (body + more) or "(empty file)", None


def _match_skill(target):
    try:
        from hazzel import skills as _skills
        return _skills.find_skill(target)
    except Exception:
        return None


def expand_mentions(text):
    targets = parse_mentions(text)
    if not targets:
        return "", [], {}, [], []
    blocks = []
    contents = {}
    ok = []
    errors = []
    attached_skills = []
    for target in targets:
        try:
            resolved = resolve_project_path(target)
        except ValueError as error:
            resolved = None
            resolve_error = str(error)
        else:
            resolve_error = ""
        if resolved is not None and resolved.exists():
            pass
        else:
            skill = _match_skill(target)
            if skill is not None:
                try:
                    from hazzel import skills as _skills
                    body = _skills.get_skill_body(skill["name"])
                except Exception:
                    body = None
                if body:
                    blocks.append(f'<skill name="{skill["name"]}">\n{body}\n</skill>')
                    contents[target] = body
                    ok.append(target)
                    attached_skills.append(skill["name"])
                else:
                    errors.append(f"@{target}: skill found but unreadable, use /skills to retry")
                continue
            if resolved is None:
                errors.append(f"@{target}: {resolve_error}")
                continue
            errors.append(f"@{target}: {missing_file_message(target)}")
            continue
        if resolved.is_dir():
            from hazzel.tools.list_files import list_files
            result = list_files(target)
            if isinstance(result, list):
                result = "\n".join(result) or "(empty directory)"
            blocks.append(f'<file path="{target}">\n{result}\n</file>')
            contents[target] = str(result)
            ok.append(target)
            continue
        try:
            if not resolved.is_file():
                errors.append(f"@{target}: not a file")
                continue
        except OSError:
            errors.append(f"@{target}: unreadable")
            continue
        if is_image_path(target):
            try:
                size = os.path.getsize(resolved)
            except OSError:
                errors.append(f"@{target}: unreadable")
                continue
            if size == 0:
                errors.append(f"@{target}: empty file, skipped")
                continue
            if size > MAX_IMAGE_BYTES:
                errors.append(f"@{target}: image too large ({size} bytes, max {MAX_IMAGE_BYTES}), resize and retry")
                continue
            media = guess_media_type(target) or "image/png"
            blocks.append(f'<image path="{target}">\n(image attached: {media}, {size} bytes — view the attached image)\n</image>')
            contents[target] = f"(image {media}, {size} bytes attached)"
            ok.append(target)
            continue
        if os.path.getsize(resolved) > 2_000_000:
            errors.append(f"@{target}: file too large, use search_files instead")
            continue
        body, err = _read_capped(resolved)
        if err:
            errors.append(f"@{target}: {err} file, skipped")
            continue
        blocks.append(f'<file path="{target}">\n{body}\n</file>')
        contents[target] = body
        ok.append(target)
    context = ""
    if blocks:
        context = "<attached_files>\n" + "\n".join(blocks) + "\n</attached_files>"
    if errors:
        context += ("\n" if context else "") + "<mention_errors>\n" + "\n".join(errors) + "\n</mention_errors>"
    return context, ok, contents, errors, attached_skills


def strip_mentions(text):
    return MENTION_RE.sub("", text or "").strip()
