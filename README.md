# IDFM Prochain Départ

Intégration Home Assistant (HACS) qui calcule **à quelle heure partir de chez vous** pour
attraper le prochain passage d'un arrêt d'Île-de-France Mobilités :

`heure de départ = passage à l'arrêt − temps de marche − marge`

## Installation (HACS, dépôt personnalisé)

1. HACS → menu ⋮ → *Dépôts personnalisés* → ajoutez l'URL de ce dépôt, catégorie *Intégration*.
2. Installez « IDFM Prochain Départ », redémarrez Home Assistant.
3. *Paramètres → Appareils et services → Ajouter une intégration → IDFM Prochain Départ*.

## Obtenir une clé PRIM

1. Créez un compte sur <https://prim.iledefrance-mobilites.fr>.
2. Dans *Mon espace → Mes jetons d'authentification*, générez un jeton : c'est votre clé API.
3. Dans le catalogue, souscrivez (gratuitement) aux deux APIs :
   - **Prochains passages** (stop-monitoring, SIRI) ;
   - **Navitia** (recherche de lieux, itinéraires, temps de marche).

Sans ces deux souscriptions, la clé sera refusée (`invalid_auth`) ou certaines recherches échoueront.

## Quota

Le quota gratuit est d'environ **1000 requêtes par jour et par clé**. Les entrées d'une même clé
s'additionnent (le total n'est pas bloqué, seulement rapporté dans l'attribut `api_usage`).

| Usage | Requêtes / jour |
|---|---|
| Mode arrêt, SIRI toutes les 120 s de 05:30 à 01:00 | ~585 |
| Mode trajet : Navitia toutes les 10 min en plus | ~117 |
| Temps de marche et lignes de l'arrêt (1 fois par jour) | ~2 |

Conseil : gardez 120 s ou plus, limitez la plage d'activité, et n'ajoutez pas trop d'entrées avec la même clé.
En dehors de la plage d'activité aucune requête n'est émise.

## Configuration

1. **Clé API et domicile** : entité `zone.home` par défaut, ou latitude/longitude manuelles
   (elles priment sur l'entité). Les coordonnées sont préremplies avec l'emplacement de la maison Home
   Assistant ; modifiables ensuite via « Configurer » (case « Reprendre l'emplacement de la maison Home
   Assistant » pour les réinitialiser).
2. **Choix du mode** :
   - *Un arrêt* : recherchez le nom, choisissez l'arrêt, puis (optionnel) une ligne et un filtre de
     direction (texte, insensible à la casse et aux accents).
   - *Une destination* : recherchez un lieu ; l'intégration calcule le trajet depuis le domicile et
     affine le premier passage en transport avec les horaires temps réel.
3. **Options** (roue dentée de l'entrée) : marge (défaut 3 min), temps de marche forcé (vide =
   automatique), intervalle de rafraîchissement (60–3600 s), rafraîchissement du trajet (défaut 10 min),
   plage d'activité (05:30 → 01:00), nombre de départs (défaut 3).
4. **Station de destination (optionnelle)** : en mode « Un arrêt », vous pouvez indiquer une station de
   destination ; seuls les passages desservant cette station sont conservés, et l'heure d'arrivée
   (`arrival_at`, `destination_name`) est exposée dans les attributs du capteur `leave_at` et affichée
   par la carte. Si le filtre ne peut pas être appliqué, `destination_filter_active` vaut `false`.

## Entités

| Entité | Description |
|---|---|
| `sensor.…_leave_at` | Heure à laquelle partir (horodatage), attribut `departures` |
| `sensor.…_minutes_until_leave` | Minutes restantes avant de partir |
| `sensor.…_departure_at_stop` | Heure de passage à l'arrêt (`realtime`, `source`) |
| `sensor.…_line` | Ligne du prochain passage (`mode`, `direction`) |
| `sensor.…_walk_time` | Temps de marche en minutes (`source` : auto/manual) |
| `binary_sensor.…_time_to_leave` | Actif quand il reste 0 à 1 minute avant de partir |

## Service

`idfm_departure.refresh` : force un rafraîchissement immédiat (même hors plage d'activité).
Paramètre optionnel `entry_id` ; sans lui, toutes les entrées chargées sont rafraîchies.

## Exemple d'automatisation

```yaml
automation:
  - alias: "Il est l'heure de partir"
    trigger:
      - platform: state
        entity_id: binary_sensor.chatelet_time_to_leave
        to: "on"
    action:
      - service: notify.mobile_app_mon_telephone
        data:
          title: "Il est temps de partir"
          message: >
            Ligne {{ states('sensor.chatelet_line') }} à
            {{ as_timestamp(states('sensor.chatelet_departure_at_stop')) | timestamp_custom('%H:%M') }}
```

## Exemple Lovelace

```yaml
type: entities
title: Prochain départ
entities:
  - entity: sensor.chatelet_minutes_until_leave
  - entity: sensor.chatelet_leave_at
  - entity: sensor.chatelet_line
  - entity: sensor.chatelet_walk_time
  - entity: binary_sensor.chatelet_time_to_leave
```

Les identifiants d'entités dépendent du titre de l'entrée ; adaptez-les.

## Carte Lovelace

L'intégration fournit une carte personnalisée `idfm-departure-card` : pastille de ligne, arrêt, heure,
gros compteur « Partir dans N min », mode et heure de départ, et météo optionnelle. Les minutes sont
recalculées côté navigateur toutes les 10 secondes.

Si une station de destination est configurée, la ligne du bas devient « Métro à 15:30 → La Défense 15:52 ».
Sur une carte étroite, l'arrivée passe sur une ligne séparée (« Arrivée à La Défense : 15:52 »). Si le
filtre de destination n'a pas pu être appliqué (`destination_filter_active: false`), un petit symbole ⚠
« filtre destination indisponible » s'affiche.

La carte est chargée automatiquement par l'intégration (servie sur
`/idfm_departure_static/idfm-departure-card.js`). Si elle n'apparaît pas dans le sélecteur de cartes,
ajoutez-la manuellement comme ressource JavaScript (module) : *Paramètres > Tableaux de bord >
Ressources*, URL `/idfm_departure_static/idfm-departure-card.js`.

```yaml
type: custom:idfm-departure-card
entity: sensor.chatelet_leave_at
weather_entity: weather.maison
show_next: true
```

| Option | Obligatoire | Défaut | Description |
|---|---|---|---|
| `entity` | oui | | Capteur `leave_at` de l'intégration |
| `weather_entity` | non | | Entité `weather.*` (icône et température) |
| `title` | non | nom de l'arrêt | Remplace le nom de l'arrêt |
| `show_next` | non | `false` | Affiche « Puis : 15:34, 15:38 » (départs suivants) |
| `show_clock` | non | `true` | Affiche l'heure courante en haut à droite |
| `show_arrival` | non | `true` | Affiche l'arrivée à la station de destination (si configurée) |
| `show_platform` | non | `true` | Affiche la voie à côté de l'heure de départ (si connue) |

### Carte « Départs détaillés »

La carte `idfm-departure-list-card` (« IDFM Départs détaillés », chargée par le même fichier) affiche un
tableau des prochains départs du capteur `leave_at` : pastille de ligne, direction, heure pour partir
(« Partir », avec « dans N min » ou « maintenant »), heure du train en gare (« Gare », avec un point vert
si le temps réel est disponible), voie (« Voie », « – » si inconnue) et heure d'arrivée (« Arrivée »,
affichée seulement si au moins un départ en a une). Les départs dont l'heure pour partir est passée
disparaissent automatiquement (recalcul toutes les 10 secondes). La carte est adaptative : la direction
est masquée sur largeur moyenne, et sur une carte étroite (moins de 360 px) chaque départ passe sur deux
lignes.

```yaml
type: custom:idfm-departure-list-card
entity: sensor.auber_leave_at
title: RER A depuis Auber
count: 5
show_arrival: true
show_direction: true
```

| Option | Obligatoire | Défaut | Description |
|---|---|---|---|
| `entity` | oui | | Capteur `leave_at` de l'intégration |
| `title` | non | nom de l'arrêt | Remplace le nom de l'arrêt |
| `count` | non | `5` | Nombre de départs affichés (1 à 10) |
| `show_arrival` | non | `true` | Affiche la colonne « Arrivée » (si des heures d'arrivée existent) |
| `show_direction` | non | `true` | Affiche la direction du train |

### Personnaliser les tailles

**Taille de la carte dans le tableau de bord.** Dans une vue « Sections », ouvrez l'onglet *Disposition*
de la carte pour régler le nombre de colonnes et de lignes (`grid_options` : `columns`, `rows`). La carte
remplit sa cellule et ses textes s'adaptent à sa largeur. Dans une vue « Panneau » (une seule carte
plein écran), la carte occupe tout l'espace ; utilisez `scale` ou `card_height` pour ajuster.

La carte simple adapte aussi ses textes à la hauteur de sa cellule. Quand la cellule est très large et peu haute
(ex. 12 colonnes × 2 à 4 lignes), elle passe en disposition horizontale (minutes à gauche, infos à droite) ; l'option
`layout: auto | tall | wide` (défaut `auto`) permet de forcer l'une ou l'autre.

**Options de taille** (les deux cartes, aussi présentes dans l'éditeur visuel) :

| Option | Cartes | Défaut | Description |
|---|---|---|---|
| `scale` | les deux | `1` | Échelle globale, de `0.5` à `3`, appliquée à toutes les tailles |
| `minutes_size` | simple | auto | Taille du gros compteur « N min » |
| `header_size` | les deux | auto | Taille du nom de l'arrêt / titre |
| `badge_size` | les deux | auto | Taille de la pastille de ligne |
| `footer_size` | simple | auto | Taille de la ligne du bas (mode, heure, arrivée) |
| `row_size` | liste | auto | Taille du texte principal des lignes (direction) |
| `time_size` | liste | auto | Taille des heures (« Partir », « Gare », « Arrivée ») |
| `platform_size` | les deux | auto | Taille de la voie |
| `card_height` | les deux | non défini | Hauteur de la carte, ex. `100%` ou `300px` |

Les tailles `*_size` et `card_height` acceptent un nombre (pixels) ou une chaîne avec unité (`120px`,
`20cqi`, `2em`; unités `px`, `em`, `rem`, `%`, `cqi`, `vw`, `vh`). Une valeur invalide est ignorée (avertissement
dans la console du navigateur). Par défaut les tailles suivent la largeur de la carte (unités `cqi`).

```yaml
type: custom:idfm-departure-card
entity: sensor.chatelet_leave_at
scale: 1.3
minutes_size: 140
```

**Variables CSS.** Chaque taille est une variable CSS (valeur finale = variable × `--idfm-scale`) :

- carte simple : `--idfm-scale`, `--idfm-header-size`, `--idfm-clock-size`, `--idfm-badge-size`,
  `--idfm-label-size` (« Partir dans »), `--idfm-minutes-size`, `--idfm-minutes-small-size` (texte « Aucun
  départ » / « Partir maintenant ! »), `--idfm-footer-size`, `--idfm-next-size` (« Puis »),
  `--idfm-weather-icon-size`, `--idfm-padding`, `--idfm-card-height` ;
- carte liste : `--idfm-scale`, `--idfm-header-size`, `--idfm-clock-size`, `--idfm-badge-size`,
  `--idfm-row-size`, `--idfm-time-size`, `--idfm-platform-size`, `--idfm-col-header-size`,
  `--idfm-sub-size` (« dans N min », marche), `--idfm-padding`, `--idfm-card-height`.

Avec card-mod :

```yaml
type: custom:idfm-departure-card
entity: sensor.chatelet_leave_at
card_mod:
  style: |
    ha-card { --idfm-minutes-size: 120px; }
```

Dans un thème (appliqué à toutes les cartes) :

```yaml
mon-theme:
  idfm-minutes-size: 120px
```

Les variables d'un thème sont des variables `--idfm-...` (HA ajoute le préfixe `--`). Les options définies
dans la configuration de la carte (`minutes_size`, `scale`...) sont posées en ligne sur la carte et
**l'emportent** sur les variables du thème ou de card-mod ; retirez l'option pour laisser le thème décider.

## Limites

Seul le premier tronçon en transport est affiné en temps réel en mode trajet. Les formats de certaines
requêtes (temps de marche Navitia, paramètre `LineRef` SIRI) n'ont pas encore été vérifiés avec une vraie clé.
