#!/usr/bin/env python3
"""
PF2e Search v5 - COMPLET
========================
Recherche avec affichage détaillé de toutes les stats.

Usage:
    python pf2_search_v5.py                    # Mode interactif
    python pf2_search_v5.py "loup"             # Recherche
    python pf2_search_v5.py "loup" --full      # Avec détails complets
    python pf2_search_v5.py créature:wolf      # Par type
    python pf2_search_v5.py --pack bestiary wolf

Interactif:
    loup              → recherche
    1                 → détails de l'entrée 1
    full 1            → détails complets
    créature:dragon   → filtre par type
    pack:bestiary loup → filtre par pack
"""

import json
import re
import html
import sys
import sqlite3
import textwrap
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

DATA_DIR = Path("pf2_data")
DB_FILE = DATA_DIR / "pf2e_v5.db"


def normalize_text(text: str) -> str:
    """Normalise le texte en retirant les accents."""
    # Décompose les caractères accentués (é -> e + accent)
    # puis retire les marques diacritiques
    normalized = unicodedata.normalize('NFD', text)
    return ''.join(c for c in normalized if unicodedata.category(c) != 'Mn').lower()


# ============================================================================
# COULEURS
# ============================================================================

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG = "\033[48;5;236m"
    ORANGE = "\033[38;5;208m"

if not sys.stdout.isatty():
    for attr in dir(C):
        if not attr.startswith('_'):
            setattr(C, attr, '')

# ============================================================================
# UTILITAIRES
# ============================================================================

def clean_html(text: str) -> str:
    """Nettoie le HTML pour affichage terminal."""
    if not text:
        return ""
    
    text = html.unescape(text)
    text = re.sub(r'<strong>|<b>', C.BOLD, text)
    text = re.sub(r'</strong>|</b>', C.RESET, text)
    text = re.sub(r'<em>|<i>', '', text)
    text = re.sub(r'</em>|</i>', '', text)
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text)
    text = re.sub(r'<p[^>]*>', '', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<hr[^>]*>', '\n' + '─' * 50 + '\n', text)
    text = re.sub(r'<li[^>]*>', '  • ', text)
    text = re.sub(r'</li>', '\n', text)
    text = re.sub(r'<ul[^>]*>|</ul>', '', text)
    text = re.sub(r'<h\d[^>]*>([^<]*)</h\d>', r'\n\1\n', text)
    # Références Foundry
    text = re.sub(r'@UUID\[Compendium\.[^\]]+\]\{([^}]+)\}', r'⟨\1⟩', text)
    text = re.sub(r'@Compendium\[[^\]]+\]\{([^}]+)\}', r'⟨\1⟩', text)
    text = re.sub(r'@Check\[([^\]|]+)[^\]]*\]', r'[\1]', text)
    text = re.sub(r'@Damage\[([^\]]+)\](\{[^}]+\})?', r'[\1]', text)
    text = re.sub(r'\[\[/r(?:oll)?\s*([^\]#\]]+)[^\]]*\]\](\{[^}]+\})?', r'[\1]', text)
    text = re.sub(r'<span[^>]*>|</span>', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def format_mod(val) -> str:
    """Formate un modificateur avec signe."""
    if val is None:
        return "?"
    try:
        v = int(val)
        return f"+{v}" if v >= 0 else str(v)
    except:
        return str(val)

def format_traits(traits: list, rarity: str = None) -> str:
    """Formate les traits."""
    if not traits and not rarity:
        return ""
    
    parts = []
    rarity_colors = {"uncommon": C.YELLOW, "rare": C.MAGENTA, "unique": C.RED}
    
    if rarity and rarity.lower() not in ["common", ""]:
        color = rarity_colors.get(rarity.lower(), C.CYAN)
        parts.append(f"{color}[{rarity}]{C.RESET}")
    
    for trait in (traits or []):
        t = trait.get("value", trait) if isinstance(trait, dict) else str(trait)
        if t.lower() not in rarity_colors:
            parts.append(f"{C.CYAN}[{t}]{C.RESET}")
    
    return " ".join(parts)

def format_actions(actions) -> str:
    """Symboles d'actions."""
    if actions is None:
        return ""
    
    mapping = {
        "1": "◆", "2": "◆◆", "3": "◆◆◆",
        1: "◆", 2: "◆◆", 3: "◆◆◆",
        "reaction": "↺", "free": "◇", "passive": "—",
    }
    
    if isinstance(actions, dict):
        actions = actions.get("value")
    
    return mapping.get(actions, str(actions) if actions else "")

# ============================================================================
# EXTRACTION DONNÉES
# ============================================================================

def get_level(entry: dict) -> Optional[int]:
    """Extrait le niveau."""
    system = entry.get("system", {})
    
    if "level" in system:
        lvl = system["level"]
        return lvl.get("value") if isinstance(lvl, dict) else lvl
    
    details = system.get("details", {})
    if "level" in details:
        lvl = details["level"]
        return lvl.get("value") if isinstance(lvl, dict) else lvl
    
    return None

def get_traits(entry: dict) -> Tuple[List[str], Optional[str]]:
    """Retourne (traits, rarity)."""
    system = entry.get("system", {})
    traits_data = system.get("traits", {})
    
    if isinstance(traits_data, dict):
        traits = traits_data.get("value", [])
        rarity = traits_data.get("rarity")
    elif isinstance(traits_data, list):
        traits = traits_data
        rarity = None
    else:
        traits, rarity = [], None
    
    return traits, rarity

def get_description(entry: dict) -> str:
    """Extrait la description."""
    # D'abord essayer description_fr (traductions)
    desc_fr = entry.get("description_fr", "")
    if desc_fr:
        return str(desc_fr)
    
    # Ensuite description directe (pf2-data-fr)
    desc = entry.get("description", "")
    if desc:
        if isinstance(desc, dict):
            desc = desc.get("value", "")
        if desc:
            return str(desc)
    
    system = entry.get("system", {})
    pack_type = entry.get("_pack_type", "")
    
    # Pour les créatures, chercher publicNotes
    if pack_type == "créature" and "details" in system:
        notes = system["details"].get("publicNotes", "")
        if notes:
            return notes
    
    # Description système
    if "description" in system:
        d = system["description"]
        return d.get("value", str(d)) if isinstance(d, dict) else str(d)
    
    return ""

# ============================================================================
# AFFICHAGE COMPACT (liste)
# ============================================================================

def display_compact(entry: dict, idx: int):
    """Affiche une entrée en mode liste."""
    name_fr = entry.get("name_fr", entry.get("name", ""))
    name_en = entry.get("name_en", "")
    level = get_level(entry)
    traits, rarity = get_traits(entry)
    pack_type = entry.get("_pack_type", "?")
    pack = entry.get("_pack", "?")
    desc = get_description(entry)
    translated = entry.get("_translated", True)
    entry_id = entry.get("_id", "")
    
    print()
    # Titre
    print(f"{C.BG}{C.BOLD} {idx}. {name_fr} {C.RESET}", end="")
    if name_en and name_en.lower() != name_fr.lower():
        print(f" {C.DIM}({name_en}){C.RESET}", end="")
    print()
    
    # Type, niveau, pack
    print(f"   {C.DIM}[{pack_type}]{C.RESET}", end="")
    if level is not None:
        print(f" {C.YELLOW}Niv.{level}{C.RESET}", end="")
    print(f" {C.MAGENTA}← {pack}{C.RESET}", end="")
    if not translated:
        print(f" {C.RED}[EN]{C.RESET}", end="")
    if entry_id:
        print(f" {C.DIM}#{entry_id[:8]}{C.RESET}", end="")
    print()
    
    # Traits
    traits_str = format_traits(traits, rarity)
    if traits_str:
        print(f"   {traits_str}")
    
    # Description courte
    if desc:
        desc_clean = clean_html(desc).replace("\n", " ")
        if len(desc_clean) > 120:
            desc_clean = desc_clean[:117] + "..."
        print(f"   {C.DIM}{desc_clean}{C.RESET}")

# ============================================================================
# AFFICHAGE COMPLET (détails)
# ============================================================================

def display_full(entry: dict):
    """Affiche TOUS les détails d'une entrée."""
    name_fr = entry.get("name_fr", entry.get("name", ""))
    name_en = entry.get("name_en", "")
    level = get_level(entry)
    traits, rarity = get_traits(entry)
    pack_type = entry.get("_pack_type", "?")
    pack = entry.get("_pack", "?")
    desc = get_description(entry)
    system = entry.get("system", {})
    entry_id = entry.get("_id", "")
    source = entry.get("_source", "")
    items = entry.get("items", [])
    
    w = 70  # Largeur
    
    # Mapping des types pour l'affichage
    type_display = {
        "créature": "Créature", "sort": "Sort", "don": "Don", 
        "action": "Action", "équipement": "Équipement", "arme": "Arme",
        "armure": "Armure", "consommable": "Consommable", "danger": "Danger",
        "ascendance": "Ascendance", "héritage": "Héritage", "historique": "Historique",
        "classe": "Classe", "archétype": "Archétype", "divinité": "Divinité",
        "état": "État", "effet": "Effet", "compagnon": "Compagnon",
        "familier": "Familier", "véhicule": "Véhicule", "trésor": "Trésor",
        "règle": "Règle", "domaine": "Domaine", "trait": "Trait",
        "capacité": "Capacité", "matériau": "Matériau", "glossaire": "Glossaire",
    }
    type_label = type_display.get(pack_type, pack_type.capitalize() if pack_type else "")
    
    # Pour les sorts, distinguer cantrip / focus / sort normal
    if pack_type == "sort":
        trait_values = [t.lower() if isinstance(t, str) else t.get("value", "").lower() for t in traits]
        if "cantrip" in trait_values:
            type_label = "Tour de magie"
        elif "focus" in trait_values:
            type_label = "Sort focalisé"
    
    print()
    print(f"{C.BLUE}{'═' * w}{C.RESET}")
    
    # === TITRE ===
    title = f" {name_fr.upper()} "
    if level is not None and type_label:
        print(f"{C.BOLD}{C.WHITE}{title}{C.RESET} {C.YELLOW}{type_label} {level}{C.RESET}")
    elif type_label:
        print(f"{C.BOLD}{C.WHITE}{title}{C.RESET} {C.YELLOW}{type_label}{C.RESET}")
    else:
        print(f"{C.BOLD}{C.WHITE}{title}{C.RESET}")
    
    if name_en and name_en.lower() != name_fr.lower():
        print(f"   {C.DIM}({name_en}){C.RESET}")
    
    # === TRAITS ===
    traits_str = format_traits(traits, rarity)
    if traits_str:
        print(f"   {traits_str}")
    
    # === MÉTADONNÉES ===
    print(f"   {C.DIM}Pack: {pack} | UUID: {entry_id} | Source: {source}{C.RESET}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # === DESCRIPTION ===
    if desc:
        desc_clean = clean_html(desc)
        for para in desc_clean.split('\n'):
            if para.strip():
                wrapped = textwrap.fill(para, width=w-4, initial_indent="   ", subsequent_indent="   ")
                print(wrapped)
        print()
    
    # === STATS SELON LE TYPE ===
    if pack_type == "créature":
        display_creature_full(system, items, w)
    elif pack_type == "sort":
        display_spell_full(system, w)
    elif pack_type == "don":
        display_feat_full(system, w)
    elif pack_type in ["équipement", "arme", "armure", "consommable"]:
        display_equipment_full(system, w)
    elif pack_type == "action":
        display_action_full(system, w)
    elif pack_type == "compagnon":
        display_creature_full(system, items, w)
    elif pack_type == "classe":
        display_class_full(system, items, w)
    
    print(f"{C.BLUE}{'═' * w}{C.RESET}")

def display_creature_full(system: dict, items: list, w: int):
    """Stats complètes d'une créature."""
    
    # === TAILLE ===
    size_map = {
        "tiny": "Très petite (TP)",
        "sm": "Petite (P)",
        "med": "Moyenne (M)",
        "lg": "Grande (G)",
        "huge": "Très grande (TG)",
        "grg": "Gargantuesque (Gar)"
    }
    traits = system.get("traits", {})
    size_value = traits.get("size", {}).get("value", "") if isinstance(traits, dict) else ""
    if size_value:
        size_label = size_map.get(size_value, size_value.capitalize())
        print(f"   {C.GREEN}Taille{C.RESET} {size_label}")
    
    # === PERCEPTION & SENS ===
    perception = system.get("perception", {})
    if perception:
        val = perception.get("mod", perception.get("value", "?"))
        senses = []
        
        # Senses depuis perception
        for sense in perception.get("senses", []):
            if isinstance(sense, dict):
                s = sense.get("type", "")
                if sense.get("acuity"):
                    s += f" ({sense['acuity']})"
                if sense.get("range"):
                    s += f" {sense['range']} m"
                senses.append(s)
            else:
                senses.append(str(sense))
        
        # Senses depuis traits
        traits = system.get("traits", {})
        if isinstance(traits, dict):
            for s in traits.get("senses", {}).get("value", "").split(","):
                s = s.strip()
                if s and s not in senses:
                    senses.append(s)
        
        print(f"   {C.GREEN}Perception{C.RESET} {format_mod(val)}", end="")
        if senses:
            print(f"; {', '.join(senses)}")
        else:
            print()
    
    # === LANGUES ===
    languages = system.get("details", {}).get("languages", {})
    if languages:
        langs = languages.get("value", [])
        if langs:
            print(f"   {C.GREEN}Langues{C.RESET} {', '.join(langs)}")
    
    # === COMPÉTENCES ===
    skills = system.get("skills", {})
    if skills:
        skill_strs = []
        skill_names = {
            "acrobatics": "Acrobaties", "arcana": "Arcanes", "athletics": "Athlétisme",
            "crafting": "Artisanat", "deception": "Duperie", "diplomacy": "Diplomatie",
            "intimidation": "Intimidation", "medicine": "Médecine", "nature": "Nature",
            "occultism": "Occultisme", "performance": "Représentation", "religion": "Religion",
            "society": "Société", "stealth": "Discrétion", "survival": "Survie",
            "thievery": "Vol"
        }
        for k, v in skills.items():
            if isinstance(v, dict) and v.get("base", 0) != 0:
                name = skill_names.get(k, k.capitalize())
                skill_strs.append(f"{name} {format_mod(v.get('base', 0))}")
        if skill_strs:
            print(f"   {C.GREEN}Compétences{C.RESET} {', '.join(skill_strs)}")
    
    # === CARACTÉRISTIQUES ===
    abilities = system.get("abilities", {})
    if abilities:
        ab_strs = []
        names = {"str": "For", "dex": "Dex", "con": "Con", "int": "Int", "wis": "Sag", "cha": "Cha"}
        for ab in ["str", "dex", "con", "int", "wis", "cha"]:
            if ab in abilities:
                mod = abilities[ab].get("mod", 0)
                ab_strs.append(f"{C.BOLD}{names[ab]}{C.RESET} {format_mod(mod)}")
        if ab_strs:
            print(f"   {', '.join(ab_strs)}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # === DÉFENSES ===
    attributes = system.get("attributes", {})
    
    # CA
    ac = attributes.get("ac", {})
    if ac:
        ac_val = ac.get("value", "?")
        ac_details = ac.get("details", "")
        print(f"   {C.GREEN}CA{C.RESET} {ac_val}", end="")
        if ac_details:
            print(f" ({ac_details})")
        else:
            print()
    
    # Sauvegardes
    saves = system.get("saves", {})
    if saves:
        save_strs = []
        names = {"fortitude": "Vigueur", "reflex": "Réflexes", "will": "Volonté"}
        for k, n in names.items():
            if k in saves:
                val = saves[k].get("value", 0)
                save_strs.append(f"{C.BOLD}{n}{C.RESET} {format_mod(val)}")
        if save_strs:
            print(f"   {'; '.join(save_strs)}")
    
    # PV
    hp = attributes.get("hp", {})
    if hp:
        hp_val = hp.get("max", hp.get("value", "?"))
        hp_details = hp.get("details", "")
        print(f"   {C.GREEN}PV{C.RESET} {hp_val}", end="")
        if hp_details:
            print(f" ({hp_details})")
        else:
            print()
    
    # Immunités, Résistances, Faiblesses
    immunities = attributes.get("immunities", [])
    if immunities:
        imm_strs = [i.get("type", str(i)) if isinstance(i, dict) else str(i) for i in immunities]
        print(f"   {C.GREEN}Immunités{C.RESET} {', '.join(imm_strs)}")
    
    resistances = attributes.get("resistances", [])
    if resistances:
        res_strs = []
        for r in resistances:
            if isinstance(r, dict):
                res_strs.append(f"{r.get('type', '?')} {r.get('value', '')}")
            else:
                res_strs.append(str(r))
        if res_strs:
            print(f"   {C.GREEN}Résistances{C.RESET} {', '.join(res_strs)}")
    
    weaknesses = attributes.get("weaknesses", [])
    if weaknesses:
        weak_strs = []
        for w_item in weaknesses:
            if isinstance(w_item, dict):
                weak_strs.append(f"{w_item.get('type', '?')} {w_item.get('value', '')}")
            else:
                weak_strs.append(str(w_item))
        if weak_strs:
            print(f"   {C.GREEN}Faiblesses{C.RESET} {', '.join(weak_strs)}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # === VITESSE ===
    speed = attributes.get("speed", {})
    if speed:
        speed_val = speed.get("value", 0)
        other_speeds = speed.get("otherSpeeds", [])
        print(f"   {C.GREEN}Vitesse{C.RESET} {speed_val} m", end="")
        if other_speeds:
            other_strs = []
            for s in other_speeds:
                if isinstance(s, dict):
                    other_strs.append(f"{s.get('type', '?')} {s.get('value', '')} m")
            if other_strs:
                print(f", {', '.join(other_strs)}")
            else:
                print()
        else:
            print()
    
    # === ATTAQUES ===
    attacks = []
    actions_list = []
    passives = []
    spellcasting = []
    
    for item in items:
        if not isinstance(item, dict):
            continue
        
        item_type = item.get("type", "")
        item_name = item.get("name_fr") or item.get("name", "")
        item_system = item.get("system", {})
        
        if item_type in ["melee", "ranged"]:
            attacks.append(parse_attack(item, item_type))
        elif item_type == "action":
            action_cat = item_system.get("category", "")
            if action_cat == "offensive":
                actions_list.append(parse_action(item))
            elif action_cat == "defensive":
                passives.append(parse_action(item))
            else:
                # Par défaut
                if item_system.get("actions", {}).get("value"):
                    actions_list.append(parse_action(item))
                else:
                    passives.append(parse_action(item))
        elif item_type == "spellcastingEntry":
            spellcasting.append(parse_spellcasting(item_name, item_system))
    
    # Afficher attaques
    if attacks:
        for atk in attacks:
            print(f"   {C.ORANGE}Corps-à-corps{C.RESET}" if atk['type'] == 'melee' else f"   {C.ORANGE}À distance{C.RESET}", end="")
            print(f" {format_actions(1)} {C.BOLD}{atk['name']}{C.RESET} {format_mod(atk['bonus'])}", end="")
            if atk['traits']:
                print(f" ({', '.join(atk['traits'])})", end="")
            print()
            if atk['damage']:
                print(f"      {C.GREEN}Dégâts{C.RESET} {atk['damage']}")
    
    # Afficher capacités passives
    if passives:
        print()
        for p in passives:
            print(f"   {C.CYAN}{C.BOLD}{p['name']}{C.RESET}", end="")
            if p['actions']:
                print(f" {format_actions(p['actions'])}", end="")
            if p['traits']:
                print(f" ({', '.join(p['traits'])})")
            else:
                print()
            if p['description']:
                desc = clean_html(p['description'])
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                wrapped = textwrap.fill(desc, width=w-6, initial_indent="      ", subsequent_indent="      ")
                print(f"{C.DIM}{wrapped}{C.RESET}")
    
    # Afficher actions offensives
    if actions_list:
        print()
        for a in actions_list:
            print(f"   {C.YELLOW}{C.BOLD}{a['name']}{C.RESET}", end="")
            if a['actions']:
                print(f" {format_actions(a['actions'])}", end="")
            if a['traits']:
                print(f" ({', '.join(a['traits'])})")
            else:
                print()
            if a['trigger']:
                print(f"      {C.GREEN}Déclencheur{C.RESET} {clean_html(a['trigger'])}")
            if a['requirements']:
                print(f"      {C.GREEN}Conditions{C.RESET} {clean_html(a['requirements'])}")
            if a['description']:
                desc = clean_html(a['description'])
                wrapped = textwrap.fill(desc, width=w-6, initial_indent="      ", subsequent_indent="      ")
                print(f"{wrapped}")

def parse_attack(item: dict, atk_type: str) -> dict:
    """Parse une attaque."""
    system = item.get("system", {})
    bonus = system.get("bonus", {}).get("value", 0)
    
    # Nom FR si disponible
    name = item.get("name_fr") or item.get("name", "")
    
    # Traits avec traduction basique
    traits = []
    trait_map = {
        "unarmed": "mains nues", "finesse": "finesse", "agile": "agile",
        "reach": "allonge", "thrown": "lancer", "deadly": "mortel",
        "fatal": "fatal", "forceful": "percutant", "sweep": "balayage",
        "trip": "croc-en-jambe", "shove": "bousculade", "grapple": "lutte",
        "knockdown": "renversement", "backstabber": "perfide",
    }
    for t in system.get("traits", {}).get("value", []):
        traits.append(trait_map.get(t.lower(), t))
    
    # Dégâts avec traduction des types
    damage_rolls = system.get("damageRolls", {})
    dmg_parts = []
    dmg_type_map = {
        "piercing": "perforant", "slashing": "tranchant", "bludgeoning": "contondant",
        "fire": "feu", "cold": "froid", "electricity": "électricité",
        "acid": "acide", "poison": "poison", "mental": "mental",
        "force": "force", "sonic": "son", "bleed": "saignement",
        "positive": "positif", "negative": "négatif", "spirit": "esprit",
        "vitality": "vitalité", "void": "néant",
    }
    for dmg in damage_rolls.values():
        if isinstance(dmg, dict):
            dice = dmg.get("damage", "")
            dtype = dmg.get("damageType", "")
            dtype_fr = dmg_type_map.get(dtype.lower(), dtype)
            if dice:
                dmg_parts.append(f"{dice} {dtype_fr}")
    
    return {
        "name": name,
        "type": atk_type,
        "bonus": bonus,
        "traits": traits,
        "damage": " plus ".join(dmg_parts)
    }

def parse_action(item: dict) -> dict:
    """Parse une action/capacité."""
    system = item.get("system", {})
    
    # Nom FR si disponible
    name = item.get("name_fr") or item.get("name", "")
    
    actions = system.get("actions", {}).get("value")
    
    # Traits avec traduction
    traits = []
    trait_map = {
        "concentrate": "concentration", "manipulate": "manipulation",
        "move": "mouvement", "attack": "attaque", "flourish": "épanouissement",
        "press": "pression", "rage": "rage", "stance": "posture",
        "visual": "visuel", "auditory": "auditif", "mental": "mental",
        "emotion": "émotion", "fear": "peur", "linguistic": "linguistique",
        "incapacitation": "mise hors combat", "death": "mort",
    }
    for t in system.get("traits", {}).get("value", []):
        traits.append(trait_map.get(t.lower(), t))
    
    # Description FR si disponible
    desc = item.get("description_fr") or ""
    if not desc:
        desc_data = system.get("description", {})
        if isinstance(desc_data, dict):
            desc = desc_data.get("value", "")
        else:
            desc = str(desc_data) if desc_data else ""
    
    return {
        "name": name,
        "actions": actions,
        "traits": traits,
        "description": desc,
        "trigger": system.get("trigger", {}).get("value", ""),
        "requirements": system.get("requirements", ""),
    }

def parse_spellcasting(name: str, system: dict) -> dict:
    """Parse une entrée d'incantation."""
    return {
        "name": name,
        "tradition": system.get("tradition", {}).get("value", ""),
        "spelldc": system.get("spelldc", {}).get("dc", ""),
        "attack": system.get("spelldc", {}).get("value", ""),
    }

def display_spell_full(system: dict, w: int):
    """Stats complètes d'un sort."""
    # Niveau
    level = system.get("level", {}).get("value", "?")
    print(f"   {C.GREEN}Niveau{C.RESET} {level}")
    
    # Traditions
    traditions = system.get("traditions", {}).get("value", [])
    if traditions:
        print(f"   {C.GREEN}Traditions{C.RESET} {', '.join(traditions)}")
    
    # Traits
    traits = system.get("traits", {}).get("value", [])
    if traits:
        print(f"   {C.GREEN}Traits{C.RESET} {', '.join(traits)}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # Incantation
    time = system.get("time", {}).get("value")
    if time:
        print(f"   {C.GREEN}Incantation{C.RESET} {format_actions(time)}")
    
    # Composantes
    components = system.get("components", {})
    if components:
        comp_list = [k for k, v in components.items() if v and k != "value"]
        if comp_list:
            print(f"   {C.GREEN}Composantes{C.RESET} {', '.join(comp_list)}")
    
    # Portée, zone, cibles
    range_val = system.get("range", {}).get("value", "")
    if range_val:
        print(f"   {C.GREEN}Portée{C.RESET} {range_val}")
    
    area = system.get("area", {})
    if area and area.get("value"):
        print(f"   {C.GREEN}Zone{C.RESET} {area.get('type', '')} de {area.get('value', '')} m")
    
    targets = system.get("target", {}).get("value", "")
    if targets:
        print(f"   {C.GREEN}Cibles{C.RESET} {targets}")
    
    # Jet de sauvegarde
    save = system.get("defense", {})
    if save:
        if save.get("save"):
            save_type = save["save"].get("statistic", "")
            basic = "basique" if save["save"].get("basic") else ""
            print(f"   {C.GREEN}Jet de sauvegarde{C.RESET} {save_type} {basic}")
    
    # Durée
    duration = system.get("duration", {}).get("value", "")
    if duration:
        print(f"   {C.GREEN}Durée{C.RESET} {duration}")
    
    # Note: Description déjà affichée par display_full()

def display_feat_full(system: dict, w: int):
    """Stats complètes d'un don."""
    # Niveau
    level = system.get("level", {}).get("value", "?")
    print(f"   {C.GREEN}Niveau{C.RESET} {level}")
    
    # Actions
    actions = system.get("actions", {}).get("value")
    if actions:
        print(f"   {C.GREEN}Actions{C.RESET} {format_actions(actions)}")
    
    # Traits
    traits = system.get("traits", {}).get("value", [])
    if traits:
        print(f"   {C.GREEN}Traits{C.RESET} {', '.join(traits)}")
    
    # Prérequis
    prereqs = system.get("prerequisites", {}).get("value", [])
    if prereqs:
        pstrs = [p.get("value", str(p)) if isinstance(p, dict) else str(p) for p in prereqs]
        print(f"   {C.GREEN}Prérequis{C.RESET} {'; '.join(pstrs)}")
    
    # Trigger/Requirements
    trigger = system.get("trigger", {}).get("value", "")
    if trigger:
        print(f"   {C.GREEN}Déclencheur{C.RESET} {trigger}")
    
    requirements = system.get("requirements", "")
    if requirements:
        print(f"   {C.GREEN}Conditions{C.RESET} {requirements}")
    
    # Note: Description déjà affichée par display_full()

def display_equipment_full(system: dict, w: int):
    """Stats équipement."""
    # Prix
    price = system.get("price", {}).get("value", {})
    if isinstance(price, dict):
        parts = [f"{v} {k}" for k, v in price.items() if v]
        if parts:
            print(f"   {C.GREEN}Prix{C.RESET} {', '.join(parts)}")
    
    # Niveau
    level = system.get("level", {}).get("value")
    if level:
        print(f"   {C.GREEN}Niveau{C.RESET} {level}")
    
    # Encombrement
    bulk = system.get("bulk", {}).get("value", "")
    if bulk:
        print(f"   {C.GREEN}Encombrement{C.RESET} {bulk}")
    
    # Traits
    traits = system.get("traits", {}).get("value", [])
    if traits:
        print(f"   {C.GREEN}Traits{C.RESET} {', '.join(traits)}")
    
    # Dégâts (armes)
    damage = system.get("damage", {})
    if damage:
        dice = damage.get("dice", 1)
        die = damage.get("die", "")
        dtype = damage.get("damageType", "")
        if die:
            print(f"   {C.GREEN}Dégâts{C.RESET} {dice}{die} {dtype}")
    
    # Groupe, catégorie (armes)
    group = system.get("group", "")
    if group:
        print(f"   {C.GREEN}Groupe{C.RESET} {group}")
    
    category = system.get("category", "")
    if category:
        print(f"   {C.GREEN}Catégorie{C.RESET} {category}")
    
    # CA (armures)
    ac_bonus = system.get("acBonus", 0)
    if ac_bonus:
        print(f"   {C.GREEN}Bonus CA{C.RESET} +{ac_bonus}")
    
    dex_cap = system.get("dexCap", 0)
    if dex_cap:
        print(f"   {C.GREEN}Cap. Dex{C.RESET} +{dex_cap}")
    
    check_penalty = system.get("checkPenalty", 0)
    if check_penalty:
        print(f"   {C.GREEN}Malus test{C.RESET} {check_penalty}")
    
    speed_penalty = system.get("speedPenalty", 0)
    if speed_penalty:
        print(f"   {C.GREEN}Malus vitesse{C.RESET} {speed_penalty}")
    
    # Note: Description déjà affichée par display_full()

def display_action_full(system: dict, w: int):
    """Stats action."""
    actions = system.get("actions", {}).get("value")
    if actions:
        print(f"   {C.GREEN}Actions{C.RESET} {format_actions(actions)}")
    
    traits = system.get("traits", {}).get("value", [])
    if traits:
        print(f"   {C.GREEN}Traits{C.RESET} {', '.join(traits)}")
    
    trigger = system.get("trigger", {}).get("value", "")
    if trigger:
        print(f"   {C.GREEN}Déclencheur{C.RESET} {trigger}")
    
    requirements = system.get("requirements", "")
    if requirements:
        print(f"   {C.GREEN}Conditions{C.RESET} {requirements}")
    
    # Note: Description déjà affichée par display_full()

def display_class_full(system: dict, items: list, w: int):
    """Stats complètes d'une classe."""
    
    # Traductions
    ability_names = {"str": "Force", "dex": "Dextérité", "con": "Constitution", 
                     "int": "Intelligence", "wis": "Sagesse", "cha": "Charisme"}
    proficiency_names = {0: "Non formé", 1: "Formé", 2: "Expert", 3: "Maître", 4: "Légendaire"}
    
    # === STATS DE BASE ===
    hp = system.get("hp", 0)
    print(f"   {C.GREEN}Points de vie{C.RESET} {hp} + modificateur de Constitution par niveau")
    
    # Caractéristique clé
    key_abilities = system.get("keyAbility", {}).get("value", [])
    if key_abilities:
        key_names = [ability_names.get(a, a.upper()) for a in key_abilities]
        print(f"   {C.GREEN}Caractéristique clé{C.RESET} {' ou '.join(key_names)}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # === MAÎTRISES INITIALES ===
    print(f"   {C.BOLD}Maîtrises initiales{C.RESET}")
    
    # Perception
    perception = system.get("perception", 0)
    print(f"   {C.GREEN}Perception{C.RESET} {proficiency_names.get(perception, '?')}")
    
    # Sauvegardes
    saves = system.get("savingThrows", {})
    save_strs = []
    save_names = {"fortitude": "Vigueur", "reflex": "Réflexes", "will": "Volonté"}
    for key, name in save_names.items():
        rank = saves.get(key, 0)
        save_strs.append(f"{name} ({proficiency_names.get(rank, '?')})")
    print(f"   {C.GREEN}Jets de sauvegarde{C.RESET} {', '.join(save_strs)}")
    
    # Compétences
    trained_skills = system.get("trainedSkills", {})
    skill_list = trained_skills.get("value", [])
    additional = trained_skills.get("additional", 0)
    skill_names_map = {
        "acrobatics": "Acrobaties", "arcana": "Arcanes", "athletics": "Athlétisme",
        "crafting": "Artisanat", "deception": "Duperie", "diplomacy": "Diplomatie",
        "intimidation": "Intimidation", "medicine": "Médecine", "nature": "Nature",
        "occultism": "Occultisme", "performance": "Représentation", "religion": "Religion",
        "society": "Société", "stealth": "Discrétion", "survival": "Survie",
        "thievery": "Vol"
    }
    skill_strs = [skill_names_map.get(s, s.capitalize()) for s in skill_list]
    if additional:
        skill_strs.append(f"+{additional} au choix")
    print(f"   {C.GREEN}Compétences{C.RESET} {', '.join(skill_strs) if skill_strs else 'Aucune'}")
    
    # Attaques
    attacks = system.get("attacks", {})
    atk_strs = []
    atk_names = {"simple": "Simples", "martial": "Martiales", "advanced": "Avancées", "unarmed": "Sans arme"}
    for key, name in atk_names.items():
        rank = attacks.get(key, 0)
        if rank > 0:
            atk_strs.append(f"{name} ({proficiency_names.get(rank, '?')})")
    if atk_strs:
        print(f"   {C.GREEN}Attaques{C.RESET} {', '.join(atk_strs)}")
    
    # Défenses
    defenses = system.get("defenses", {})
    def_strs = []
    def_names = {"unarmored": "Sans armure", "light": "Légère", "medium": "Intermédiaire", "heavy": "Lourde"}
    for key, name in def_names.items():
        rank = defenses.get(key, 0)
        if rank > 0:
            def_strs.append(f"{name} ({proficiency_names.get(rank, '?')})")
    if def_strs:
        print(f"   {C.GREEN}Défenses{C.RESET} {', '.join(def_strs)}")
    
    # Incantation
    spellcasting = system.get("spellcasting", 0)
    if spellcasting:
        print(f"   {C.GREEN}Incantation{C.RESET} {proficiency_names.get(spellcasting, '?')}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # === PROGRESSION ===
    print(f"   {C.BOLD}Progression{C.RESET}")
    
    ancestry_feats = system.get("ancestryFeatLevels", {}).get("value", [])
    if ancestry_feats:
        print(f"   {C.GREEN}Dons d'ascendance{C.RESET} Niv. {', '.join(map(str, ancestry_feats))}")
    
    class_feats = system.get("classFeatLevels", {}).get("value", [])
    if class_feats:
        print(f"   {C.GREEN}Dons de classe{C.RESET} Niv. {', '.join(map(str, class_feats))}")
    
    general_feats = system.get("generalFeatLevels", {}).get("value", [])
    if general_feats:
        print(f"   {C.GREEN}Dons généraux{C.RESET} Niv. {', '.join(map(str, general_feats))}")
    
    skill_feats = system.get("skillFeatLevels", {}).get("value", [])
    if skill_feats:
        print(f"   {C.GREEN}Dons de compétence{C.RESET} Niv. {', '.join(map(str, skill_feats))}")
    
    skill_increases = system.get("skillIncreaseLevels", {}).get("value", [])
    if skill_increases:
        print(f"   {C.GREEN}Augm. compétences{C.RESET} Niv. {', '.join(map(str, skill_increases))}")
    
    print(f"{C.DIM}{'─' * w}{C.RESET}")
    
    # === CAPACITÉS DE CLASSE ===
    class_items = system.get("items", {})
    if class_items:
        print(f"   {C.BOLD}Capacités de classe{C.RESET}")
        
        # Trier par niveau
        sorted_items = sorted(class_items.values(), key=lambda x: x.get("level", 0))
        
        for item in sorted_items:
            level = item.get("level", "?")
            name = item.get("name", "?")
            print(f"   {C.YELLOW}Niv.{level:>2}{C.RESET} {name}")
    
    # Publication
    pub = system.get("publication", {})
    if pub:
        title = pub.get("title", "")
        if title:
            print(f"\n   {C.DIM}Source: {title}{C.RESET}")

# ============================================================================
# RECHERCHE
# ============================================================================

def search(query: str, conn: sqlite3.Connection, entry_type: str = None, 
           pack_filter: str = None, trait_filter: str = None, limit: int = 25) -> List[dict]:
    """Recherche et retourne des dictionnaires."""
    query_lower = query.lower().strip()
    query_normalized = normalize_text(query)
    cur = conn.cursor()
    
    results = []
    seen_keys = set()
    
    def add_results(sql: str, params: list, score: int):
        cur.execute(sql, params)
        for row in cur.fetchall():
            try:
                entry = json.loads(row[0])
                
                # Filtrer par trait si demandé
                if trait_filter:
                    traits = entry.get("system", {}).get("traits", {}).get("value", [])
                    if not any(trait_filter.lower() in t.lower() for t in traits):
                        continue
                
                key = f"{entry.get('_pack')}:{entry.get('_id')}"
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append((score, entry))
            except:
                pass
    
    def add_entry_if_match(entry: dict, score: int):
        """Ajoute une entrée si elle correspond à la recherche normalisée."""
        # Filtrer par trait si demandé
        if trait_filter:
            traits = entry.get("system", {}).get("traits", {}).get("value", [])
            if not any(trait_filter.lower() in t.lower() for t in traits):
                return
        
        # Filtrer par type
        if entry_type and entry.get("type") != entry_type:
            return
        
        # Filtrer par pack
        if pack_filter and pack_filter.lower() not in entry.get("_pack", "").lower():
            return
        
        key = f"{entry.get('_pack')}:{entry.get('_id')}"
        if key not in seen_keys:
            seen_keys.add(key)
            results.append((score, entry))
    
    # UUID exact
    if len(query) >= 8 and query.replace("-", "").isalnum():
        cur.execute("SELECT data FROM entries WHERE id = ?", (query,))
        row = cur.fetchone()
        if row:
            try:
                return [json.loads(row[0])]
            except:
                pass
    
    # Filtres
    type_clause = " AND type = ?" if entry_type else ""
    pack_clause = " AND pack LIKE ?" if pack_filter else ""
    
    def params_with_filters(base_params):
        p = list(base_params)
        if entry_type:
            p.append(entry_type)
        if pack_filter:
            p.append(f"%{pack_filter}%")
        return p
    
    # Recherches par ordre de priorité (SQL standard)
    queries = [
        (f"SELECT data FROM entries WHERE LOWER(name_fr) = ?{type_clause}{pack_clause}", 1000),
        (f"SELECT data FROM entries WHERE LOWER(name_en) = ?{type_clause}{pack_clause}", 950),
        (f"SELECT data FROM entries WHERE LOWER(name_fr) LIKE ?{type_clause}{pack_clause}", 500),
        (f"SELECT data FROM entries WHERE LOWER(name_en) LIKE ?{type_clause}{pack_clause}", 450),
    ]
    
    for sql, score in queries[:2]:
        add_results(sql, params_with_filters([query_lower]), score)
    
    for sql, score in queries[2:]:
        add_results(sql, params_with_filters([query_lower + '%']), score)
    
    # Contient
    add_results(
        f"SELECT data FROM entries WHERE LOWER(name_fr) LIKE ?{type_clause}{pack_clause}",
        params_with_filters(['%' + query_lower + '%']), 200
    )
    add_results(
        f"SELECT data FROM entries WHERE LOWER(name_en) LIKE ?{type_clause}{pack_clause}",
        params_with_filters(['%' + query_lower + '%']), 150
    )
    
    # Recherche normalisée (sans accents) - nécessaire car SQLite LOWER() gère mal les accents
    # Lance si peu de résultats OU si la requête contient des caractères accentués
    has_accents = query_normalized != query_lower
    if len(results) < 5 or has_accents:
        # Recherche avec texte normalisé (gère é/e, à/a, etc.)
        if entry_type:
            cur.execute("SELECT data FROM entries WHERE type = ?", (entry_type,))
        else:
            cur.execute("SELECT data FROM entries")
        
        for row in cur.fetchall():
            try:
                entry = json.loads(row[0])
                name_fr = entry.get("name_fr", "")
                name_en = entry.get("name_en", "")
                name_fr_norm = normalize_text(name_fr)
                name_en_norm = normalize_text(name_en)
                
                # Match exact normalisé
                if name_fr_norm == query_normalized:
                    add_entry_if_match(entry, 900)
                elif name_en_norm == query_normalized:
                    add_entry_if_match(entry, 850)
                # Commence par (normalisé)
                elif name_fr_norm.startswith(query_normalized):
                    add_entry_if_match(entry, 400)
                elif name_en_norm.startswith(query_normalized):
                    add_entry_if_match(entry, 350)
                # Contient (normalisé)
                elif query_normalized in name_fr_norm:
                    add_entry_if_match(entry, 100)
                elif query_normalized in name_en_norm:
                    add_entry_if_match(entry, 50)
            except:
                pass
    
    results.sort(key=lambda x: (-x[0], x[1].get("name_fr", "").lower()))
    return [r[1] for r in results[:limit]]


def list_by_trait(conn: sqlite3.Connection, trait: str, entry_type: str = None, limit: int = 50) -> List[dict]:
    """Liste toutes les entrées avec un trait donné."""
    cur = conn.cursor()
    
    # Récupérer toutes les entrées et filtrer par trait
    if entry_type:
        cur.execute("SELECT data FROM entries WHERE type = ?", (entry_type,))
    else:
        cur.execute("SELECT data FROM entries")
    
    results = []
    trait_lower = trait.lower()
    
    for row in cur.fetchall():
        try:
            entry = json.loads(row[0])
            traits = entry.get("system", {}).get("traits", {}).get("value", [])
            
            # Vérifier si le trait est présent
            if any(trait_lower in t.lower() for t in traits):
                level = entry.get("system", {}).get("level", {})
                if isinstance(level, dict):
                    level = level.get("value", 0)
                results.append((level or 0, entry))
        except:
            pass
    
    # Trier par niveau puis par nom
    results.sort(key=lambda x: (x[0], x[1].get("name_fr", "").lower()))
    return [r[1] for r in results[:limit]]


# ============================================================================
# MODE INTERACTIF
# ============================================================================

TYPE_SHORTCUTS = {
    "créature:": "créature", "creature:": "créature", "monstre:": "créature",
    "npc:": "créature", "pnj:": "créature",
    "sort:": "sort", "spell:": "sort",
    "don:": "don", "feat:": "don",
    "équipement:": "équipement", "equip:": "équipement", "objet:": "équipement",
    "arme:": "arme", "weapon:": "arme",
    "armure:": "armure", "armor:": "armure",
    "action:": "action",
    "danger:": "danger", "hazard:": "danger",
    "état:": "état", "condition:": "état",
    "classe:": "classe", "class:": "classe",
    "compagnon:": "compagnon", "companion:": "compagnon",
    "règle:": "règle", "regle:": "règle", "rule:": "règle",
    "traitdef:": "trait", "définition:": "trait",  # Pour chercher la définition d'un trait
    "capacité:": "capacité", "ability:": "capacité", "npca:": "capacité",  # Capacités NPC
    "matériau:": "matériau", "materiau:": "matériau", "material:": "matériau",  # Matériaux précieux
    "glossaire:": "glossaire", "gloss:": "glossaire", "ref:": "glossaire",  # Glossaire général
}

def interactive(conn: sqlite3.Connection):
    """Mode interactif."""
    print(f"\n{C.BOLD}🔍 PF2e Search v5{C.RESET}")
    print(f"{C.DIM}   Commandes: q=quitter, stats, types, packs, traits")
    print(f"   <num>=détails, full <num>=complet")
    print(f"   Filtres: créature: sort: pack:bestiary trait:magus")
    print(f"   Nouveaux: capacité: matériau: traitdef:{C.RESET}")
    print()
    
    last_results = []
    
    while True:
        try:
            user_input = input(f"{C.CYAN}pf2>{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C.GREEN}👋 Bye!{C.RESET}")
            break
        
        if not user_input:
            continue
        
        if user_input.lower() == 'q':
            print(f"{C.GREEN}👋 Bye!{C.RESET}")
            break
        
        if user_input.lower() == 'stats':
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM entries")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM entries WHERE translated = 1")
            trans = cur.fetchone()[0]
            print(f"\n{C.BOLD}📊 {total} entrées, {trans} traduites{C.RESET}")
            continue
        
        if user_input.lower() == 'types':
            cur = conn.cursor()
            cur.execute("SELECT type, COUNT(*) FROM entries GROUP BY type ORDER BY COUNT(*) DESC")
            print(f"\n{C.BOLD}📋 Types:{C.RESET}")
            for row in cur.fetchall():
                print(f"   • {row[0]} ({row[1]})")
            continue
        
        if user_input.lower() == 'packs':
            cur = conn.cursor()
            cur.execute("SELECT pack, COUNT(*) FROM entries GROUP BY pack ORDER BY COUNT(*) DESC")
            print(f"\n{C.BOLD}📦 Packs:{C.RESET}")
            for row in cur.fetchall()[:25]:
                print(f"   • {row[0]} ({row[1]})")
            continue
        
        if user_input.lower() == 'traits':
            # Lister les traits les plus courants
            cur = conn.cursor()
            cur.execute("SELECT data FROM entries")
            trait_counts = defaultdict(int)
            for row in cur.fetchall():
                try:
                    data = json.loads(row[0])
                    traits = data.get("system", {}).get("traits", {}).get("value", [])
                    for t in traits:
                        trait_counts[t] += 1
                except:
                    pass
            print(f"\n{C.BOLD}🏷️ Traits (top 30):{C.RESET}")
            for trait, count in sorted(trait_counts.items(), key=lambda x: -x[1])[:30]:
                print(f"   • {trait} ({count})")
            continue
        
        # Numéro seul -> détails compacts
        if user_input.isdigit():
            idx = int(user_input)
            if 1 <= idx <= len(last_results):
                display_full(last_results[idx - 1])
            else:
                print(f"{C.RED}Numéro invalide (1-{len(last_results)}){C.RESET}")
            continue
        
        # "full N" -> détails complets
        if user_input.lower().startswith("full "):
            rest = user_input[5:].strip()
            if rest.isdigit():
                idx = int(rest)
                if 1 <= idx <= len(last_results):
                    display_full(last_results[idx - 1])
                else:
                    print(f"{C.RED}Numéro invalide (1-{len(last_results)}){C.RESET}")
            continue
        
        # Recherche
        entry_type = None
        pack_filter = None
        trait_filter = None
        query = user_input
        
        # Type filter
        for prefix, t in TYPE_SHORTCUTS.items():
            if query.lower().startswith(prefix):
                entry_type = t
                query = query[len(prefix):].strip()
                break
        
        # Pack filter
        if query.lower().startswith("pack:"):
            rest = query[5:].strip()
            parts = rest.split(None, 1)
            if parts:
                pack_filter = parts[0]
                query = parts[1] if len(parts) > 1 else ""
        
        # Trait filter
        if query.lower().startswith("trait:"):
            rest = query[6:].strip()
            parts = rest.split(None, 1)
            if parts:
                trait_filter = parts[0]
                query = parts[1] if len(parts) > 1 else ""
        
        # Si seulement trait: sans query, lister tout avec ce trait
        if trait_filter and not query:
            results = list_by_trait(conn, trait_filter, entry_type, limit=50)
            last_results = results
            
            if not results:
                print(f"{C.YELLOW}Aucun résultat avec le trait '{trait_filter}'{C.RESET}")
                continue
            
            filters = [f"trait:{trait_filter}"]
            if entry_type:
                filters.append(f"type:{entry_type}")
            filter_str = f" ({', '.join(filters)})"
            
            print(f"\n{C.GREEN}✨ {len(results)} résultat(s){filter_str}:{C.RESET}")
            
            for i, entry in enumerate(results, 1):
                display_compact(entry, i)
            
            print(f"\n{C.DIM}Tapez un numéro pour les détails complets{C.RESET}")
            continue
        
        if not query:
            print(f"{C.YELLOW}Entrez un terme de recherche{C.RESET}")
            continue
        
        results = search(query, conn, entry_type, pack_filter, trait_filter)
        last_results = results
        
        if not results:
            print(f"{C.YELLOW}Aucun résultat pour '{query}'{C.RESET}")
            continue
        
        filters = []
        if entry_type:
            filters.append(f"type:{entry_type}")
        if pack_filter:
            filters.append(f"pack:{pack_filter}")
        if trait_filter:
            filters.append(f"trait:{trait_filter}")
        filter_str = f" ({', '.join(filters)})" if filters else ""
        
        print(f"\n{C.GREEN}✨ {len(results)} résultat(s) pour '{query}'{filter_str}:{C.RESET}")
        
        for i, entry in enumerate(results, 1):
            display_compact(entry, i)
        
        print(f"\n{C.DIM}Tapez un numéro pour les détails complets{C.RESET}")

# ============================================================================
# MAIN
# ============================================================================

def main():
    print(f"\n{C.BOLD}{'═' * 55}")
    print("🎲 PF2e Search v5 - COMPLET")
    print(f"{'═' * 55}{C.RESET}")
    
    if not DB_FILE.exists():
        print(f"\n{C.RED}Base non trouvée: {DB_FILE}{C.RESET}")
        print(f"Lancez: python pf2_extract_v5.py")
        return
    
    conn = sqlite3.connect(str(DB_FILE))
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM entries")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM entries WHERE translated = 1")
    trans = cur.fetchone()[0]
    
    print(f"\n{C.GREEN}✓ {total} entrées ({trans} traduites){C.RESET}")
    
    args = sys.argv[1:]
    
    if args:
        # Mode CLI
        entry_type = None
        pack_filter = None
        query_parts = []
        full_mode = "--full" in args or "-f" in args
        
        i = 0
        while i < len(args):
            if args[i] == "--type" and i + 1 < len(args):
                entry_type = args[i + 1]
                i += 2
            elif args[i] == "--pack" and i + 1 < len(args):
                pack_filter = args[i + 1]
                i += 2
            elif args[i] in ["--full", "-f"]:
                i += 1
            else:
                query_parts.append(args[i])
                i += 1
        
        query = " ".join(query_parts)
        
        # Shortcuts
        for prefix, t in TYPE_SHORTCUTS.items():
            if query.lower().startswith(prefix):
                entry_type = t
                query = query[len(prefix):].strip()
                break
        
        if query.lower().startswith("pack:"):
            rest = query[5:].strip()
            parts = rest.split(None, 1)
            if parts:
                pack_filter = parts[0]
                query = parts[1] if len(parts) > 1 else ""
        
        if query:
            results = search(query, conn, entry_type, pack_filter)
            if results:
                print(f"\n{C.GREEN}✨ {len(results)} résultat(s):{C.RESET}")
                if full_mode:
                    for e in results:
                        display_full(e)
                else:
                    for i, e in enumerate(results, 1):
                        display_compact(e, i)
            else:
                print(f"{C.YELLOW}Aucun résultat pour '{query}'{C.RESET}")
        
        conn.close()
    else:
        interactive(conn)
        conn.close()

if __name__ == "__main__":
    main()
