"""
common/city_normalizer.py
Единая нормализация городов для ВСЕХ парсеров.

Выходная конвенция — latin slug в нижнем регистре ('almaty',
'ust-kamenogorsk'), та же что исторически лежит в listings.city и по
которой матчится _CITY_COORDS в backend/app/api/v1/endpoints/analytics.py
(каждый canonical slug из CITY_ALIASES, отображаемый на карте, должен
иметь там координаты).

Пайплайн normalize_city():
  1. None / "" / "0" → None
  2. trim + схлопывание внутренних пробелов
  3. срез суффикса " - ..." ("Костанай - Сегодня в" → "Костанай").
     ВНИМАНИЕ: пробел ПЕРЕД дефисом обязателен (r"\\s+-"). Паттерн
     r"\\s*-\\s*" без обязательных пробелов однажды испортил 18,481
     значение 'ust-kamenogorsk' → 'ust' (см. CLAUDE.md). Дефис внутри
     слова НИКОГДА не должен резать строку — покрыто регресс-тестом.
  4. alias-lookup по casefold: кириллица RU/KZ, латинские транслиты,
     исторические имена → canonical slug
  5. fallback — безопасный slugify: casefold, пробелы → дефис, дефисы
     внутри слов сохраняются, строка никогда не усекается до префикса.
     Кириллица без алиаса остаётся кириллицей (транслитерации «наугад»
     нет — лучше стабильный кириллический slug, чем кривой латинский).

Расширение карты: добавляй пару 'вариант (casefold)': 'canonical-slug'.
Canonical slug городов, которые должны показываться на карте, обязан
присутствовать в _CITY_COORDS бэкенда.
"""
import re
from typing import Optional

# Вариант написания (casefold) → canonical latin slug.
# База перенесена из parsers/common/db.py::_CITY_NORMALIZATIONS (t-0014),
# расширена латинскими транслитами, казахскими названиями и историческими
# именами городов.
CITY_ALIASES = {
    # 20 крупнейших городов (есть в _CITY_COORDS — отображаются на карте)
    'алматы': 'almaty', 'астана': 'astana', 'шымкент': 'shymkent',
    'караганда': 'karaganda', 'актобе': 'aktobe', 'актау': 'aktau',
    'костанай': 'kostanai', 'павлодар': 'pavlodar',
    'талдыкорган': 'taldykorgan', 'уральск': 'uralsk', 'атырау': 'atyrau',
    'тараз': 'taraz', 'усть-каменогорск': 'ust-kamenogorsk', 'семей': 'semey',
    'кокшетау': 'kokshetau', 'кызылорда': 'kyzylorda',
    'петропавловск': 'petropavlovsk', 'темиртау': 'temirtau',
    'туркестан': 'turkestan', 'экибастуз': 'ekibastuz',
    # Средние города (есть в _CITY_COORDS)
    'жезказган': 'zhezkazgan', 'риддер': 'ridder', 'балхаш': 'balkhash',
    'кентау': 'kentau', 'жанаозен': 'zhanaozen', 'капчагай': 'kapchagay',
    'рудный': 'rudny', 'степногорск': 'stepnogorsk', 'арыс': 'arys',
    'арал': 'aral', 'аркалык': 'arkalyk', 'хромтау': 'khromtau',
    'жетысай': 'zhetisay', 'сатпаев': 'satpayev', 'аксу': 'aksu',
    'шу': 'shu',
    # Long-tail — пригороды и райцентры. На карту не выводятся (нет в
    # _CITY_COORDS), но slug-consistency для filters/aggregations.
    # Алматинская область
    'талгар': 'talgar', 'каскелен': 'kaskelen', 'есик': 'esik',
    'жаркент': 'zharkent', 'текели': 'tekeli', 'уштобе': 'ushtobe',
    'кордай': 'kordai', 'отеген': 'otegen', 'алмалыбак': 'almalybak',
    'бесагаш': 'besagash', 'байтерек': 'bayterek',
    # Конаев = переименованный Капчагай (с 2022)
    'конаев': 'kapchagay', 'конаев (капшагай)': 'kapchagay',
    'капшагай (конаев)': 'kapchagay', 'капшагай': 'kapchagay',
    # Шымкентская область
    'сарыагаш': 'saryagash', 'аксукент': 'aksukent', 'шиели': 'shieli',
    'мерке': 'merke', 'арысь': 'arys',
    # Атырауская / Мангистау
    'кульсары': 'kulsary', 'бейнеу': 'beineu', 'балыкши': 'balykshi',
    'еркинкала': 'erkinkala',
    # Северный Казахстан
    'щучинск': 'schuchinsk', 'булаево': 'bulayevo', 'бишкуль': 'bishkul',
    'акколь': 'akkol', 'атбасар': 'atbasar', 'нура': 'nura',
    'аягоз': 'ayagoz',
    # Восточный Казахстан
    'зыряновск': 'zyryanovsk', 'кокпекты': 'kokpekty',
    'белоусовка': 'belousovka', 'прапорщиково': 'praporshchikovo',
    # Западный Казахстан
    'аксай': 'aksai', 'аральск': 'aralsk', 'жолбарыса калшораева': 'zholbarys',
    # Костанайская область
    'затобольск': 'zatobolsk', 'житикара': 'zhitikara',
    # Прочие small towns (нормализуем для полной consistency)
    'шахтинск': 'shakhtinsk', 'алга': 'alga', 'бектобе': 'bektobe',
    'бесколь': 'beskol', 'белоярка': 'beloyarka', 'байтобе': 'baytobe',
    'муткенова': 'mutkenova', 'чапаево': 'chapayevo',
    'мичуринское': 'michurinskoye', 'нуркен': 'nurken',
    'валиханово': 'valikhanovo', 'акбулак': 'akbulak',
    'интернациональное': 'internatsionalnoye', 'сырдарья': 'syrdaria',
    'балпык би': 'balpyk-bi', 'айдарлы': 'aydarly', 'алмалы': 'almaly',
    'баянбай': 'bayanbay',
    # Старые алиасы и kolesa-quirks
    'semei': 'semey',
    'kostanay': 'kostanai',  # альт-вариант slug
    'oral': 'uralsk',        # казахское имя Уральска
    # ── Расширение t-0014: латинские транслиты + казахские названия ──
    # Актау
    'aqtau': 'aktau', 'ақтау': 'aktau',
    # Актобе
    'aqtobe': 'aktobe', 'ақтөбе': 'aktobe',
    # Усть-Каменогорск (каз. Өскемен / Oskemen)
    'oskemen': 'ust-kamenogorsk', 'өскемен': 'ust-kamenogorsk',
    'ust kamenogorsk': 'ust-kamenogorsk',
    # Семей (до 2007 — Семипалатинск)
    'semipalatinsk': 'semey', 'семипалатинск': 'semey', 'семеи': 'semey',
    # Астана (Нур-Султан 2019–2022, ранее Целиноград/Акмола)
    'nur-sultan': 'astana', 'нур-султан': 'astana', 'нұр-сұлтан': 'astana',
    'целиноград': 'astana', 'акмола': 'astana',
    # Алматы (Алма-Ата до 1993)
    'alma-ata': 'almaty', 'алма-ата': 'almaty',
    # Шымкент (Чимкент до 1993)
    'chimkent': 'shymkent', 'чимкент': 'shymkent',
    # Караганда (каз. Қарағанды)
    'qaraghandy': 'karaganda', 'qaragandy': 'karaganda',
    'қарағанды': 'karaganda',
    # Костанай (каз. Қостанай)
    'qostanay': 'kostanai', 'қостанай': 'kostanai',
    # Кызылорда (каз. Қызылорда)
    'qyzylorda': 'kyzylorda', 'қызылорда': 'kyzylorda',
    # Туркестан (каз. Түркістан)
    'turkistan': 'turkestan', 'түркістан': 'turkestan',
    # Уральск (каз. Орал)
    'орал': 'uralsk',
    # Петропавловск (каз. Петропавл)
    'петропавл': 'petropavlovsk', 'petropavl': 'petropavlovsk',
    # Кокшетау (каз. Көкшетау)
    'көкшетау': 'kokshetau',
    # Талдыкорган (каз. Талдықорған)
    'талдықорған': 'taldykorgan',
    # Жанаозен (каз. Жаңаөзен)
    'жаңаөзен': 'zhanaozen',
    # Атырау (до 1991 — Гурьев)
    'гурьев': 'atyrau',
    # Тараз (до 1997 — Джамбул / Жамбыл)
    'джамбул': 'taraz', 'жамбыл': 'taraz',
}

_WS_RE = re.compile(r"\s+")
# Суффикс " - что-то" ("Костанай - Сегодня в" → "Костанай").
# Пробел перед дефисом ОБЯЗАТЕЛЕН (\s+): дефис внутри слова
# ('ust-kamenogorsk', 'алма-ата') резать НЕЛЬЗЯ. Не менять на \s*-\s*!
_SUFFIX_RE = re.compile(r"\s+-\s*.*$")
# slugify: всё, что не буква/цифра/дефис (юникод: кириллица остаётся)
_NON_WORD_RE = re.compile(r"[^\w-]+", re.UNICODE)
_MULTI_DASH_RE = re.compile(r"-{2,}")


def _slugify(s: str) -> str:
    """Безопасный slug: casefold, пробелы → '-', внутренние дефисы
    сохраняются, строка никогда не усекается. 'Some Town' → 'some-town',
    'ust-kamenogorsk' → 'ust-kamenogorsk' (без изменений)."""
    s = s.casefold()
    s = _WS_RE.sub("-", s)
    s = _NON_WORD_RE.sub("", s)
    s = _MULTI_DASH_RE.sub("-", s)
    return s.strip("-_")


def normalize_city(raw: Optional[str]) -> Optional[str]:
    """
    Нормализует city value для сохранения в БД:
      - None / "" / "0" → None
      - "Костанай - Сегодня в" → срез суффикса → "Костанай" → 'kostanai'
      - "Алматы" / "Aqtau" / "Ақтау" (алиас) → canonical slug
      - неизвестный город → безопасный slugify (casefold, пробелы→дефис),
        НИКОГДА не усекается по дефису
    """
    if raw is None:
        return None
    s = raw if isinstance(raw, str) else str(raw)
    s = _WS_RE.sub(" ", s).strip()
    if not s or s == "0":
        return None
    s = _SUFFIX_RE.sub("", s).strip()
    if not s:
        return None
    canonical = CITY_ALIASES.get(s.casefold())
    if canonical:
        return canonical
    return _slugify(s) or None
