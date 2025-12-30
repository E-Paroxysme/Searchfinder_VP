#!/usr/bin/env python3
"""
PF2e Data Extractor v6 - HTM-Based
==================================
Utilise les fichiers .htm de pf2-fr/data/ comme source de traduction.
Ces fichiers utilisent l'UUID comme nom de fichier = liaison parfaite !

Structure des sources:
- pf2-fr/data/{pack}/{UUID}.htm  → Traductions FR (nom, desc, items)
- pf2e/packs/{pack}/*.db         → Données mécaniques (stats, system)

Usage:
    python pf2_extract_v6.py              # Télécharge et indexe
    python pf2_extract_v6.py --clean      # Repart de zéro
    python pf2_extract_v6.py --local      # Sans télécharger
"""

import json
import shutil
import subprocess
import sys
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field

DATA_DIR = Path("pf2_data")
RAW_DIR = DATA_DIR / "raw"
DB_FILE = DATA_DIR / "pf2e_v5.db"  # Même nom pour compatibilité avec search

REPOS = [
    ("pf2e", "https://github.com/foundryvtt/pf2e.git"),
    ("pf2-fr", "https://gitlab.com/pathfinder-fr/foundryvtt-pathfinder2-fr.git"),
]

# ============================================================================
# COULEURS
# ============================================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"

if not sys.stdout.isatty():
    for attr in ['RESET', 'BOLD', 'DIM', 'RED', 'GREEN', 'YELLOW', 'CYAN']:
        setattr(C, attr, '')

def log(msg: str, level: str = "info"):
    colors = {"info": C.CYAN, "ok": C.GREEN, "warn": C.YELLOW, "err": C.RED, "dim": C.DIM}
    icons = {"info": "→", "ok": "✓", "warn": "⚠", "err": "✗", "dim": " "}
    print(f"{colors.get(level, '')}{icons.get(level, '')} {msg}{C.RESET}")

def run_cmd(cmd: list, cwd: Path = None, timeout: int = 900) -> Tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)

# ============================================================================
# MAPPING DES TYPES
# ============================================================================

TYPE_MAP = {
    "npc": "créature", "creature": "créature", "character": "créature",
    "hazard": "danger", "spell": "sort", "feat": "don", "action": "action",
    "equipment": "équipement", "treasure": "trésor", "backpack": "conteneur",
    "weapon": "arme", "armor": "armure", "shield": "bouclier",
    "consumable": "consommable", "ancestry": "ascendance", "heritage": "héritage",
    "background": "historique", "class": "classe", "archetype": "archétype",
    "deity": "divinité", "effect": "effet", "condition": "état",
    "familiar": "familier", "vehicle": "véhicule",
}

PACK_TYPE_MAP = {
    "pathfinder-bestiary": "créature", "bestiary": "créature", 
    "pathfinder-monster-core": "créature", "monster-core": "créature",
    "npc": "créature", "hazards": "danger", "spells": "sort", 
    "feats": "don", "actions": "action", "equipment": "équipement", 
    "weapons": "arme", "armor": "armure", "consumables": "consommable", 
    "ancestries": "ascendance", "heritages": "héritage",
    "backgrounds": "historique", "classes": "classe", "archetypes": "archétype",
    "deities": "divinité", "conditions": "état", "familiar": "familier",
    "vehicles": "véhicule", "animal-companions": "compagnon", "eidolons": "eidolon",
}

def detect_type_from_entry(entry: dict) -> str:
    t = entry.get("type", "")
    if t in TYPE_MAP:
        return TYPE_MAP[t]
    system = entry.get("system", {})
    if "attributes" in system and "hp" in system.get("attributes", {}):
        return "créature"
    if "traditions" in system:
        return "sort"
    if "prerequisites" in system:
        return "don"
    if "price" in system:
        return "équipement"
    return "autre"

def detect_type_from_pack(pack_name: str) -> str:
    pack_lower = pack_name.lower().replace(".json", "").replace("-srd", "")
    for key, val in PACK_TYPE_MAP.items():
        if key in pack_lower:
            return val
    return "autre"

# ============================================================================
# TÉLÉCHARGEMENT
# ============================================================================

def download_repos() -> Dict[str, bool]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ok, _ = run_cmd(["git", "--version"])
    if not ok:
        log("Git non installé!", "err")
        return {}
    
    results = {}
    for name, url in REPOS:
        target = RAW_DIR / name
        if target.exists():
            log(f"Mise à jour {name}...", "dim")
            ok, _ = run_cmd(["git", "-C", str(target), "pull", "--ff-only"])
            if ok:
                results[name] = True
                log(f"  {name}: à jour", "ok")
                continue
            shutil.rmtree(target)
        
        log(f"Clonage {name}...", "info")
        ok, out = run_cmd(["git", "clone", "--depth", "1", url, str(target)])
        if not ok:
            ok, out = run_cmd(["git", "clone", url, str(target)])
        results[name] = ok
        log(f"  {name}: {'OK' if ok else 'ÉCHEC'}", "ok" if ok else "err")
    return results

# ============================================================================
# PARSING DES FICHIERS .HTM (TRADUCTIONS)
# ============================================================================

@dataclass
class ItemTranslation:
    id: str
    name_en: str
    name_fr: str
    desc_en: str = ""
    desc_fr: str = ""

@dataclass 
class Translation:
    uuid: str
    pack: str
    name_en: str
    name_fr: str
    desc_en: str = ""
    desc_fr: str = ""
    status: str = ""
    items: Dict[str, ItemTranslation] = field(default_factory=dict)


def parse_htm_file(filepath: Path, pack_name: str) -> Optional[Translation]:
    """Parse un fichier .htm de traduction."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except:
        return None
    
    # Extraire l'UUID depuis le nom de fichier
    # Formats possibles:
    # - {UUID}.htm (ex: BN5Lb6IsQ9Wyu3rL.htm)
    # - {rarity}-{level}-{UUID}.htm (ex: common-03-sxQZ6yqTn0czJxVd.htm)
    # - {type}-{level}-{UUID}.htm (ex: equipment-00-oJZe5rRitvioUgRh.htm)
    # - {prefix}-{UUID}.htm (ex: backpack-12-iAfqKpHyJ6beLGjB.htm)
    stem = filepath.stem
    parts = stem.split("-")
    
    # Un UUID Foundry est généralement 16 caractères alphanumériques
    def looks_like_uuid(s: str) -> bool:
        return len(s) == 16 and s.isalnum()
    
    if len(parts) >= 2 and looks_like_uuid(parts[-1]):
        # Le dernier segment ressemble à un UUID
        uuid = parts[-1]
    elif len(parts) == 1 and looks_like_uuid(parts[0]):
        # Juste un UUID
        uuid = parts[0]
    else:
        # Fallback: prendre tout le nom (cas rares)
        uuid = stem
    
    # Parser les champs principaux
    name_en = ""
    name_fr = ""
    desc_en = ""
    desc_fr = ""
    status = ""
    
    # Name: / Nom:
    match = re.search(r'^Name:\s*(.+)$', content, re.MULTILINE)
    if match:
        name_en = match.group(1).strip()
    
    match = re.search(r'^Nom:\s*(.+)$', content, re.MULTILINE)
    if match:
        name_fr = match.group(1).strip()
    
    match = re.search(r'^État:\s*(.+)$', content, re.MULTILINE)
    if match:
        status = match.group(1).strip()
    
    # Descriptions
    # -- Desc (en) -- ... -- Desc (fr) -- ou -- End desc ---
    desc_en_match = re.search(r'-- Desc \(en\) --\s*(.+?)(?=-- Desc \(fr\) --|-- End desc ---|$)', content, re.DOTALL)
    if desc_en_match:
        desc_en = desc_en_match.group(1).strip()
    
    desc_fr_match = re.search(r'-- Desc \(fr\) --\s*(.+?)(?=-- End desc ---|$)', content, re.DOTALL)
    if desc_fr_match:
        desc_fr = desc_fr_match.group(1).strip()
    
    # Parser les items
    items = {}
    items_section = re.search(r'----- Items -+\s*(.+?)(?=-{10,}|$)', content, re.DOTALL)
    if items_section:
        items_content = items_section.group(1)
        
        # Chercher chaque bloc ID: / Name: / Nom:
        item_blocks = re.split(r'(?=^ID:\s)', items_content, flags=re.MULTILINE)
        for block in item_blocks:
            if not block.strip():
                continue
            
            item_id_match = re.search(r'^ID:\s*(.+)$', block, re.MULTILINE)
            item_name_en_match = re.search(r'^Name:\s*(.+)$', block, re.MULTILINE)
            item_name_fr_match = re.search(r'^Nom:\s*(.+)$', block, re.MULTILINE)
            
            if item_id_match:
                item_id = item_id_match.group(1).strip()
                item_name_en = item_name_en_match.group(1).strip() if item_name_en_match else ""
                item_name_fr = item_name_fr_match.group(1).strip() if item_name_fr_match else item_name_en
                
                # Description de l'item
                item_desc_en = ""
                item_desc_fr = ""
                item_desc_en_match = re.search(r'-- Desc \(en\) --\s*(.+?)(?=-- Desc \(fr\) --|-- End desc ---|^ID:|$)', block, re.DOTALL)
                if item_desc_en_match:
                    item_desc_en = item_desc_en_match.group(1).strip()
                item_desc_fr_match = re.search(r'-- Desc \(fr\) --\s*(.+?)(?=-- End desc ---|^ID:|$)', block, re.DOTALL)
                if item_desc_fr_match:
                    item_desc_fr = item_desc_fr_match.group(1).strip()
                
                items[item_id] = ItemTranslation(
                    id=item_id,
                    name_en=item_name_en,
                    name_fr=item_name_fr,
                    desc_en=item_desc_en,
                    desc_fr=item_desc_fr
                )
    
    if not name_en and not name_fr:
        return None
    
    return Translation(
        uuid=uuid,
        pack=pack_name,
        name_en=name_en,
        name_fr=name_fr or name_en,
        desc_en=desc_en,
        desc_fr=desc_fr or desc_en,
        status=status,
        items=items
    )


def load_journal_pages() -> Dict[str, str]:
    """Charge les pages de journaux (descriptions complètes des classes, etc.)."""
    journals = {}  # Clé = UUID de la page, Valeur = description FR
    
    data_dir = RAW_DIR / "pf2-fr" / "data" / "journals"
    if not data_dir.exists():
        return journals
    
    # Parcourir les sous-dossiers pages-*
    for subdir in data_dir.iterdir():
        if subdir.is_dir() and subdir.name.startswith("pages-"):
            for htm_file in subdir.glob("*.htm"):
                try:
                    content = htm_file.read_text(encoding="utf-8")
                    uuid = htm_file.stem
                    
                    # Extraire la description FR
                    desc_fr_match = re.search(r'-- Desc \(fr\) --\s*(.+?)(?=-- End desc ---|$)', content, re.DOTALL)
                    if desc_fr_match:
                        journals[uuid] = desc_fr_match.group(1).strip()
                except:
                    pass
    
    return journals


def extract_journal_entries() -> List[dict]:
    """Extrait les pages de journaux comme entrées recherchables."""
    entries = []
    
    data_dir = RAW_DIR / "pf2-fr" / "data" / "journals"
    if not data_dir.exists():
        return entries
    
    # Mapping des dossiers vers les types
    folder_type_map = {
        "pages-GMScreen": "règle",
        "pages-Classes": "classe",
        "pages-Ancestries": "ascendance", 
        "pages-Archetypes": "archétype",
        "pages-Domains": "domaine",
        "pages-RemasterChanges": "règle",
    }
    
    log("Extraction des journaux (règles, etc.)...", "info")
    count = 0
    
    # Parcourir les sous-dossiers pages-*
    for subdir in data_dir.iterdir():
        if not subdir.is_dir() or not subdir.name.startswith("pages-"):
            continue
        
        entry_type = folder_type_map.get(subdir.name, "règle")
        pack_name = subdir.name.replace("pages-", "").lower()
        
        for htm_file in subdir.glob("*.htm"):
            try:
                content = htm_file.read_text(encoding="utf-8")
                uuid = htm_file.stem
                
                # Parser les champs
                name_en = ""
                name_fr = ""
                desc_en = ""
                desc_fr = ""
                
                match = re.search(r'^Name:\s*(.+)$', content, re.MULTILINE)
                if match:
                    name_en = match.group(1).strip()
                
                match = re.search(r'^Nom:\s*(.+)$', content, re.MULTILINE)
                if match:
                    name_fr = match.group(1).strip()
                
                # Description
                desc_en_match = re.search(r'-- Desc \(en\) --\s*(.+?)(?=-- Desc \(fr\) --|-- End desc ---|$)', content, re.DOTALL)
                if desc_en_match:
                    desc_en = desc_en_match.group(1).strip()
                
                desc_fr_match = re.search(r'-- Desc \(fr\) --\s*(.+?)(?=-- End desc ---|$)', content, re.DOTALL)
                if desc_fr_match:
                    desc_fr = desc_fr_match.group(1).strip()
                
                if not name_fr and not name_en:
                    continue
                
                # Créer l'entrée
                entry = {
                    "_id": uuid,
                    "_pack": f"journals-{pack_name}",
                    "_pack_type": entry_type,
                    "_source": "pf2-fr",
                    "_translated": True,
                    "name": name_fr or name_en,
                    "name_fr": name_fr or name_en,
                    "name_en": name_en or name_fr,
                    "description_fr": desc_fr,
                    "type": "journal",
                    "system": {
                        "description": {"value": desc_en or desc_fr}
                    }
                }
                
                entries.append(entry)
                count += 1
                
            except Exception as e:
                pass
    
    log(f"  {count} pages de journaux extraites", "ok")
    return entries


def extract_traits() -> List[dict]:
    """Extrait les traits depuis les fichiers de langue."""
    entries = []
    
    # Chemins des fichiers de langue
    fr_file = RAW_DIR / "pf2-fr" / "lang" / "fr.json"
    en_file = RAW_DIR / "pf2e" / "static" / "lang" / "en.json"
    
    if not fr_file.exists():
        log(f"Fichier de langue FR non trouvé: {fr_file}", "warn")
        return entries
    
    if not en_file.exists():
        log(f"Fichier de langue EN non trouvé: {en_file}", "warn")
        return entries
    
    log("Extraction des traits depuis les fichiers de langue...", "info")
    
    # Charger les fichiers JSON
    try:
        with open(fr_file, 'r', encoding='utf-8') as f:
            fr_data = json.load(f)
        with open(en_file, 'r', encoding='utf-8') as f:
            en_data = json.load(f)
    except Exception as e:
        log(f"Erreur chargement fichiers de langue: {e}", "err")
        return entries
    
    # Extraire les traits FR (dans PF2E.TraitDescriptionXxx)
    fr_traits = {}
    if "PF2E" in fr_data:
        for key, value in fr_data["PF2E"].items():
            if key.startswith("TraitDescription") and isinstance(value, str):
                trait_name = key[len("TraitDescription"):]  # Enlever le préfixe
                fr_traits[trait_name.lower()] = {
                    "name": trait_name,
                    "description": value
                }
    
    # Extraire les traits EN (dans PF2E.TraitDescriptionXxx)
    en_traits = {}
    if "PF2E" in en_data:
        for key, value in en_data["PF2E"].items():
            if key.startswith("TraitDescription") and isinstance(value, str):
                trait_name = key[len("TraitDescription"):]
                en_traits[trait_name.lower()] = {
                    "name": trait_name,
                    "description": value
                }
    
    # Aussi chercher les labels des traits (TraitXxx pour le nom affiché)
    fr_labels = {}
    en_labels = {}
    if "PF2E" in fr_data:
        for key, value in fr_data["PF2E"].items():
            if key.startswith("Trait") and not key.startswith("TraitDescription") and isinstance(value, str):
                trait_key = key[len("Trait"):].lower()
                fr_labels[trait_key] = value
    
    if "PF2E" in en_data:
        for key, value in en_data["PF2E"].items():
            if key.startswith("Trait") and not key.startswith("TraitDescription") and isinstance(value, str):
                trait_key = key[len("Trait"):].lower()
                en_labels[trait_key] = value
    
    # Combiner FR et EN
    all_trait_keys = set(fr_traits.keys()) | set(en_traits.keys())
    
    for trait_key in all_trait_keys:
        fr_info = fr_traits.get(trait_key, {})
        en_info = en_traits.get(trait_key, {})
        
        # Nom du trait (utiliser le label si disponible, sinon le nom de la clé)
        name_fr = fr_labels.get(trait_key, fr_info.get("name", trait_key.capitalize()))
        name_en = en_labels.get(trait_key, en_info.get("name", trait_key.capitalize()))
        
        desc_fr = fr_info.get("description", "")
        desc_en = en_info.get("description", "")
        
        entry = {
            "_id": trait_key,
            "_pack": "traits",
            "_pack_type": "trait",
            "_source": "pf2-fr+pf2e",
            "_translated": bool(desc_fr),
            "name": name_fr or name_en,
            "name_fr": name_fr or name_en,
            "name_en": name_en or name_fr,
            "description_fr": desc_fr,
            "type": "trait",
            "system": {
                "description": {"value": desc_en or desc_fr}
            }
        }
        
        entries.append(entry)
    
    log(f"  {len(entries)} traits extraits", "ok")
    return entries


def extract_npc_abilities() -> List[dict]:
    """Extrait les capacités de PNJ (glossaire) depuis les fichiers de langue."""
    entries = []
    
    fr_file = RAW_DIR / "pf2-fr" / "lang" / "fr.json"
    en_file = RAW_DIR / "pf2e" / "static" / "lang" / "en.json"
    
    if not fr_file.exists() or not en_file.exists():
        log("Fichiers de langue non trouvés pour capacités NPC", "warn")
        return entries
    
    log("Extraction des capacités NPC (glossaire)...", "info")
    
    try:
        with open(fr_file, 'r', encoding='utf-8') as f:
            fr_data = json.load(f)
        with open(en_file, 'r', encoding='utf-8') as f:
            en_data = json.load(f)
    except Exception as e:
        log(f"Erreur chargement fichiers de langue: {e}", "err")
        return entries
    
    # Extraire le glossaire des capacités NPC
    fr_glossary = fr_data.get("PF2E", {}).get("NPC", {}).get("Abilities", {}).get("Glossary", {})
    en_glossary = en_data.get("PF2E", {}).get("NPC", {}).get("Abilities", {}).get("Glossary", {})
    
    # Aussi les AttackEffect pour les noms traduits (Grab -> Agrippement, etc.)
    fr_attack_effects = {}
    en_attack_effects = {}
    for k, v in fr_data.get("PF2E", {}).items():
        if k.startswith("AttackEffect") and isinstance(v, str):
            key = k[len("AttackEffect"):].lower()
            fr_attack_effects[key] = v
    for k, v in en_data.get("PF2E", {}).items():
        if k.startswith("AttackEffect") and isinstance(v, str):
            key = k[len("AttackEffect"):].lower()
            en_attack_effects[key] = v
    
    all_keys = set(fr_glossary.keys()) | set(en_glossary.keys())
    
    for key in all_keys:
        desc_fr = fr_glossary.get(key, "")
        desc_en = en_glossary.get(key, "")
        
        # Chercher le nom traduit dans AttackEffect ou utiliser la clé
        name_fr = fr_attack_effects.get(key.lower(), key)
        name_en = en_attack_effects.get(key.lower(), key)
        
        entry = {
            "_id": f"npc-ability-{key.lower()}",
            "_pack": "npc-abilities",
            "_pack_type": "capacité",
            "_source": "pf2-fr+pf2e",
            "_translated": bool(desc_fr),
            "name": name_fr or name_en,
            "name_fr": name_fr or name_en,
            "name_en": name_en or name_fr,
            "description_fr": desc_fr,
            "type": "capacité",
            "system": {
                "description": {"value": desc_en or desc_fr}
            }
        }
        entries.append(entry)
    
    log(f"  {len(entries)} capacités NPC extraites", "ok")
    return entries


def extract_conditions() -> List[dict]:
    """Extrait les états/conditions depuis les fichiers de langue."""
    entries = []
    
    fr_file = RAW_DIR / "pf2-fr" / "lang" / "fr.json"
    en_file = RAW_DIR / "pf2e" / "static" / "lang" / "en.json"
    
    if not fr_file.exists() or not en_file.exists():
        log("Fichiers de langue non trouvés pour conditions", "warn")
        return entries
    
    log("Extraction des états/conditions...", "info")
    
    try:
        with open(fr_file, 'r', encoding='utf-8') as f:
            fr_data = json.load(f)
        with open(en_file, 'r', encoding='utf-8') as f:
            en_data = json.load(f)
    except Exception as e:
        log(f"Erreur chargement fichiers de langue: {e}", "err")
        return entries
    
    # Extraire les conditions (ConditionTypeXxx)
    fr_conditions = {}
    en_conditions = {}
    
    for k, v in fr_data.get("PF2E", {}).items():
        if k.startswith("ConditionType") and isinstance(v, str):
            cond_key = k[len("ConditionType"):].lower()
            fr_conditions[cond_key] = v
    
    for k, v in en_data.get("PF2E", {}).items():
        if k.startswith("ConditionType") and isinstance(v, str):
            cond_key = k[len("ConditionType"):].lower()
            en_conditions[cond_key] = v
    
    all_keys = set(fr_conditions.keys()) | set(en_conditions.keys())
    
    for key in all_keys:
        name_fr = fr_conditions.get(key, "")
        name_en = en_conditions.get(key, "")
        
        # Note: Les descriptions des conditions sont dans les items du compendium conditionitems
        # Ici on extrait juste les noms traduits comme référence rapide
        entry = {
            "_id": f"condition-{key}",
            "_pack": "conditions",
            "_pack_type": "état",
            "_source": "pf2-fr+pf2e",
            "_translated": bool(name_fr),
            "name": name_fr or name_en,
            "name_fr": name_fr or name_en,
            "name_en": name_en or name_fr,
            "description_fr": "",  # Descriptions dans les items du compendium
            "type": "état",
            "system": {
                "description": {"value": ""}
            }
        }
        entries.append(entry)
    
    log(f"  {len(entries)} états/conditions extraits", "ok")
    return entries


def extract_materials() -> List[dict]:
    """Extrait les matériaux précieux depuis les fichiers de langue."""
    entries = []
    
    fr_file = RAW_DIR / "pf2-fr" / "lang" / "fr.json"
    en_file = RAW_DIR / "pf2e" / "static" / "lang" / "en.json"
    
    if not fr_file.exists() or not en_file.exists():
        log("Fichiers de langue non trouvés pour matériaux", "warn")
        return entries
    
    log("Extraction des matériaux précieux...", "info")
    
    try:
        with open(fr_file, 'r', encoding='utf-8') as f:
            fr_data = json.load(f)
        with open(en_file, 'r', encoding='utf-8') as f:
            en_data = json.load(f)
    except Exception as e:
        log(f"Erreur chargement fichiers de langue: {e}", "err")
        return entries
    
    # Extraire les noms et descriptions des matériaux précieux
    fr_names = {}
    fr_descs = {}
    en_names = {}
    en_descs = {}
    
    for k, v in fr_data.get("PF2E", {}).items():
        if k.startswith("PreciousMaterial") and isinstance(v, str):
            if "Description" in k:
                mat_key = k[len("PreciousMaterial"):-len("Description")].lower()
                fr_descs[mat_key] = v
            elif "Grade" not in k and "Label" not in k:
                mat_key = k[len("PreciousMaterial"):].lower()
                fr_names[mat_key] = v
    
    for k, v in en_data.get("PF2E", {}).items():
        if k.startswith("PreciousMaterial") and isinstance(v, str):
            if "Description" in k:
                mat_key = k[len("PreciousMaterial"):-len("Description")].lower()
                en_descs[mat_key] = v
            elif "Grade" not in k and "Label" not in k:
                mat_key = k[len("PreciousMaterial"):].lower()
                en_names[mat_key] = v
    
    # Ne garder que les matériaux qui ont une description
    all_keys = set(fr_descs.keys()) | set(en_descs.keys())
    
    for key in all_keys:
        name_fr = fr_names.get(key, key.capitalize())
        name_en = en_names.get(key, key.capitalize())
        desc_fr = fr_descs.get(key, "")
        desc_en = en_descs.get(key, "")
        
        entry = {
            "_id": f"material-{key}",
            "_pack": "materials",
            "_pack_type": "matériau",
            "_source": "pf2-fr+pf2e",
            "_translated": bool(desc_fr),
            "name": name_fr or name_en,
            "name_fr": name_fr or name_en,
            "name_en": name_en or name_fr,
            "description_fr": desc_fr,
            "type": "matériau",
            "system": {
                "description": {"value": desc_en or desc_fr}
            }
        }
        entries.append(entry)
    
    log(f"  {len(entries)} matériaux précieux extraits", "ok")
    return entries


def extract_glossary() -> List[dict]:
    """Extrait les termes génériques du glossaire depuis les fichiers de langue."""
    entries = []
    
    fr_file = RAW_DIR / "pf2-fr" / "lang" / "fr.json"
    en_file = RAW_DIR / "pf2e" / "static" / "lang" / "en.json"
    
    if not fr_file.exists() or not en_file.exists():
        log("Fichiers de langue non trouvés pour glossaire", "warn")
        return entries
    
    log("Extraction du glossaire général...", "info")
    
    try:
        with open(fr_file, 'r', encoding='utf-8') as f:
            fr_data = json.load(f)
        with open(en_file, 'r', encoding='utf-8') as f:
            en_data = json.load(f)
    except Exception as e:
        log(f"Erreur chargement fichiers de langue: {e}", "err")
        return entries
    
    fr_pf2e = fr_data.get("PF2E", {})
    en_pf2e = en_data.get("PF2E", {})
    
    # Définir les catégories à extraire
    categories = {
        "ActorSize": ("taille", "Taille"),
        "ProficiencyLevel": ("maîtrise", "Niveau de maîtrise"),
        "DCAdjustment": ("dd", "Ajustement DD"),
        "ActionType": ("type-action", "Type d'action"),
        "PreparationType": ("préparation", "Type de préparation"),
        "WeaponGroup": ("groupe-arme", "Groupe d'armes"),
        "ArmorGroup": ("groupe-armure", "Groupe d'armures"),
        "WeaponType": ("type-arme", "Type d'arme"),
        "ArmorType": ("type-armure", "Type d'armure"),
        "Currency": ("devise", "Devise"),
    }
    
    # Extraire les clés simples (string values)
    for prefix, (id_prefix, category_label) in categories.items():
        fr_items = {k: v for k, v in fr_pf2e.items() 
                    if k.startswith(prefix) and isinstance(v, str)
                    and "Label" not in k and "Header" not in k and "Title" not in k}
        en_items = {k: v for k, v in en_pf2e.items() 
                    if k.startswith(prefix) and isinstance(v, str)
                    and "Label" not in k and "Header" not in k and "Title" not in k}
        
        all_keys = set(fr_items.keys()) | set(en_items.keys())
        
        for key in all_keys:
            # Extraire le suffixe (ex: "ActorSizeLarge" -> "Large")
            suffix = key[len(prefix):]
            if not suffix:
                continue
                
            name_fr = fr_items.get(key, "")
            name_en = en_items.get(key, "")
            
            if not name_fr and not name_en:
                continue
            
            entry = {
                "_id": f"glossaire-{id_prefix}-{suffix.lower()}",
                "_pack": "glossaire",
                "_pack_type": "glossaire",
                "_source": "pf2-fr+pf2e",
                "_translated": bool(name_fr),
                "name": name_fr or name_en,
                "name_fr": name_fr or name_en,
                "name_en": name_en or name_fr,
                "description_fr": f"Catégorie: {category_label}",
                "type": "glossaire",
                "glossary_category": category_label,
                "system": {
                    "description": {"value": f"Category: {category_label}"}
                }
            }
            entries.append(entry)
    
    # Extraire les compétences (Skill dict)
    fr_skills = fr_pf2e.get("Skill", {})
    en_skills = en_pf2e.get("Skill", {})
    if isinstance(fr_skills, dict) and isinstance(en_skills, dict):
        all_skill_keys = set(fr_skills.keys()) | set(en_skills.keys())
        for key in all_skill_keys:
            fr_val = fr_skills.get(key, "")
            en_val = en_skills.get(key, "")
            if isinstance(fr_val, str) and isinstance(en_val, str):
                entry = {
                    "_id": f"glossaire-compétence-{key.lower()}",
                    "_pack": "glossaire",
                    "_pack_type": "glossaire",
                    "_source": "pf2-fr+pf2e",
                    "_translated": bool(fr_val),
                    "name": fr_val or en_val,
                    "name_fr": fr_val or en_val,
                    "name_en": en_val or fr_val,
                    "description_fr": "Catégorie: Compétence",
                    "type": "glossaire",
                    "glossary_category": "Compétence",
                    "system": {
                        "description": {"value": "Category: Skill"}
                    }
                }
                entries.append(entry)
    
    # Extraire les types de dégâts (Damage.IWR.Type)
    fr_damage = fr_pf2e.get("Damage", {})
    en_damage = en_pf2e.get("Damage", {})
    if isinstance(fr_damage, dict) and isinstance(en_damage, dict):
        fr_types = fr_damage.get("IWR", {}).get("Type", {}) if isinstance(fr_damage.get("IWR"), dict) else {}
        en_types = en_damage.get("IWR", {}).get("Type", {}) if isinstance(en_damage.get("IWR"), dict) else {}
        
        all_damage_keys = set(fr_types.keys()) | set(en_types.keys())
        for key in all_damage_keys:
            fr_val = fr_types.get(key, "")
            en_val = en_types.get(key, "")
            if fr_val or en_val:
                entry = {
                    "_id": f"glossaire-dégât-{key.lower()}",
                    "_pack": "glossaire",
                    "_pack_type": "glossaire",
                    "_source": "pf2-fr+pf2e",
                    "_translated": bool(fr_val),
                    "name": fr_val or en_val,
                    "name_fr": fr_val or en_val,
                    "name_en": en_val or fr_val,
                    "description_fr": "Catégorie: Type de dégât/immunité/résistance",
                    "type": "glossaire",
                    "glossary_category": "Type de dégât",
                    "system": {
                        "description": {"value": "Category: Damage/IWR Type"}
                    }
                }
                entries.append(entry)
    
    # Extraire les formes de zone (Area.Shape)
    fr_area = fr_pf2e.get("Area", {})
    en_area = en_pf2e.get("Area", {})
    if isinstance(fr_area, dict) and isinstance(en_area, dict):
        fr_shapes = fr_area.get("Shape", {}) if isinstance(fr_area.get("Shape"), dict) else {}
        en_shapes = en_area.get("Shape", {}) if isinstance(en_area.get("Shape"), dict) else {}
        
        all_shape_keys = set(fr_shapes.keys()) | set(en_shapes.keys())
        for key in all_shape_keys:
            fr_val = fr_shapes.get(key, "")
            en_val = en_shapes.get(key, "")
            if fr_val or en_val:
                entry = {
                    "_id": f"glossaire-zone-{key.lower()}",
                    "_pack": "glossaire",
                    "_pack_type": "glossaire",
                    "_source": "pf2-fr+pf2e",
                    "_translated": bool(fr_val),
                    "name": fr_val or en_val,
                    "name_fr": fr_val or en_val,
                    "name_en": en_val or fr_val,
                    "description_fr": "Catégorie: Forme de zone",
                    "type": "glossaire",
                    "glossary_category": "Forme de zone",
                    "system": {
                        "description": {"value": "Category: Area Shape"}
                    }
                }
                entries.append(entry)
    
    # Extraire les durées (Duration dict)
    fr_duration = fr_pf2e.get("Duration", {})
    en_duration = en_pf2e.get("Duration", {})
    if isinstance(fr_duration, dict) and isinstance(en_duration, dict):
        all_dur_keys = set(fr_duration.keys()) | set(en_duration.keys())
        for key in all_dur_keys:
            fr_val = fr_duration.get(key, "")
            en_val = en_duration.get(key, "")
            if isinstance(fr_val, str) and isinstance(en_val, str):
                entry = {
                    "_id": f"glossaire-durée-{key.lower()}",
                    "_pack": "glossaire",
                    "_pack_type": "glossaire",
                    "_source": "pf2-fr+pf2e",
                    "_translated": bool(fr_val),
                    "name": fr_val or en_val,
                    "name_fr": fr_val or en_val,
                    "name_en": en_val or fr_val,
                    "description_fr": "Catégorie: Durée",
                    "type": "glossaire",
                    "glossary_category": "Durée",
                    "system": {
                        "description": {"value": "Category: Duration"}
                    }
                }
                entries.append(entry)
    
    # Extraire les jets de sauvegarde
    saves_mapping = {
        "SavesFortitude": "Vigueur",
        "SavesReflex": "Réflexes",
        "SavesWill": "Volonté",
    }
    for key, default_fr in saves_mapping.items():
        fr_val = fr_pf2e.get(key, "")
        en_val = en_pf2e.get(key, "")
        if fr_val or en_val:
            entry = {
                "_id": f"glossaire-sauvegarde-{key.replace('Saves', '').lower()}",
                "_pack": "glossaire",
                "_pack_type": "glossaire",
                "_source": "pf2-fr+pf2e",
                "_translated": bool(fr_val),
                "name": fr_val or en_val,
                "name_fr": fr_val or default_fr,
                "name_en": en_val or key.replace('Saves', ''),
                "description_fr": "Catégorie: Jet de sauvegarde",
                "type": "glossaire",
                "glossary_category": "Jet de sauvegarde",
                "system": {
                    "description": {"value": "Category: Saving Throw"}
                }
            }
            entries.append(entry)
    
    log(f"  {len(entries)} entrées de glossaire extraites", "ok")
    return entries


def load_all_translations() -> Tuple[Dict[str, Translation], Dict[str, str]]:
    """Charge toutes les traductions depuis les fichiers .htm."""
    translations = {}  # Clé = UUID
    
    data_dir = RAW_DIR / "pf2-fr" / "data"
    if not data_dir.exists():
        log("pf2-fr/data non trouvé", "warn")
        return translations, {}
    
    # Parcourir tous les dossiers (chaque dossier = un pack)
    pack_dirs = [d for d in data_dir.iterdir() if d.is_dir()]
    
    log(f"Chargement traductions depuis {len(pack_dirs)} packs...", "info")
    
    total = 0
    items_total = 0
    
    for pack_dir in pack_dirs:
        pack_name = pack_dir.name
        
        # Fichiers .htm directs dans le pack
        htm_files = list(pack_dir.glob("*.htm"))
        
        # Aussi chercher dans les sous-dossiers (pour journals/pages-*)
        for subdir in pack_dir.iterdir():
            if subdir.is_dir():
                htm_files.extend(subdir.glob("*.htm"))
        
        pack_count = 0
        for htm_file in htm_files:
            trans = parse_htm_file(htm_file, pack_name)
            if trans:
                translations[trans.uuid] = trans
                pack_count += 1
                items_total += len(trans.items)
        
        if pack_count > 0:
            total += pack_count
    
    log(f"  {total} traductions, {items_total} items traduits", "ok")
    
    # Charger les journaux (descriptions complètes)
    journals = load_journal_pages()
    if journals:
        log(f"  {len(journals)} pages de journaux chargées", "ok")
    
    return translations, journals

# ============================================================================
# PARSING DES FICHIERS FOUNDRY (.json)
# ============================================================================

def parse_json_file(filepath: Path) -> Optional[dict]:
    """Parse un fichier JSON individuel."""
    try:
        content = filepath.read_text(encoding="utf-8")
        entry = json.loads(content)
        if isinstance(entry, dict):
            return entry
    except:
        pass
    return None


def apply_translation(entry: dict, trans: Optional[Translation], journals: Dict[str, str] = None) -> dict:
    """Applique une traduction à une entrée Foundry."""
    if not trans:
        entry["name_fr"] = entry.get("name", "")
        entry["name_en"] = entry.get("name", "")
        entry["description_fr"] = ""
        entry["_translated"] = False
        return entry
    
    entry["name_fr"] = trans.name_fr
    entry["name_en"] = trans.name_en or entry.get("name", "")
    entry["description_fr"] = trans.desc_fr
    entry["_translated"] = True
    entry["_trans_status"] = trans.status
    
    # Pour les classes, ascendances et archétypes, chercher la description complète dans les journaux
    entry_type = entry.get("type", "")
    if journals and entry_type in ["class", "ancestry", "archetype"]:
        # Chercher une référence @UUID vers un journal dans la description
        desc = trans.desc_fr or trans.desc_en or ""
        # Format: @UUID[Compendium.pf2e.journals.JournalEntry.XXX.JournalEntryPage.YYY]{...}
        match = re.search(r'@UUID\[Compendium\.pf2e\.journals\.JournalEntry\.[^.]+\.JournalEntryPage\.([^\]]+)\]', desc)
        if match:
            page_uuid = match.group(1)
            if page_uuid in journals:
                entry["description_fr"] = journals[page_uuid]
                entry["_has_journal"] = True
    
    # Appliquer les traductions aux items (attaques, capacités)
    if "items" in entry and trans.items:
        for item in entry.get("items", []):
            if not isinstance(item, dict):
                continue
            item_id = item.get("_id", "")
            if item_id and item_id in trans.items:
                item_trans = trans.items[item_id]
                item["name_fr"] = item_trans.name_fr
                item["name_en"] = item_trans.name_en or item.get("name", "")
                if item_trans.desc_fr:
                    item["description_fr"] = item_trans.desc_fr
                item["_translated"] = True
            else:
                item["name_fr"] = item.get("name", "")
                item["name_en"] = item.get("name", "")
                item["_translated"] = False
    
    return entry


def extract_foundry_with_translations(translations: Dict[str, Translation], journals: Dict[str, str] = None) -> Tuple[List[dict], Dict[str, int]]:
    """Extrait les données Foundry et applique les traductions."""
    entries = []
    stats = defaultdict(int)
    seen_keys = set()
    
    if journals is None:
        journals = {}
    
    # Nouveau chemin: pf2e/packs/pf2e/
    packs_dir = RAW_DIR / "pf2e" / "packs" / "pf2e"
    if not packs_dir.exists():
        # Fallback ancien chemin
        packs_dir = RAW_DIR / "pf2e" / "packs"
    
    if not packs_dir.exists():
        log("Foundry packs non trouvé", "warn")
        return entries, dict(stats)
    
    # Chercher tous les fichiers JSON (nouveau format: un fichier = une entrée)
    all_files = list(packs_dir.glob("**/*.json"))
    # Exclure les fichiers _folders.json et _source.json
    all_files = [f for f in all_files if not f.name.startswith("_")]
    
    log(f"Extraction de {len(all_files)} fichiers Foundry...", "info")
    
    translated_count = 0
    pack_stats = defaultdict(lambda: {"total": 0, "translated": 0})
    
    for filepath in all_files:
        # Déterminer le pack depuis le chemin
        # Structure: packs/pf2e/{pack-name}/.../{file}.json
        rel_path = filepath.relative_to(packs_dir)
        pack_name = rel_path.parts[0] if rel_path.parts else "unknown"
        
        item = parse_json_file(filepath)
        if not item or not isinstance(item, dict):
            continue
        
        entry_id = item.get("_id", "")
        if not entry_id:
            continue
        
        unique_key = f"{pack_name}:{entry_id}"
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        
        # Chercher la traduction par UUID
        trans = translations.get(entry_id)
        
        # Détecter le type
        entry_type = detect_type_from_entry(item)
        if entry_type == "autre":
            entry_type = detect_type_from_pack(pack_name)
        
        # Appliquer traduction (avec journaux pour les classes)
        item = apply_translation(item, trans, journals)
        
        # Construire l'entrée finale
        entry = {
            "_id": entry_id,
            "_pack": pack_name,
            "_pack_type": entry_type,
            "_source": "foundry+pf2-fr",
            "_translated": item.get("_translated", False),
            "name": item.get("name_fr") or item.get("name", ""),
            "name_fr": item.get("name_fr") or item.get("name", ""),
            "name_en": item.get("name_en") or item.get("name", ""),
            "description": item.get("description_fr") or "",
            "type": item.get("type", ""),
            "system": item.get("system", {}),
            "items": item.get("items", []),
        }
        
        entries.append(entry)
        stats[entry_type] += 1
        pack_stats[pack_name]["total"] += 1
        if item.get("_translated"):
            pack_stats[pack_name]["translated"] += 1
            translated_count += 1
    
    # Afficher stats par pack (top 10)
    sorted_packs = sorted(pack_stats.items(), key=lambda x: -x[1]["total"])[:10]
    for pack_name, pstats in sorted_packs:
        pct = (pstats["translated"] / pstats["total"] * 100) if pstats["total"] else 0
        log(f"  {pack_name}: {pstats['total']} entrées ({pstats['translated']} FR, {pct:.0f}%)", "dim")
    
    log(f"  Total: {len(entries)} entrées, {translated_count} traduites", "ok")
    return entries, dict(stats)

# ============================================================================
# BASE DE DONNÉES
# ============================================================================

def create_database(entries: List[dict], stats: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists():
        DB_FILE.unlink()
    
    log("Création base de données...", "info")
    conn = sqlite3.connect(str(DB_FILE))
    cur = conn.cursor()
    
    cur.execute('''CREATE TABLE entries (
        id TEXT NOT NULL, pack TEXT NOT NULL,
        name_fr TEXT NOT NULL, name_en TEXT NOT NULL,
        type TEXT NOT NULL, source TEXT NOT NULL,
        translated INTEGER NOT NULL, data TEXT NOT NULL,
        PRIMARY KEY (pack, id))''')
    
    cur.execute('CREATE INDEX idx_name_fr ON entries(name_fr COLLATE NOCASE)')
    cur.execute('CREATE INDEX idx_name_en ON entries(name_en COLLATE NOCASE)')
    cur.execute('CREATE INDEX idx_type ON entries(type)')
    cur.execute('CREATE INDEX idx_pack ON entries(pack)')
    cur.execute('CREATE INDEX idx_id ON entries(id)')
    
    cur.execute('''CREATE VIRTUAL TABLE entries_fts USING fts5(
        name_fr, name_en, pack, description,
        content=entries, content_rowid=rowid)''')
    
    cur.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)')
    
    log(f"Insertion {len(entries)} entrées...", "dim")
    inserted = 0
    for entry in entries:
        entry_id = entry.get("_id", "")
        pack = entry.get("_pack", "unknown")
        name_fr = entry.get("name_fr", "")
        name_en = entry.get("name_en", "")
        entry_type = entry.get("_pack_type", "autre")
        source = entry.get("_source", "unknown")
        translated = 1 if entry.get("_translated", False) else 0
        desc = entry.get("description", "")
        if isinstance(desc, dict):
            desc = desc.get("value", "")
        data_json = json.dumps(entry, ensure_ascii=False)
        
        try:
            cur.execute('INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (entry_id, pack, name_fr, name_en, entry_type, source, translated, data_json))
            rowid = cur.lastrowid
            cur.execute('INSERT INTO entries_fts (rowid, name_fr, name_en, pack, description) VALUES (?, ?, ?, ?, ?)',
                       (rowid, name_fr, name_en, pack, desc[:5000]))
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    
    trans_ct = sum(1 for e in entries if e.get("_translated"))
    
    meta = {"created_at": datetime.now().isoformat(), "total": inserted,
            "translated": trans_ct, "stats": json.dumps(stats), "version": "6.0"}
    for k, v in meta.items():
        cur.execute('INSERT INTO metadata VALUES (?, ?)', (k, str(v)))
    
    conn.commit()
    conn.close()
    
    size_mb = DB_FILE.stat().st_size / (1024 * 1024)
    log(f"Base créée: {size_mb:.1f} MB, {inserted} entrées", "ok")
    log(f"  {trans_ct} traduites ({trans_ct/inserted*100:.1f}%)", "dim")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{C.BOLD}{'═' * 60}")
    print("🎲 PF2e Data Extractor v6 - HTM-Based")
    print(f"{'═' * 60}{C.RESET}\n")
    
    args = sys.argv[1:]
    if "--clean" in args:
        if DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
        log("Données supprimées", "ok")
        print()
    
    skip_download = "--local" in args
    
    if not skip_download:
        print(f"{C.BOLD}[1/4] Téléchargement{C.RESET}")
        results = download_repos()
        print()
        if not any(results.values()):
            log("Aucune source disponible!", "err")
            return
    else:
        log("Mode local", "dim")
        print()
    
    # Charger les traductions depuis les fichiers .htm
    print(f"{C.BOLD}[2/4] Chargement traductions (.htm){C.RESET}")
    translations, journals = load_all_translations()
    print()
    
    if not translations:
        log("Aucune traduction chargée!", "warn")
    
    # Extraire Foundry et appliquer les traductions
    print(f"{C.BOLD}[3/4] Extraction Foundry + traductions{C.RESET}")
    entries, stats = extract_foundry_with_translations(translations, journals)
    
    # Ajouter les pages de journaux (règles, etc.)
    journal_entries = extract_journal_entries()
    for je in journal_entries:
        entries.append(je)
        pack_type = je.get("_pack_type", "règle")
        stats[pack_type] = stats.get(pack_type, 0) + 1
    
    # Ajouter les traits depuis les fichiers de langue
    trait_entries = extract_traits()
    for te in trait_entries:
        entries.append(te)
        stats["trait"] = stats.get("trait", 0) + 1
    
    # Ajouter les capacités NPC (glossaire)
    npc_ability_entries = extract_npc_abilities()
    for ae in npc_ability_entries:
        entries.append(ae)
        stats["capacité"] = stats.get("capacité", 0) + 1
    
    # Ajouter les états/conditions
    condition_entries = extract_conditions()
    for ce in condition_entries:
        entries.append(ce)
        stats["état"] = stats.get("état", 0) + 1
    
    # Ajouter les matériaux précieux
    material_entries = extract_materials()
    for me in material_entries:
        entries.append(me)
        stats["matériau"] = stats.get("matériau", 0) + 1
    
    # Ajouter le glossaire général
    glossary_entries = extract_glossary()
    for ge in glossary_entries:
        entries.append(ge)
        stats["glossaire"] = stats.get("glossaire", 0) + 1
    
    print()
    
    if not entries:
        log("Aucune entrée!", "err")
        return
    
    # Créer la base de données
    print(f"{C.BOLD}[4/4] Base de données{C.RESET}")
    create_database(entries, stats)
    
    # Stats
    print(f"\n{C.BOLD}Par type:{C.RESET}")
    for t, c in sorted(stats.items(), key=lambda x: -x[1])[:15]:
        pct = (c / len(entries)) * 100
        print(f"  {t:.<22} {c:>6} ({pct:>5.1f}%)")
    
    print(f"\n{C.GREEN}✅ Terminé! → python pf2_search_v5.py{C.RESET}\n")

if __name__ == "__main__":
    main()
