# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et le versionnage [SemVer](https://semver.org/lang/fr/).

## [1.0.0] — 2026-08-10

Première version publiée.

### Ajouté

- **Scanner de code-barres** utilisable sur iOS et Android : `BarcodeDetector` quand le
  navigateur le propose, ZXing en JavaScript sinon (seule option viable sur Safari).
  Décodage limité à la bande centrale de l'image, lampe torche quand l'appareil l'expose.
- **Validation stricte des lectures** : clé de contrôle EAN-13, préfixe Bookland 978/979,
  puis deux lectures identiques d'affilée avant acceptation. Les ISSN (977) et les codes
  produits hors édition sont refusés avec un message explicite.
- **Saisie manuelle de l'ISBN en première page**, toujours accessible même depuis l'écran
  de scan, et bouton « Saisir le livre à la main » pour les ouvrages sans code-barres.
- **Recherche parallèle dans quatre catalogues** : BnF (SRU / UNIMARC), OpenLibrary,
  openBD pour les éditions japonaises, Google Books en dernier recours. Ordre et
  composition réglables par `PROVIDERS`.
- **Fusion des notices champ par champ** avec priorité au premier catalogue, et rejet
  d'une source qui décrit visiblement un autre livre (titres sans rapport et aucun auteur
  commun) pour éviter les fiches chimériques.
- **Détection série / tome** depuis la zone UNIMARC 461 de la BnF, le champ `series`
  d'OpenLibrary, ou à défaut le titre lui-même (« One Piece, Tome 12 : … »). Les
  collections éditoriales numérotées (Folio n°822) ne sont pas confondues avec des séries.
- **Envoi vers Koillection** : création de l'item, des champs (titre, auteur, éditeur,
  date, pages, genre, synopsis, série, tome, langue, ISBN, lien vers la notice source et
  case « Lu »), des tags de genre et téléversement de la couverture — celle réellement
  affichée dans l'interface, les services de couverture renvoyant souvent une image vide
  avec un code 200.
- **Sous-collections de série** créées automatiquement sous la collection choisie.
- **Détection des doublons** sur l'ISBN dans la collection de destination, avec lien vers
  la fiche existante et possibilité de forcer l'ajout.
- **Fiche éditable avant validation**, case « J'ai lu ce livre » incluse, et ouverture de
  la fiche vide avec invitation à saisir titre et auteur quand aucun catalogue ne répond.
- **PWA installable** sur l'écran d'accueil, thème clair/sombre automatique, historique
  local des ajouts (SQLite).
- **Mot de passe d'accès facultatif** (`APP_PASSWORD`) et libellés de champs
  personnalisables (`FIELD_LABELS`).
- **Image Docker multi-architecture** (amd64, arm64) publiée sur GHCR, profil Compose
  `https` avec Caddy pour obtenir le HTTPS qu'exigent les navigateurs mobiles.

[1.0.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.0.0
