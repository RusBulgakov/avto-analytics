"""Юнит-тесты единой нормализации городов (t-0014) — чистая логика, без БД.

Главный регресс-кейс: паттерн '\\s*-\\s*' без обязательных пробелов вокруг
дефиса однажды испортил 18,481 значение 'ust-kamenogorsk' → 'ust'
(правило CLAUDE.md). Дефис ВНУТРИ слова резать нельзя ни при каких
входах — суффикс " - ..." срезается только с пробелом ПЕРЕД дефисом.
"""
import pytest

from parsers.common.city_normalizer import CITY_ALIASES, normalize_city


# ── Регресс инцидента ust-kamenogorsk: дефисы внутри слов неприкосновенны ──

def test_ust_kamenogorsk_preserved_exactly():
    # THE incident: 18,481 строк 'ust-kamenogorsk' превратились в 'ust'
    assert normalize_city("ust-kamenogorsk") == "ust-kamenogorsk"


def test_hyphenated_values_never_truncated():
    assert normalize_city("Усть-Каменогорск") == "ust-kamenogorsk"
    assert normalize_city("Нур-Султан") == "astana"
    assert normalize_city("Алма-Ата") == "almaty"
    # Неизвестный дефисный город — остаётся целиком, не режется до префикса
    assert normalize_city("some-unknown-town") == "some-unknown-town"


def test_suffix_stripped_only_with_space_before_dash():
    # " - что-то" суффикс режется (пробел перед дефисом есть)
    assert normalize_city("Костанай - Сегодня в") == "kostanai"
    assert normalize_city("Павлодар -") == "pavlodar"
    # дефис без пробела перед ним — НЕ суффикс
    assert normalize_city("ust-kamenogorsk - вчера") == "ust-kamenogorsk"


# ── Alias-варианты → canonical slug ──

@pytest.mark.parametrize("raw,expected", [
    # Актау: латиница, транслит с q, казахская кириллица
    ("Aktau", "aktau"),
    ("Aqtau", "aktau"),
    ("Ақтау", "aktau"),
    ("актау", "aktau"),
    # Атырау
    ("Атырау", "atyrau"),
    ("Atyrau", "atyrau"),
    ("Гурьев", "atyrau"),
    # Усть-Каменогорск / Өскемен / Oskemen
    ("Oskemen", "ust-kamenogorsk"),
    ("Өскемен", "ust-kamenogorsk"),
    ("ust kamenogorsk", "ust-kamenogorsk"),
    # Семей / Семипалатинск / kolesa-quirk semei
    ("Семей", "semey"),
    ("Семипалатинск", "semey"),
    ("semei", "semey"),
    # Астана и её исторические имена
    ("Астана", "astana"),
    ("Nur-Sultan", "astana"),
    ("Нұр-Сұлтан", "astana"),
    ("Целиноград", "astana"),
    # Алматы
    ("Алматы", "almaty"),
    ("Alma-Ata", "almaty"),
    # Шымкент
    ("Шымкент", "shymkent"),
    ("Чимкент", "shymkent"),
    ("Chimkent", "shymkent"),
    # прочие
    ("Қарағанды", "karaganda"),
    ("Qostanay", "kostanai"),
    ("oral", "uralsk"),
    ("Орал", "uralsk"),
])
def test_alias_variants(raw, expected):
    assert normalize_city(raw) == expected


def test_canonical_slugs_idempotent():
    # Повторная нормализация canonical slug'а ничего не меняет
    for slug in ("almaty", "astana", "shymkent", "ust-kamenogorsk",
                 "semey", "kostanai", "atyrau", "balpyk-bi"):
        assert normalize_city(slug) == slug


def test_all_alias_values_are_normalize_fixpoints():
    # Каждый canonical из карты — неподвижная точка normalize_city
    for canonical in set(CITY_ALIASES.values()):
        assert normalize_city(canonical) == canonical, canonical


# ── Регистр и пробелы ──

def test_case_insensitive_and_whitespace():
    assert normalize_city("  АЛМАТЫ  ") == "almaty"
    assert normalize_city("аЛмАтЫ") == "almaty"
    assert normalize_city("Усть-Каменогорск  ") == "ust-kamenogorsk"
    # внутренние пробелы схлопываются перед alias-lookup
    assert normalize_city("балпык   би") == "balpyk-bi"


# ── Неизвестные города: pass-through через безопасный slugify ──

def test_unknown_latin_slugified():
    assert normalize_city("Zaisan") == "zaisan"
    assert normalize_city("Some Town") == "some-town"


def test_unknown_cyrillic_kept_cyrillic():
    # Без алиаса не транслитерируем «наугад» — стабильный кириллический slug
    assert normalize_city("Зайсан") == "зайсан"
    assert normalize_city("Новая Бухтарма") == "новая-бухтарма"


def test_unknown_never_dropped_to_prefix():
    assert normalize_city("kaskelen-north") == "kaskelen-north"


# ── Пустые значения ──

@pytest.mark.parametrize("raw", [None, "", "0", "   "])
def test_empty_values_return_none(raw):
    assert normalize_city(raw) is None
