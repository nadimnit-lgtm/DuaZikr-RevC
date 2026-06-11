#!/usr/bin/env python3
"""Repository validation for Dua & Zikr — Version 00 Rev A Personal.

Run from repository root:
    python3 tools/validate.py

Validation focuses on personal debug APK readiness, clean bundled Islamic data,
canonical sectionRefs, audio-free runtime data, Tajweed foundation consistency,
Qur'anic text completeness checks, source hygiene, and safe UI/data contracts.
The accepted baseline rotation timer values are not validated or changed here.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTENT_DIR = REPO_ROOT / "app" / "src" / "main" / "assets" / "content"
CONTENT_JSON = CONTENT_DIR / "content.json"
SECTIONS_JSON = CONTENT_DIR / "sections.json"

REQUIRED_ITEM_FIELDS = [
    "id", "section", "category", "type", "main_category", "title",
    "arabic", "transliteration", "translation", "translation_ur",
    "source", "verification",
]

ALLOWED_VERIFICATION = {"quran", "hadith", "compilation"}
ALLOWED_MAIN_CATEGORY = {"Azkar", "Dua", "Kalima"}
ALLOWED_SIZE_MODE = {"short", "normal", "long", "very_long"}
ALLOWED_VERIFICATION_STATUS = {
    "verified_2_sources",
    "verified_quran_reference",
    "verified_hadith_reference",
    "traditional_compilation",
    "needs_review",
    "weak_chain_pending_review",
    "not_verified",
    "pending_review",
}

ARABIC_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
WHITESPACE_RE = re.compile(r"\s+")
WAQF_UNICODE_SIGNS = "\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC\u06DD\u06DE\u061E\u06E9"
WAQF_TOKEN_RE = re.compile(r"(^|[\s\u00a0،؛:\(\[\{])((?:قلى)|(?:صلى)|(?:لا)|[مجطزصقسع])(?=$|[\s\u00a0،؛:\.\)\]\}])")
SOURCE_SPLIT_RE = re.compile(r"\s*;\s*")
VAGUE_SOURCE_RE = re.compile(r"\b(variant|established|accepted narration|accepted wording)\b", re.I)
AUDIO_FIELD_RE = re.compile(("recitation" + "Notes") + r"|audioBase|recAudio|recBtn", re.I)


def error(message: str) -> None:
    print(f"::error::{message}")


def warning(message: str) -> None:
    print(f"::warning::{message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        error(f"invalid JSON {path.relative_to(REPO_ROOT)}: {exc}")
        return None


def normalise_arabic(value: Any) -> str:
    text = str(value or "")
    text = ARABIC_DIACRITICS_RE.sub("", text)
    text = text.replace("\u0640", "")
    text = text.translate(str.maketrans({
        "ٱ": "ا", "آ": "ا", "أ": "ا", "إ": "ا",
        "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه",
    }))
    text = WHITESPACE_RE.sub("", text)
    text = re.sub(r"[^ء-ي]", "", text)
    return text


def normalise_arabic_without_waqf(value: Any) -> str:
    text = str(value or "")
    text = re.sub(f"[{re.escape(WAQF_UNICODE_SIGNS)}]", "", text)
    text = WAQF_TOKEN_RE.sub(lambda m: m.group(1), text)
    return normalise_arabic(text)


def normalise_title(value: Any) -> str:
    return WHITESPACE_RE.sub(" ", str(value or "").strip().lower())


def valid_repeat(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    return False


def is_quranic(item: dict[str, Any]) -> bool:
    return str(item.get("verification") or "").lower() == "quran"


def has_waqf_mark(text: str) -> bool:
    return any(ch in text for ch in WAQF_UNICODE_SIGNS) or bool(WAQF_TOKEN_RE.search(text))


def walk_json(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}" if path else str(k), v
            yield from walk_json(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield f"{path}[{i}]", v
            yield from walk_json(v, f"{path}[{i}]")


def source_tokens(source: str) -> list[str]:
    return [p.strip().lower() for p in SOURCE_SPLIT_RE.split(source or "") if p.strip()]


def validate_all_json_files() -> int:
    bad = 0
    json_files = sorted(Path(p) for p in glob.glob(str(CONTENT_DIR / "*.json")))
    if not json_files:
        error(f"no JSON files found under {CONTENT_DIR.relative_to(REPO_ROOT)}")
        return 1
    for path in json_files:
        if load_json(path) is None:
            bad = 1
    return bad


def validate_runtime_text_is_audio_free() -> int:
    bad = 0
    runtime_paths = [
        REPO_ROOT / "app" / "src" / "main" / "assets",
        REPO_ROOT / "app" / "src" / "main" / "java",
        REPO_ROOT / "app" / "src" / "main" / "res",
    ]
    for base in runtime_paths:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_dir() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".jar"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if AUDIO_FIELD_RE.search(text):
                error(f"audio or legacy recitation reference found in runtime file: {path.relative_to(REPO_ROOT)}")
                bad = 1
    return bad


def validate_content_schema() -> int:
    bad = 0
    content = load_json(CONTENT_JSON)
    sections_data = load_json(SECTIONS_JSON)

    if not isinstance(content, dict):
        error("content.json must be a JSON object")
        return 1

    for path, value in walk_json(content):
        if AUDIO_FIELD_RE.search(str(path)):
            error(f"legacy audio/recitation field exists in content.json at {path}")
            bad = 1
        if isinstance(value, str) and AUDIO_FIELD_RE.search(value):
            error(f"legacy audio/recitation text exists in content.json at {path}")
            bad = 1

    items = content.get("items")
    if not isinstance(items, list) or not items:
        error("content.json must contain a non-empty items array")
        return 1

    if content.get("app") != "Dua & Zikr":
        error("content.json app must be 'Dua & Zikr'")
        bad = 1
    if content.get("version_name") != "Version 00 Rev A Personal":
        error("content.json version_name must be 'Version 00 Rev A Personal'")
        bad = 1

    if content.get("total_items") != len(items):
        error(f"content.json total_items mismatch: declared {content.get('total_items')} but found {len(items)} items")
        bad = 1

    ids: list[str] = []
    canonical_arabic: dict[str, str] = {}
    canonical_arabic_waqfless: dict[str, str] = {}
    display_arabic: dict[tuple[str, str], str] = {}
    display_titles: dict[tuple[str, str], str] = {}
    section_counts: Counter[str] = Counter()
    verification_counts: Counter[str] = Counter()
    quranic_count = 0
    quranic_with_tajweed = 0
    quranic_with_waqf = 0

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            error(f"content.json item {index} must be an object")
            bad = 1
            continue

        item_id = str(item.get("id") or f"item_{index}")
        ids.append(item_id)
        section = str(item.get("section") or "")
        arabic = str(item.get("arabic") or "")
        source = str(item.get("source") or "")
        title = str(item.get("title") or "")

        for field in REQUIRED_ITEM_FIELDS:
            value = item.get(field)
            if value is None or str(value).strip() == "":
                error(f"missing required field '{field}' in item {index}: {item_id}")
                bad = 1

        if not valid_repeat(item.get("repeat")):
            error(f"invalid repeat value {item.get('repeat')!r} in item {item_id}")
            bad = 1

        verification = str(item.get("verification") or "").strip().lower()
        verification_counts[verification] += 1
        if verification not in ALLOWED_VERIFICATION:
            error(f"invalid verification value '{verification or 'blank'}' in item {item_id}")
            bad = 1

        vstatus = str(item.get("verification_status") or "").strip()
        if vstatus and vstatus not in ALLOWED_VERIFICATION_STATUS:
            warning(f"non-standard verification_status '{vstatus}' in item {item_id}")

        main_cat = str(item.get("main_category") or "").strip()
        if main_cat not in ALLOWED_MAIN_CATEGORY:
            error(f"invalid main_category '{main_cat}' in item {item_id}")
            bad = 1

        size_mode = str(item.get("size_mode") or "").strip()
        if size_mode and size_mode not in ALLOWED_SIZE_MODE:
            error(f"invalid size_mode '{size_mode}' in item {item_id}")
            bad = 1

        norm = normalise_arabic(arabic)
        if norm:
            prev = canonical_arabic.get(norm)
            if prev and prev != item_id:
                if verification == "quran":
                    warning(f"same Qur'anic verse reused across occasions (allowed): {prev} and {item_id}")
                else:
                    error(f"duplicate normalized canonical Arabic: {prev} and {item_id}")
                    bad = 1
            canonical_arabic[norm] = item_id

        norm_waqfless = normalise_arabic_without_waqf(arabic)
        if norm_waqfless:
            prev = canonical_arabic_waqfless.get(norm_waqfless)
            if prev and prev != item_id:
                if verification == "quran":
                    warning(f"same Qur'anic verse reused after removing Waqf (allowed): {prev} and {item_id}")
                else:
                    error(f"duplicate canonical Arabic after removing Waqf marks: {prev} and {item_id}")
                    bad = 1
            canonical_arabic_waqfless[norm_waqfless] = item_id

        refs = item.get("sectionRefs")
        display_refs = refs if isinstance(refs, list) and refs else [item]
        seen_ref_sections: set[str] = set()
        if not isinstance(refs, list) or not refs:
            error(f"missing sectionRefs for canonical item {item_id}")
            bad = 1

        for r_index, ref in enumerate(display_refs, start=1):
            if not isinstance(ref, dict):
                error(f"sectionRefs entry {r_index} in item {item_id} must be an object")
                bad = 1
                continue
            ref_section = str(ref.get("section") or section)
            if not ref_section:
                error(f"missing section in sectionRefs entry {r_index} for item {item_id}")
                bad = 1
            if ref_section in seen_ref_sections:
                error(f"duplicate section reference '{ref_section}' in item {item_id}")
                bad = 1
            seen_ref_sections.add(ref_section)
            section_counts[ref_section] += 1

            if "repeat" in ref and not valid_repeat(ref.get("repeat")):
                error(f"invalid repeat value {ref.get('repeat')!r} in sectionRef {r_index} for item {item_id}")
                bad = 1

            if norm and ref_section:
                key = (ref_section, norm)
                prev = display_arabic.get(key)
                if prev and prev != item_id:
                    error(f"duplicate Arabic content in display section '{ref_section}': {prev} and {item_id}")
                    bad = 1
                display_arabic[key] = item_id

            ref_title = normalise_title(ref.get("title") or title)
            if ref_title and ref_section:
                key = (ref_section, ref_title)
                prev_t = display_titles.get(key)
                if prev_t and prev_t != item_id:
                    error(f"duplicate title '{ref.get('title') or title}' in section '{ref_section}': {prev_t} and {item_id}")
                    bad = 1
                display_titles[key] = item_id

        parts = source_tokens(source)
        if len(parts) != len(set(parts)):
            error(f"duplicate source reference inside source field for item {item_id}: {source}")
            bad = 1
        if VAGUE_SOURCE_RE.search(source):
            error(f"vague source wording remains in source field for item {item_id}: {source}")
            bad = 1

        norm_for_completeness = normalise_arabic(arabic)
        if "ayat al-kursi" in title.lower() or "2:255" in source.lower():
            if len(norm_for_completeness) < 170 or "اللهلاالها" not in norm_for_completeness or "وهوالعليالعظيم" not in norm_for_completeness:
                error(f"incomplete Ayat al-Kursi text in item {item_id}")
                bad = 1

        claims_last_two = "last two ayat" in title.lower() or "last two" in title.lower() or "2:285-286" in source.lower() or "2:285–286" in source.lower()
        if claims_last_two:
            if len(norm_for_completeness) < 280 or "امنالرسول" not in norm_for_completeness or "لايكلفالله" not in norm_for_completeness:
                error(f"incomplete last two verses of Al-Baqarah in item {item_id}")
                bad = 1

        if "complete" in title.lower() and len(arabic) < 80:
            error(f"title claims complete wording but Arabic is too short in item {item_id}")
            bad = 1

        if has_waqf_mark(arabic):
            quranic_with_waqf += 1
            if re.search(r"[۝۩۞؞]\s+[۝۩۞؞]", arabic):
                error(f"consecutive Quranic marks need review in item {item_id}")
                bad = 1

        if is_quranic(item):
            quranic_count += 1
            if content.get("tajweed_available") is True:
                if item.get("tajweed_available") is not True or not str(item.get("tajweed_html") or "").strip():
                    error(f"Qur'anic item missing Tajweed markup while Tajweed is enabled: {item_id}")
                    bad = 1
                else:
                    quranic_with_tajweed += 1
        else:
            if item.get("tajweed_available") is True or item.get("tajweed_html"):
                error(f"non-Qur'anic item has Tajweed markup enabled: {item_id}")
                bad = 1

    for item_id, count in Counter(ids).items():
        if count > 1:
            error(f"duplicate item id found: {item_id} (x{count})")
            bad = 1

    if content.get("tajweed_available") is True and quranic_count and quranic_with_tajweed != quranic_count:
        error(f"Tajweed availability mismatch: {quranic_with_tajweed} of {quranic_count} Qur'anic items have markup")
        bad = 1

    if content.get("tajweed_available") is False:
        for item in items:
            if item.get("tajweed_available") or item.get("tajweed_html"):
                error("content tajweed_available is false but item-level Tajweed markup exists")
                bad = 1
                break

    if quranic_count and quranic_with_waqf == 0:
        error("Waqf support is enabled but no Qur'anic item contains Waqf marks")
        bad = 1

    if isinstance(sections_data, dict) and isinstance(sections_data.get("sections"), list):
        declared_keys = set()
        for section_obj in sections_data["sections"]:
            if not isinstance(section_obj, dict):
                error("sections.json contains a non-object section entry")
                bad = 1
                continue
            key = str(section_obj.get("key") or "")
            declared_keys.add(key)
            if not key:
                error("sections.json contains a section without key")
                bad = 1
                continue
            declared_count = section_obj.get("count")
            actual_count = section_counts.get(key, 0)
            if actual_count == 0:
                error(f"empty section declared or used with no display references: {key}")
                bad = 1
            if declared_count != actual_count:
                error(f"sections.json count mismatch for {key}: declared {declared_count}, found {actual_count}")
                bad = 1
        for used_key in section_counts:
            if used_key and used_key not in declared_keys:
                error(f"section '{used_key}' used by items but not declared in sections.json")
                bad = 1
    else:
        error("sections.json must contain a sections array")
        bad = 1

    actual_display_items = sum(section_counts.values())
    if content.get("total_display_items") != actual_display_items:
        error(f"content.json total_display_items mismatch: declared {content.get('total_display_items')} but found {actual_display_items}")
        bad = 1

    summary = ", ".join(f"{key or 'blank'}={value}" for key, value in sorted(verification_counts.items()))
    print(f"Verification summary: {summary}")
    print(f"Item count: {len(items)} canonical, {actual_display_items} display references, {quranic_count} Qur'anic items")
    print(f"Tajweed: {quranic_with_tajweed}/{quranic_count} Qur'anic items prepared")
    print(f"Waqf-marked Qur'anic records: {quranic_with_waqf}")
    return bad


def main() -> int:
    bad = 0
    bad |= validate_all_json_files()
    bad |= validate_runtime_text_is_audio_free()
    bad |= validate_content_schema()
    if bad:
        error("Dua & Zikr validation failed")
        return 1
    print("Dua & Zikr validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
