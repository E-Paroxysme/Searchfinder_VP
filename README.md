# 🎲 PF2e Search - Base de données Pathfinder 2e en français

Outil d'extraction et de recherche pour le contenu Pathfinder 2e, combinant les données Foundry VTT (pf2e) avec les traductions françaises (pf2-fr).

## ✨ Fonctionnalités

- **Recherche rapide** dans +28 000 entrées (créatures, sorts, dons, objets, etc.)
- **Traductions françaises** intégrées depuis le module pf2-fr
- **Recherche insensible aux accents** ("epee" trouve "épée")
- **Filtres avancés** par type, pack, trait, tradition magique
- **Affichage détaillé** avec stats complètes selon le type d'entrée
- **Glossaire complet** : traits, capacités NPC, états, matériaux précieux

## 📁 Structure du projet

```
pf2_data/
├── raw/
│   ├── pf2e/              # Données Foundry VTT (source)
│   │   ├── packs/pf2e/    # Fichiers JSON par pack
│   │   └── static/lang/   # Fichier en.json
│   └── pf2-fr/            # Traductions françaises
│       ├── data/          # Fichiers .htm traduits
│       └── lang/          # Fichier fr.json
├── pf2_compendium.db      # Base SQLite générée
├── pf2_extract_v6.py      # Script d'extraction
└── pf2_search_v5.py       # Script de recherche
```

## 🚀 Installation

### Prérequis

- Python 3.8+
- Modules Python : `sqlite3` (inclus), `json`, `pathlib`

### Sources de données

1. **pf2e** (Foundry VTT) :
   ```bash
   git clone https://github.com/foundryvtt/pf2e.git pf2_data/raw/pf2e
   ```

2. **pf2-fr** (Traductions) :
   ```bash
   git clone https://gitlab.com/music-music-music/foundryvtt-babele-translation-files-pf2.git pf2_data/raw/pf2-fr
   ```

### Extraction

```bash
# Extraire et créer la base de données
python pf2_extract_v6.py --local

# Options disponibles
python pf2_extract_v6.py --help
```

## 🔍 Utilisation

### Lancer la recherche interactive

```bash
python pf2_search_v5.py
```

### Commandes de base

| Commande | Description |
|----------|-------------|
| `q` ou `quit` | Quitter |
| `stats` | Afficher les statistiques de la base |
| `types` | Lister les types disponibles |
| `packs` | Lister les packs disponibles |
| `traits` | Lister les traits les plus courants |
| `<numéro>` | Afficher les détails d'un résultat |

### Exemples de recherche

```bash
pf2> gobelin                    # Recherche simple
pf2> créature: dragon           # Filtrer par type
pf2> sort: boule de feu         # Chercher un sort
pf2> don: attaque en puissance  # Chercher un don
pf2> pack:bestiary dragon       # Filtrer par pack
pf2> trait: fire                # Filtrer par trait
pf2> tradition: arcane          # Sorts d'une tradition
```

### Filtres par type

| Raccourci | Type |
|-----------|------|
| `créature:` `monstre:` `pnj:` | Créatures |
| `sort:` `spell:` | Sorts |
| `don:` `feat:` | Dons |
| `équipement:` `objet:` | Équipement |
| `arme:` `weapon:` | Armes |
| `armure:` `armor:` | Armures |
| `action:` | Actions |
| `danger:` `hazard:` | Dangers |
| `état:` `condition:` | États/Conditions |
| `classe:` `class:` | Classes |
| `règle:` `rule:` | Règles |

### Filtres spéciaux

| Raccourci | Description |
|-----------|-------------|
| `traitdef:` `définition:` | Définitions de traits |
| `capacité:` `ability:` | Capacités NPC (Grab, Constrict...) |
| `matériau:` `material:` | Matériaux précieux |
| `glossaire:` `gloss:` | Glossaire général |
| `tradition:` `trad:` | Filtrer sorts par tradition |

### Traditions magiques

```bash
pf2> tradition: arcane      # ou trad: arc
pf2> tradition: divine      # ou trad: div
pf2> tradition: occulte     # ou trad: occ
pf2> tradition: primordial  # ou trad: pri
```

## 📊 Contenu extrait

### Types principaux

| Type | Description | Exemple |
|------|-------------|---------|
| `créature` | Monstres et PNJ | Gobelin, Dragon rouge |
| `sort` | Sorts et rituels | Boule de feu, Guérison |
| `don` | Dons et capacités | Attaque en puissance |
| `action` | Actions de jeu | Chercher, Se cacher |
| `équipement` | Objets divers | Corde, Lanterne |
| `arme` | Armes | Épée longue, Arc long |
| `armure` | Armures et boucliers | Cotte de mailles |
| `consommable` | Objets à usage unique | Potions, Parchemins |
| `danger` | Pièges et dangers | Fosse à pieux |
| `classe` | Classes de personnage | Guerrier, Magicien |
| `ascendance` | Ascendances | Elfe, Nain, Humain |
| `archétype` | Archétypes | Duelliste, Archer |

### Glossaire et références

| Type | Contenu |
|------|---------|
| `trait` | ~300 définitions de traits (Fire, Polymorph, Agile...) |
| `capacité` | ~53 capacités NPC (Agrippement, Constriction, Engloutissement...) |
| `état` | ~46 états (Aveuglé, Effrayé, Agrippé...) |
| `matériau` | ~20 matériaux précieux avec descriptions |
| `glossaire` | ~200 termes de référence (tailles, compétences, traditions...) |

## 🎯 Affichage des résultats

### Vue liste (compact)

```
 1. GOBELIN PYROMANE  (Goblin Pyro)
   [créature] Niv.1 ← pf2e-av1-bestiary #abc12345
   [peu-commun] [feu] [gobelinoïde]
   Ce gobelin adore mettre le feu à tout ce qu'il trouve...
```

### Vue détaillée (créature)

```
══════════════════════════════════════════════════════════════
 GOBELIN PYROMANE  Créature 1
   (Goblin Pyro)
   [peu-commun] [feu] [gobelinoïde]
──────────────────────────────────────────────────────────────
   Description complète...

   Taille Petite (P)
   Perception +5 (vision dans le noir)
   Langues commun, gobelin
   Compétences Acrobaties +7, Discrétion +7

   FOR +1 | DEX +3 | CON +1 | INT +0 | SAG +1 | CHA +2

   CA 16 | Vig +4 | Réf +8 | Vol +4
   PV 15

   Vitesse 7,5 m
══════════════════════════════════════════════════════════════
```

### Vue détaillée (sort)

```
══════════════════════════════════════════════════════════════
 BOULE DE FEU  Sort 3
   (Fireball)
   [evocation] [fire]
──────────────────────────────────────────────────────────────
   Description...

   Niveau 3
   Traditions Arcanique, Primordial
   Traits evocation, fire
──────────────────────────────────────────────────────────────
   Incantation ◆◆
   Composantes somatic, verbal
   Portée 500 feet
   Zone explosion de 6 m
   Jet de sauvegarde reflex basique
══════════════════════════════════════════════════════════════
```

## 🔧 Configuration

### Variables d'environnement

Les chemins peuvent être modifiés dans les scripts :

```python
# pf2_extract_v6.py
RAW_DIR = Path("pf2_data/raw")
DATA_DIR = Path("pf2_data")
DB_FILE = DATA_DIR / "pf2_compendium.db"
```

### Base de données

La base SQLite contient une table `entries` avec :

| Colonne | Type | Description |
|---------|------|-------------|
| `id` | TEXT | UUID unique |
| `name_fr` | TEXT | Nom français |
| `name_en` | TEXT | Nom anglais |
| `name_normalized` | TEXT | Nom sans accents (recherche) |
| `type` | TEXT | Type d'entrée |
| `pack` | TEXT | Pack source |
| `data` | TEXT | JSON complet |

## 📝 Notes techniques

### Recherche insensible aux accents

La recherche normalise automatiquement les accents :
- `épée` → `epee`
- `créature` → `creature`
- `guérison` → `guerison`

### Sources de traduction

1. **Fichiers .htm** : Traductions complètes dans `pf2-fr/data/{pack}/{uuid}.htm`
2. **Fichiers .json** : Noms et descriptions dans `pf2-fr/lang/fr.json`
3. **Journals** : Descriptions de classes/règles dans les journaux traduits

### Priorité des traductions

1. Traduction .htm (si disponible)
2. Traduction .json (fallback)
3. Texte anglais original (si non traduit)

## 🐛 Dépannage

### "Base non trouvée"

```bash
# Vérifier que l'extraction a été effectuée
python pf2_extract_v6.py --local
```

### "Aucun résultat"

- Vérifier l'orthographe (la recherche est tolérante aux accents)
- Essayer une recherche plus large
- Vérifier le type avec `types`

### Traditions non affichées

Les traditions dépendent de la structure des données sources. Si `system.traditions.value` n'existe pas dans les fichiers JSON, les traditions ne seront pas extraites.

## 📜 Licence

Ce projet utilise des données sous licence OGL (Open Game License) de Paizo Inc. et les traductions communautaires du projet pf2-fr.

## 🙏 Crédits

- **Foundry VTT PF2e** : Système de jeu et données
- **pf2-fr** : Traductions françaises communautaires
- **Paizo Inc.** : Pathfinder Second Edition

---

*Dernière mise à jour : Janvier 2025*
