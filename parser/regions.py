"""Region registry: Greece, 13 regions (NUTS2) and 74 regional units (ELSTAT codes).

Codes
-----
- country : "GR"
- region  : NUTS2 code, e.g. "GR11"
- unit    : parent NUTS2 code + ELSTAT regional-unit code, e.g. "GR11-03" (Evros)

The ELSTAT unit codes 01-74 come from the hidden "ListOfRegions"/"ListOfValues"
sheet shipped with the ELSTAT tables.

Names in the Excel files vary between tables and years (accents, trailing dots,
abbreviations, typos in the English column). Matching is done on a normalised
form of the Greek name first, then the English name. Any name that does not
match raises an error: add the new spelling to ALIASES, never edit the Excel.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    code: str
    level: str        # country / region / unit
    name_en: str      # canonical English name written to the CSV
    name_el: str      # canonical Greek name
    parent: str | None


# (NUTS2 code, English, Greek)
_REGIONS = [
    ("GR11", "Eastern Macedonia and Thrace", "Περιφέρεια Ανατολικής Μακεδονίας και Θράκης"),
    ("GR12", "Central Macedonia", "Περιφέρεια Κεντρικής Μακεδονίας"),
    ("GR13", "Western Macedonia", "Περιφέρεια Δυτικής Μακεδονίας"),
    ("GR21", "Epirus", "Περιφέρεια Ηπείρου"),
    ("GR14", "Thessaly", "Περιφέρεια Θεσσαλίας"),
    ("GR24", "Central Greece", "Περιφέρεια Στερεάς Ελλάδας"),
    ("GR22", "Ionian Islands", "Περιφέρεια Ιονίων Νήσων"),
    ("GR23", "Western Greece", "Περιφέρεια Δυτικής Ελλάδας"),
    ("GR25", "Peloponnese", "Περιφέρεια Πελοποννήσου"),
    ("GR30", "Attica", "Περιφέρεια Αττικής"),
    ("GR41", "Northern Aegean", "Περιφέρεια Βορείου Αιγαίου"),
    ("GR42", "Southern Aegean", "Περιφέρεια Νοτίου Αιγαίου"),
    ("GR43", "Crete", "Περιφέρεια Κρήτης"),
]

# (ELSTAT code, parent NUTS2, English, Greek) - order as in the ELSTAT tables
_UNITS = [
    ("01", "GR11", "Rodopi", "Ροδόπης"),
    ("02", "GR11", "Drama", "Δράμας"),
    ("03", "GR11", "Evros", "Έβρου"),
    ("04", "GR11", "Thasos", "Θάσου"),
    ("05", "GR11", "Kavala", "Καβάλας"),
    ("06", "GR11", "Xanthi", "Ξάνθης"),
    ("07", "GR12", "Thessaloniki", "Θεσσαλονίκης"),
    ("08", "GR12", "Imathia", "Ημαθίας"),
    ("09", "GR12", "Kilkis", "Κιλκίς"),
    ("10", "GR12", "Pella", "Πέλλας"),
    ("11", "GR12", "Pieria", "Πιερίας"),
    ("12", "GR12", "Serres", "Σερρών"),
    ("13", "GR12", "Chalkidiki", "Χαλκιδικής"),
    ("14", "GR13", "Kozani", "Κοζάνης"),
    ("15", "GR13", "Grevena", "Γρεβενών"),
    ("16", "GR13", "Kastoria", "Καστοριάς"),
    ("17", "GR13", "Florina", "Φλώρινας"),
    ("18", "GR21", "Ioannina", "Ιωαννίνων"),
    ("19", "GR21", "Arta", "Άρτας"),
    ("20", "GR21", "Thesprotia", "Θεσπρωτίας"),
    ("21", "GR21", "Preveza", "Πρέβεζας"),
    ("22", "GR14", "Larissa", "Λάρισας"),
    ("23", "GR14", "Karditsa", "Καρδίτσας"),
    ("24", "GR14", "Magnesia", "Μαγνησίας"),
    ("25", "GR14", "Sporades", "Σποράδων"),
    ("26", "GR14", "Trikala", "Τρικάλων"),
    ("27", "GR24", "Fthiotida", "Φθιώτιδας"),
    ("28", "GR24", "Viotia", "Βοιωτίας"),
    ("29", "GR24", "Evia", "Εύβοιας"),
    ("30", "GR24", "Evrytania", "Ευρυτανίας"),
    ("31", "GR24", "Fokida", "Φωκίδας"),
    ("32", "GR22", "Corfu", "Κέρκυρας"),
    ("33", "GR22", "Zakynthos", "Ζακύνθου"),
    ("34", "GR22", "Ithaca", "Ιθάκης"),
    ("35", "GR22", "Kefalonia", "Κεφαλληνίας"),
    ("36", "GR22", "Lefkada", "Λευκάδας"),
    ("37", "GR23", "Achaia", "Αχαΐας"),
    ("38", "GR23", "Aitoloakarnania", "Αιτωλοακαρνανίας"),
    ("39", "GR23", "Ilia", "Ηλείας"),
    ("40", "GR25", "Arkadia", "Αρκαδίας"),
    ("41", "GR25", "Argolida", "Αργολίδας"),
    ("42", "GR25", "Korinthia", "Κορινθίας"),
    ("43", "GR25", "Lakonia", "Λακωνίας"),
    ("44", "GR25", "Messinia", "Μεσσηνίας"),
    ("45", "GR30", "Central Athens", "Κεντρικού Τομέα Αθηνών"),
    ("46", "GR30", "North Athens", "Βορείου Τομέα Αθηνών"),
    ("47", "GR30", "West Athens", "Δυτικού Τομέα Αθηνών"),
    ("48", "GR30", "South Athens", "Νοτίου Τομέα Αθηνών"),
    ("49", "GR30", "East Attica", "Ανατολικής Αττικής"),
    ("50", "GR30", "West Attica", "Δυτικής Αττικής"),
    ("51", "GR30", "Piraeus", "Πειραιώς"),
    ("52", "GR30", "Islands (Attica)", "Νήσων"),
    ("53", "GR41", "Lesvos", "Λέσβου"),
    ("54", "GR41", "Ikaria", "Ικαρίας"),
    ("55", "GR41", "Lemnos", "Λήμνου"),
    ("56", "GR41", "Samos", "Σάμου"),
    ("57", "GR41", "Chios", "Χίου"),
    ("58", "GR42", "Syros", "Σύρου"),
    ("59", "GR42", "Andros", "Άνδρου"),
    ("60", "GR42", "Thira", "Θήρας"),
    ("61", "GR42", "Kalymnos", "Καλύμνου"),
    ("62", "GR42", "Karpathos", "Καρπάθου"),
    ("63", "GR42", "Kea-Kythnos", "Κέας - Κύθνου"),
    ("64", "GR42", "Kos", "Κω"),
    ("65", "GR42", "Milos", "Μήλου"),
    ("66", "GR42", "Mykonos", "Μυκόνου"),
    ("67", "GR42", "Naxos", "Νάξου"),
    ("68", "GR42", "Paros", "Πάρου"),
    ("69", "GR42", "Rhodes", "Ρόδου"),
    ("70", "GR42", "Tinos", "Τήνου"),
    ("71", "GR43", "Heraklion", "Ηρακλείου"),
    ("72", "GR43", "Lasithi", "Λασιθίου"),
    ("73", "GR43", "Rethymno", "Ρεθύμνης"),
    ("74", "GR43", "Chania", "Χανίων"),
]

# Extra spellings seen in the files (Greek or English) -> code.
# Add new variants here when the parser reports an unknown name.
ALIASES = {
    # country
    "Greece Total": "GR",
    # regions: English as printed by ELSTAT ("Region of ...", typos)
    "Region of Thessally": "GR14",
    # regions: Greeklish names in the livestock tables
    "Anatoliki Makedonia and Thraki": "GR11",
    "Kentriki Makedonia": "GR12",
    "Dytiki Makedonia": "GR13",
    "Ipeiros": "GR21",
    "Thessalia": "GR14",
    "Ionia Nisia": "GR22",
    "Dytiki Ellada": "GR23",
    "Sterea Ellada": "GR24",
    "Peloponnisos": "GR25",
    "Attiki": "GR30",
    "Voreio Aigaio": "GR41",
    "Notio Aigaio": "GR42",
    "Kriti": "GR43",
    # units: Greek variants
    "Αιτωλ/νανίας": "GR23-38",
    "Καρπάθου - Ηρωικής Νήσου Κάσου": "GR42-62",
    "Κύθνου": "GR42-63",
    "Ευβοίας": "GR24-29",
    # units: English variants printed in the tables
    "Ionnina": "GR21-18",
    "Pthiotida": "GR24-27",
    "Evritania": "GR24-30",
    "Ithaka": "GR22-34",
    "Etolia and Akarnania": "GR23-38",
    "Mesinia": "GR25-44",
    "Athens Central Section": "GR30-45",
    "Athens North Section": "GR30-46",
    "Athens West Section": "GR30-47",
    "Athens South Section": "GR30-48",
    "Pireaus": "GR30-51",
    "Attica Islands": "GR30-52",
    "Lesbos": "GR41-53",
    "Limnos": "GR41-55",
    "Kalimnos": "GR42-61",
    "Karpathos - Heroic Island of Kasos": "GR42-62",
    "Kythnos": "GR42-63",
    "Kea - Kythnos": "GR42-63",
    "Sporades Islands": "GR14-25",
}


def normalise(name: str) -> str:
    """Accent/case/punctuation-insensitive key for matching names."""
    s = unicodedata.normalize("NFD", str(name))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("ς", "σ")
    s = re.sub(r"^region of\s+", "", s)
    s = re.sub(r"[.·]", "", s)
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _build():
    by_code: dict[str, Region] = {}
    by_code["GR"] = Region("GR", "country", "Greece", "Σύνολο Ελλάδας", None)
    for code, en, el in _REGIONS:
        by_code[code] = Region(code, "region", en, el, "GR")
    for elstat, parent, en, el in _UNITS:
        code = f"{parent}-{elstat}"
        by_code[code] = Region(code, "unit", en, el, parent)

    lookup: dict[str, str] = {}

    def add(name: str, code: str):
        key = normalise(name)
        if key in lookup and lookup[key] != code:
            raise ValueError(f"Region name {name!r} is ambiguous: {lookup[key]} vs {code}")
        lookup[key] = code

    for r in by_code.values():
        add(r.name_en, r.code)
        add(r.name_el, r.code)
    for name, code in ALIASES.items():
        if code not in by_code:
            raise ValueError(f"Alias {name!r} points to unknown code {code}")
        add(name, code)
    return by_code, lookup


REGIONS, _LOOKUP = _build()


def resolve(name_el: str | None, name_en: str | None) -> Region | None:
    """Return the region for a data row, matching Greek name first, then English."""
    for name in (name_el, name_en):
        if name:
            code = _LOOKUP.get(normalise(name))
            if code:
                return REGIONS[code]
    return None


def children(code: str) -> list[Region]:
    return [r for r in REGIONS.values() if r.parent == code]
