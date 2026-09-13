"""Colours carried inside product codes: ``01/1009 C1``, ``ARM-001-NEG``.

Supplier sheets rarely have a colour column. The colour is the tail of the
code, written however that supplier writes it: a word in one of several
languages, cut short by an old system's length limit (``BLAC``), two words
(``MATTE BLACK``), or the supplier's own number (``C1``), which means a
different colour on every model. Nothing here assumes one of those shapes.

* ``analyze_codes`` finds the rule. It tries every separator the codes use and
  scores how much the tails behave like colours: known colour words, or the
  same tail under several models. A model number (``ARM-001``, ``ARM-002``)
  never recurs across models, so it scores nothing.
* ``suggest`` proposes what each distinct tail means, from what the shop
  answered before, then its own colour list, then a synonym table. It only
  proposes: ``plan`` refuses a batch while any tail is unanswered.
* ``plan`` turns the answers into the two columns the importer already reads,
  "Producto base" and "Colores", and adds the base rows no supplier sheet has.
  From there it is the ordinary products import, so every business rule still
  runs (CLAUDE.md rule 9), including the family checks in engine.py.
* ``remember`` keeps the rule and the answers, so a shop's dialect is learned
  once rather than guessed at every import.

A model offered in a single colour stays a plain article with that colour.
Its family forms when a second colour turns up, in this file or a later one;
the article already in the catalogue then moves under the new base and keeps
its own stock. A lone bicolour tail (``BLACK BLUE``) is one article too: it is
flagged ``multicolor``, so its two colours are never split into a family.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import CompanySettings
from app.models.enums import ColorAliasKind
from app.models.imports import ColorAlias
from app.models.product import Color, Product

DEFAULT_WORDS = 2
# Share of rows whose tail behaves like a colour before the step offers itself.
LIKELY_SCORE = 0.3
EXAMPLES = 3
PHRASE_LENGTH = ColorAlias.__table__.c.phrase.type.length

# What a synthesised base copies from its first colour: the importer's
# spelling of services.products.INHERITED.
INHERITED = (
    "description", "product_type", "brand", "model", "supplier", "current_cost",
    "min_stock", "pricing_mode", "sale_price", "price_list", "price_category",
)

# Canonical name -> spellings. The names match the starter palette
# (services.provisioning.STARTER_COLORS), so a new shop is offered its own
# colours; a shop that renamed them is matched by meaning instead (Vocabulary).
# Spellings cover Spanish, English, Italian, Portuguese and French plus the
# abbreviations suppliers use. Cut-off words need no entry: see lookup().
_COLOURS: dict[str, str] = {
    "Negro": "NEGRO NEGRA NEG NGR BLACK BLK BLCK BK NERO NERA PRETO PRETA NOIR NOIRE",
    "Blanco": "BLANCO BLANCA WHITE WHT BIANCO BIANCA BRANCO BRANCA BLANC BLANCHE",
    "Gris": "GRIS GREY GRAY GRY GRIGIO GRIGIA CINZA SMOKE HUMO GUN GUNMETAL "
            "ANTRACITA ANTHRACITE",
    "Marrón": "MARRON BROWN BRWN BRN MARRONE MARROM CASTANHO CAFE CAFFE COFFEE "
              "CHOCOLATE CHOCO TABACO TOBACCO",
    "Havana": "HAVANA HABANO HABANA HAV HVN AVANA HAVANE",
    "Carey": "CAREY TORTOISE TORTUGA TORT DEMI TARTARUGA",
    "Dorado": "DORADO DORADA GOLD GLD ORO DORATO DORATA OURO DOURADO",
    "Plateado": "PLATEADO PLATEADA PLATA SILVER SILV SLV ARGENTO ARGENTATO PRATA "
                "PRATEADO ARGENT",
    "Azul": "AZUL BLUE BLU BLEU BLAU NAVY MARINO",
    "Celeste": "CELESTE AZZURRO AZZURRA SKY CIELO",
    "Verde": "VERDE GREEN GRN VERT OLIVA OLIVE MUSGO MILITAR",
    "Rojo": "ROJO ROJA RED ROSSO ROSSA VERMELHO ROUGE",
    "Bordó": "BORDO BORRAVINO BURGUNDY BORGOGNA WINE VINO GRANATE MARSALA",
    "Rosa": "ROSA PINK ROSADO ROSADA ROSE",
    "Violeta": "VIOLETA VIOLET VIOLA PURPURA PURPLE MORADO LILA LILAC LAVANDA LAVENDER",
    "Transparente": "TRANSPARENTE TRASPARENTE CRISTAL CRYSTAL CLEAR",
    "Amarillo": "AMARILLO AMARILLA YELLOW GIALLO GIALLA AMARELO JAUNE",
    "Naranja": "NARANJA ORANGE ARANCIO ARANCIONE LARANJA",
    "Beige": "BEIGE NUDE CREMA CREAM ARENA SAND",
    # Shades a shop names on the label rather than folding into a family.
    "Fucsia": "FUCSIA FUCHSIA MAGENTA",
    "Coral": "CORAL CORALLO",
    "Salmón": "SALMON SALMONE SALOMONE",
    "Miel": "MIEL MIELE HONEY",
    "Champagne": "CHAMPAGNE CHAMPAN CHAMP",
    "Petróleo": "PETROLEO PETROL PETROLIO",
    "Turquesa": "TURQUESA TURQUOISE TURCHESE AQUA ACQUA TEAL",
    "Ocre": "OCRE OCRA OCHRE",
    "Caramelo": "CARAMELO CARAMEL CARAMELLO",
    "Cobre": "COBRE COPPER RAME",
    "Bronce": "BRONCE BRONZE BRONZO",
    "Ébano": "EBANO EBONY",
    "Jade": "JADE GIADA",
    "Menta": "MENTA MINT",
    "Esmeralda": "ESMERALDA EMERALD SMERALDO SMERALD",
    "Peltre": "PELTRE PEWTER PELTRO",
    "Visón": "VISON MINK",
    "Amatista": "AMATISTA AMETHYST AMETISTA",
    "Tierra": "TIERRA TERRA EARTH",
}
_COLOURS["Gris"] += " CENERE ASH"
_COLOURS["Marrón"] += " SEPIA"
_COLOURS["Bordó"] += " BORAVINO CHERRY GRANADA"
# A finish qualifies a colour rather than being one: "NERO MATE" is Negro mate.
_FINISHES: dict[str, str] = {
    "mate": "MATE MATTE MAT MATT MATTO OPACO",
    "brillante": "BRILLO BRILLANTE GLOSS GLOSSY SHINY LUCIDO",
    "metalizado": "METAL METALIZADO METALLIC",
}
# Supplier shorthands that pack a finish and a colour into one word.
_COMPOUNDS: dict[str, str] = {
    "MBLK": "MATE NEGRO", "MBK": "MATE NEGRO", "SBLK": "BRILLO NEGRO",
    "MGRY": "MATE GRIS", "MBRN": "MATE MARRON",
}
# Letters then a short number: the supplier's own colour numbering (C1, P04).
_NUMBERED = re.compile(r"^([A-Z]{1,2})(\d{1,3})$")


def norm(text) -> str:
    """Upper-case, accents folded, spaces collapsed: how a tail is keyed."""
    folded = unicodedata.normalize("NFKD", str(text or ""))
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    return " ".join(ascii_only.upper().split())


def _words(text) -> list[str]:
    """``GRIS/ROJO`` and ``L.BLUE`` are several words glued by punctuation."""
    return [w for w in re.split(r"[^A-Z0-9]+", norm(text)) if w]


# --- vocabulary ------------------------------------------------------------

@dataclass(frozen=True)
class Meaning:
    hues: tuple[str, ...]                     # colour names, in written order
    finishes: frozenset[str] = frozenset()


def _compose(meaning: Meaning) -> str:
    finishes = [f for f in _FINISHES if f in meaning.finishes]
    return " ".join([*meaning.hues, *finishes])


class Vocabulary:
    """Spellings and what they mean: the built-in table plus the shop's colours.

    The shop's list is folded in two ways. A colour it named in a word we do not
    know ("Jade") becomes a word, so ``JADE MATE`` reads as Jade mate. And each
    of its colours is indexed by meaning, so a shop that calls black "Black" is
    offered "Black" for ``NERO``, never a second black named "Negro".
    """

    def __init__(self, colors) -> None:
        self._spellings: dict[str, tuple[str, str]] = {}
        for name, spellings in _COLOURS.items():
            for s in spellings.split():
                self._spellings[s] = ("colour", name)
        for name, spellings in _FINISHES.items():
            for s in spellings.split():
                self._spellings[s] = ("finish", name)
        self._cache: dict[str, tuple[tuple[str, str], ...] | None] = {}

        colors = list(colors)
        for c in colors:
            words = _words(c.name)
            if len(words) == 1 and self.lookup(words[0]) is None:
                self._learn(words[0], ("colour", c.name))

        self.catalog: dict[str, str] = {}         # norm(name or code) -> name
        self.by_meaning: dict[Meaning, str] = {}
        for c in colors:
            for key in (c.name, c.code):
                if key and norm(key) not in self.catalog:
                    self.catalog[norm(key)] = c.name
            meaning = self.meaning(c.name)
            if meaning is None:
                continue
            if norm(c.name) == norm(_compose(meaning)):
                self.by_meaning[meaning] = c.name    # the canonical spelling wins
            else:
                self.by_meaning.setdefault(meaning, c.name)
            code = _words(c.code or "")
            if (len(code) == 1 and len(meaning.hues) == 1 and not meaning.finishes
                    and self.lookup(code[0]) is None):
                self._learn(code[0], ("colour", meaning.hues[0]))

    def _learn(self, word: str, hit: tuple[str, str]) -> None:
        self._spellings[word] = hit
        self._cache.clear()

    def _exact(self, word: str) -> tuple[tuple[str, str], ...] | None:
        if word in self._spellings:
            return (self._spellings[word],)
        if word in _COMPOUNDS:
            return tuple(self._spellings[w] for w in _COMPOUNDS[word].split())
        return None

    def lookup(self, word: str) -> tuple[tuple[str, str], ...] | None:
        """What one written word means: ``(("colour", "Negro"),)`` or None.

        Two tolerances, both for what old systems do to codes. A word that is
        the start of exactly one meaning counts, so ``BLAC`` is black; ``GRE``
        could be grey or green, and an ambiguous guess is worse than asking, so
        it stays unknown. And two exact spellings with the space lost count as
        both (``NEROMATE``, ``GREYBLK``).
        """
        if word in self._cache:
            return self._cache[word]
        hits = self._exact(word)
        if hits is None and len(word) >= 3 and not word.isdigit():
            found = {v for k, v in self._spellings.items() if k.startswith(word)}
            hits = (found.pop(),) if len(found) == 1 else None
        if hits is None and len(word) >= 6:
            for i in range(3, len(word) - 2):
                left, right = self._exact(word[:i]), self._exact(word[i:])
                if left and right:
                    hits = left + right
                    break
        self._cache[word] = hits
        return hits

    def knows(self, part: str) -> bool:
        words = _words(part)
        return bool(words) and all(self.lookup(w) is not None for w in words)

    def meaning(self, text: str) -> Meaning | None:
        """What a tail means when every word of it is known, else None."""
        words = _words(text)
        if not words:
            return None
        hues: list[str] = []
        finishes: set[str] = set()
        for w in words:
            hits = self.lookup(w)
            if hits is None:
                return None
            for kind, name in hits:
                if kind == "finish":
                    finishes.add(name)
                elif name not in hues:
                    hues.append(name)
        return Meaning(tuple(hues), frozenset(finishes)) if hues else None

    def partial_meaning(self, text: str) -> Meaning | None:
        """The colour in a tail with some noise on it (``BLACK G15``, ``BROWN PH``).

        Only a hint: lens codes and cut-off letters are not safe to discard
        silently, so this never counts as an answer (see suggest).
        """
        words = _words(text)
        known = [w for w in words if self.lookup(w) is not None]
        if not known or len(known) < len(words) - len(known):
            return None
        return self.meaning(" ".join(known))

    def names_for(self, meaning: Meaning) -> list[str]:
        """Colour names for a meaning: one per hue, the finish on the first."""
        whole = self.by_meaning.get(meaning)
        if whole:
            return [whole]
        out: list[str] = []
        for i, hue in enumerate(meaning.hues):
            one = Meaning((hue,), meaning.finishes if i == 0 else frozenset())
            name = self.by_meaning.get(one) or _compose(one)
            if norm(name) not in {norm(n) for n in out}:
                out.append(name)
        return out


# --- reading a code --------------------------------------------------------

@dataclass(frozen=True)
class CodeRule:
    separator: str
    max_words: int = DEFAULT_WORDS


def split_code(code: str, rule: CodeRule, vocab: Vocabulary) -> tuple[str, str] | None:
    """``(stem, tail)`` for a code, or None when the rule finds no tail.

    The last part always starts the tail; earlier parts join it only while
    they are colour words, so ``03/AGREV MATTE BLACK`` keeps ``MATTE BLACK``
    together while ``03/C09 M AZUL`` leaves the ``M`` with the model. The stem
    always keeps at least one part.
    """
    sep = rule.separator
    if sep.isspace():
        parts, joiner = str(code).split(), " "
    else:
        parts, joiner = [p.strip() for p in str(code).split(sep)], sep
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return None
    take = 1
    while (take < rule.max_words and len(parts) - take > 1
           and vocab.knows(parts[-take - 1])):
        take += 1
    return joiner.join(parts[:-take]), " ".join(parts[-take:])


@dataclass
class Tail:
    phrase: str
    rows: int = 0
    stems: set[str] = field(default_factory=set)
    examples: list[str] = field(default_factory=list)


def _tails(codes, rule: CodeRule, vocab: Vocabulary) -> tuple[dict[str, Tail], int]:
    tails: dict[str, Tail] = {}
    without = 0
    for code in codes:
        split = split_code(code, rule, vocab)
        if split is None:
            without += 1
            continue
        stem, tail = split
        key = norm(tail)[:PHRASE_LENGTH]
        t = tails.setdefault(key, Tail(key))
        t.rows += 1
        t.stems.add(stem.casefold())
        if len(t.examples) < EXAMPLES:
            t.examples.append(code)
    return tails, without


# --- answers ---------------------------------------------------------------

@dataclass
class Decision:
    kind: ColorAliasKind
    colors: list[str] = field(default_factory=list)


@dataclass
class Choices:
    """The shop's confirmation of the "Colores" step."""

    rule: CodeRule
    decisions: dict[str, Decision] = field(default_factory=dict)


@dataclass
class Suggestion:
    kind: ColorAliasKind | None
    colors: list[str]
    source: str | None          # saved | catalog | synonyms | pattern


def _colors(db: Session, company_id: int) -> list[Color]:
    return list(db.execute(
        select(Color)
        .where(Color.company_id == company_id, Color.is_active.is_(True))
        .order_by(Color.name)
    ).scalars())


def saved_decisions(db: Session, company_id: int) -> dict[str, Decision]:
    out: dict[str, Decision] = {}
    for alias in db.execute(
        select(ColorAlias).where(ColorAlias.company_id == company_id)
    ).scalars():
        names = [c.name for c in alias.colors if c.is_active]
        if alias.kind == ColorAliasKind.COLOR and (
            not names or len(names) != len(alias.colors)
        ):
            continue    # a colour it pointed at was retired: ask again, don't guess
        out[alias.phrase] = Decision(alias.kind, names)
    return out


def _stored_rule(db: Session, company_id: int) -> CodeRule | None:
    settings = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    if settings is None or not settings.code_color_separator:
        return None
    return CodeRule(settings.code_color_separator,
                    settings.code_color_max_words or DEFAULT_WORDS)


def suggest(
    tails: dict[str, Tail], vocab: Vocabulary, saved: dict[str, Decision]
) -> dict[str, Suggestion]:
    """A proposal per tail, most trusted source first.

    A letters-and-number tail is only called a supplier number when its letters
    already behave like one: recurring under several models here, or answered
    that way before. That is what tells ``C14`` (one more of the C1, C2...)
    from ``T3`` on a lone row, which could be anything. A numbering is read as
    one series, ahead of the colour list: a shop that once made a colour named
    "C1" by hand must not get C1 as a colour and C3 as a number.

    A ``partial`` source proposes colours but no kind, so the tail still counts
    as unanswered until the shop picks.
    """
    numbering = {
        m.group(1) for key, t in tails.items()
        if len(t.stems) > 1 and (m := _NUMBERED.match(key))
    } | {
        m.group(1) for key, d in saved.items()
        if d.kind == ColorAliasKind.SUPPLIER_NUMBER and (m := _NUMBERED.match(key))
    }
    out: dict[str, Suggestion] = {}
    for key in tails:
        numbered = _NUMBERED.match(key)
        if key in saved:
            out[key] = Suggestion(saved[key].kind, saved[key].colors, "saved")
        elif numbered and numbered.group(1) in numbering:
            out[key] = Suggestion(ColorAliasKind.SUPPLIER_NUMBER, [], "pattern")
        elif key in vocab.catalog:
            out[key] = Suggestion(ColorAliasKind.COLOR, [vocab.catalog[key]], "catalog")
        elif (meaning := vocab.meaning(key)) is not None:
            out[key] = Suggestion(ColorAliasKind.COLOR, vocab.names_for(meaning),
                                  "synonyms")
        elif (partial := vocab.partial_meaning(key)) is not None:
            out[key] = Suggestion(None, vocab.names_for(partial), "partial")
        else:
            out[key] = Suggestion(None, [], None)
    return out


# --- detection -------------------------------------------------------------

def candidate_separators(codes) -> list[str]:
    """Every non-alphanumeric character a fair share of the codes contain."""
    counts: Counter[str] = Counter()
    for code in codes:
        counts.update({" " if ch.isspace() else ch
                       for ch in str(code).strip() if not ch.isalnum()})
    # Two rows, or 5% of a long file; a one-row file still gets a proposal.
    floor = max(min(2, len(codes)), len(codes) // 20)
    return [ch for ch, n in counts.most_common() if n >= floor]


def score_rule(codes, rule: CodeRule, vocab: Vocabulary,
               saved: dict[str, Decision] | None = None) -> float:
    """Share of rows whose tail behaves like a colour under this rule."""
    if not codes:
        return 0.0
    saved = saved or {}
    tails, _ = _tails(codes, rule, vocab)
    hits = sum(
        t.rows for key, t in tails.items()
        if len(t.stems) > 1
        or key in vocab.catalog
        or vocab.meaning(key) is not None
        or (key in saved and saved[key].kind != ColorAliasKind.NOT_COLOR)
    )
    return round(hits / len(codes), 3)


def analyze_codes(
    db: Session,
    codes: list[str],
    *,
    company_id: int,
    separator: str | None = None,
    max_words: int | None = None,
) -> dict:
    """Everything the "Colores" step shows. Writes nothing.

    With no separator given, the shop's remembered rule is used when it still
    fits this file, otherwise the best-scoring one. The shop can override
    either; the scores are returned so the screen can say why.
    """
    colors = _colors(db, company_id)
    vocab = Vocabulary(colors)
    saved = saved_decisions(db, company_id)
    words = max_words or DEFAULT_WORDS
    candidates = sorted(
        ({"separator": sep, "score": score_rule(codes, CodeRule(sep, words), vocab, saved)}
         for sep in candidate_separators(codes)),
        key=lambda c: -c["score"],
    )

    rule: CodeRule | None = None
    remembered = False
    stored = _stored_rule(db, company_id)
    if separator:
        rule = CodeRule(separator, words)
    elif stored is not None:
        fitted = CodeRule(stored.separator, max_words or stored.max_words)
        if score_rule(codes, fitted, vocab, saved) >= LIKELY_SCORE:
            rule, remembered = fitted, True
    if rule is None and candidates:
        rule = CodeRule(candidates[0]["separator"], words)

    base = {
        "colors": [{"name": c.name, "hex_code": c.hex_code} for c in colors],
        "candidates": candidates, "remembered": remembered,
    }
    if rule is None:
        return {**base, "separator": None, "max_words": words, "score": 0.0,
                "likely": False, "examples": [], "tails": [],
                "rows_with_tail": 0, "rows_without_tail": len(codes)}

    tails, without = _tails(codes, rule, vocab)
    suggestions = suggest(tails, vocab, saved)
    score = score_rule(codes, rule, vocab, saved)
    examples = []
    for code in codes:
        if (split := split_code(code, rule, vocab)) is not None:
            examples.append({"code": code, "stem": split[0], "tail": split[1]})
            if len(examples) == EXAMPLES:
                break
    return {
        **base,
        "separator": rule.separator,
        "max_words": rule.max_words,
        "score": score,
        "likely": score >= LIKELY_SCORE,
        "examples": examples,
        "tails": [
            {
                "phrase": key, "rows": t.rows, "models": len(t.stems),
                "examples": t.examples,
                "kind": s.kind.value if s.kind else None,
                "colors": s.colors, "source": s.source,
            }
            for key, t in sorted(tails.items(), key=lambda kv: (-kv[1].rows, kv[0]))
            for s in [suggestions[key]]
        ],
        "rows_with_tail": len(codes) - without,
        "rows_without_tail": without,
    }


# --- applying the answers --------------------------------------------------

def plan(
    db: Session,
    parsed: list[tuple[int, dict]],
    choices: Choices,
    *,
    company_id: int,
) -> tuple[list[tuple[int, dict]], list[tuple[int, str, str]], list[dict]]:
    """Fill "Producto base" and "Colores" from the codes. Writes nothing.

    Returns the rows (plus the bases and catalogue articles the families need),
    errors as ``(row, field, message)``, and the families for the preview.
    Whatever the file states itself wins: a row with its own "Producto base"
    is left alone, and a filled "Colores" cell is kept.
    """
    vocab = Vocabulary(_colors(db, company_id))
    decisions = saved_decisions(db, company_id)
    decisions.update({norm(k): d for k, d in choices.decisions.items()})
    rule = choices.rule

    errors: list[tuple[int, str, str]] = []
    undecided: dict[str, list[int]] = defaultdict(list)
    colourless: dict[str, list[int]] = defaultdict(list)
    groups: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    stems: dict[str, str] = {}
    for row_no, v in parsed:
        if v.get("parent"):
            continue
        split = split_code(v["code"], rule, vocab)
        if split is None:
            continue                                  # no tail: a plain article
        stem, tail = split
        key = norm(tail)[:PHRASE_LENGTH]
        decision = decisions.get(key)
        if decision is None:
            undecided[key].append(row_no)
            continue
        if decision.kind == ColorAliasKind.NOT_COLOR:
            continue
        if decision.kind == ColorAliasKind.COLOR:
            if not decision.colors:
                colourless[key].append(row_no)
                continue
            v.setdefault("color", list(decision.colors))
        groups[stem.casefold()].append((row_no, v))
        stems.setdefault(stem.casefold(), stem)
    for key, rows in undecided.items():
        errors.append((rows[0], "code",
                       f'Falta decidir qué es "{key}" al final del código '
                       f"({len(rows)} fila(s))."))
    for key, rows in colourless.items():
        errors.append((rows[0], "code", f'Elegí al menos un color para "{key}".'))
    if not groups:
        return parsed, errors, []

    in_file = {v["code"].casefold() for _, v in parsed}
    products = db.execute(
        select(Product).where(Product.company_id == company_id)
    ).scalars().all()
    by_code = {p.code.casefold(): p for p in products}
    children: dict[int, list[Product]] = defaultdict(list)
    for p in products:
        if p.parent_id is not None and p.is_active:
            children[p.parent_id].append(p)
    # Plain articles already in the catalogue that the same rule puts under one
    # of this file's models: the colour that came first, waiting for a second.
    loose: dict[str, list[tuple[Product, Decision]]] = defaultdict(list)
    for p in products:
        if (not p.is_active or p.parent_id is not None or children.get(p.id)
                or p.code.casefold() in in_file):
            continue
        split = split_code(p.code, rule, vocab)
        if split is None or split[0].casefold() not in groups:
            continue
        decision = decisions.get(norm(split[1])[:PHRASE_LENGTH])
        if decision is not None and decision.kind != ColorAliasKind.NOT_COLOR:
            loose[split[0].casefold()].append((p, decision))

    added: list[tuple[int, dict]] = []
    families: list[dict] = []
    for key, members in groups.items():
        base_row = next((v for _, v in parsed if v["code"].casefold() == key), None)
        base_db = by_code.get(key)
        existing = children.get(base_db.id, []) if base_db is not None else []
        moving = loose.get(key, [])
        size = len({v["code"].casefold() for _, v in members}
                   | {p.code.casefold() for p in existing}
                   | {p.code.casefold() for p, _ in moving})
        if size < 2:
            # One colourway of a model: a plain article. Two colours in that one
            # tail describe the article, not a range, unless the file says no.
            for _, v in members:
                if len(v.get("color") or []) > 1:
                    v.setdefault("multicolor", True)
            continue

        base_code = (base_row["code"] if base_row is not None
                     else base_db.code if base_db is not None else stems[key])
        first_row = members[0][0]
        variants: list[dict] = []
        for _, v in members:
            v["parent"] = base_code
            variants.append({"code": v["code"], "colors": list(v.get("color") or []),
                             "status": "file"})
        for p, decision in moving:
            row = {"code": p.code, "parent": base_code}
            names = [c.name for c in p.colors]
            if not names and decision.kind == ColorAliasKind.COLOR:
                row["color"] = names = list(decision.colors)
            added.append((first_row, row))
            variants.append({"code": p.code, "colors": names, "status": "moved"})
        listed = {x["code"].casefold() for x in variants}
        for p in existing:
            if p.code.casefold() not in listed:
                variants.append({"code": p.code, "colors": [c.name for c in p.colors],
                                 "status": "existing"})

        new = base_row is None and base_db is None
        if new:
            template = members[0][1]
            base = {f: template[f] for f in INHERITED if f in template}
            base["code"] = base_code
            hues: list[str] = []
            for x in variants:
                for name in x["colors"]:
                    if norm(name) not in {norm(h) for h in hues}:
                        hues.append(name)
            if hues:
                base["color"] = hues
            added.append((first_row, base))
        families.append({"base": base_code, "new": new,
                         "variants": sorted(variants, key=lambda x: x["code"])})

    families.sort(key=lambda f: f["base"].casefold())
    return parsed + added, errors, families


def remember(db: Session, choices: Choices, *, company_id: int) -> None:
    """Keep the rule and every answer, inside the batch's own transaction."""
    settings = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one_or_none()
    if settings is None:
        settings = CompanySettings(company_id=company_id)
        db.add(settings)
    settings.code_color_separator = choices.rule.separator
    settings.code_color_max_words = choices.rule.max_words

    colours = {norm(c.name): c for c in _colors(db, company_id)}
    aliases = {
        a.phrase: a for a in db.execute(
            select(ColorAlias).where(ColorAlias.company_id == company_id)
        ).scalars()
    }
    for phrase, decision in choices.decisions.items():
        key = norm(phrase)[:PHRASE_LENGTH]
        names = list(dict.fromkeys(norm(n) for n in decision.colors if norm(n)))
        linked = [colours[n] for n in names if n in colours]
        if decision.kind == ColorAliasKind.COLOR and (not linked or len(linked) != len(names)):
            continue        # a colour the batch never used: nothing true to keep
        if not key:
            continue
        alias = aliases.get(key)
        if alias is None:
            alias = aliases[key] = ColorAlias(company_id=company_id, phrase=key,
                                              kind=decision.kind)
            db.add(alias)
        alias.kind = decision.kind
        alias.colors = linked if decision.kind == ColorAliasKind.COLOR else []
