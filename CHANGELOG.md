# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et le versionnage [SemVer](https://semver.org/lang/fr/).

## [1.2.2] — 2026-08-11

### Corrigé

- **Une collection créée dans Koillection après le démarrage n'apparaissait jamais** dans
  la liste du scanner : son cache n'avait aucune durée de vie et n'était vidé qu'au
  redémarrage du conteneur. Il expire désormais au bout d'une minute, et la liste est
  aussi resynchronisée à chaque retour sur l'accueil.
- La pagination de l'API Koillection ne supposait plus rien sur la taille des pages
  décidée par le serveur : elle s'arrêtait dès qu'une page comptait moins de 30 éléments.
  Le comportement était correct avec la valeur actuelle, mais aurait silencieusement
  masqué des collections si elle changeait.

### Ajouté

- Bouton **« ⟳ Recharger depuis Koillection »** sous la liste des collections, bien plus
  visible que l'icône de la barre de titre, avec un retour explicite sur le nombre de
  collections trouvées.
- Message d'aide plus clair quand aucune collection n'existe encore.

## [1.2.1] — 2026-08-11

### Corrigé

- **Le HTTPS ne fonctionnait pas du tout.** Le `Caddyfile` livré déclarait un site sans
  nom d'hôte (`:8443`), si bien que Caddy n'avait aucun certificat à présenter et
  interrompait chaque poignée de main. Il faut à la fois une adresse explicite
  (`NAS_HOST`) et l'option `default_sni`, un navigateur qui vise une adresse IP n'envoyant
  pas d'indication de nom de serveur. Vérifié de bout en bout, requête sans SNI comprise.
- **Le conteneur bouclait au démarrage dès que `PUID` était renseigné**, c'est-à-dire dans
  le cas le plus courant sur un NAS : `setpriv --init-groups` exige que l'identifiant
  existe dans `/etc/passwd`, ce qui n'est jamais vrai pour un UID propre au NAS.

### Modifié

- **Le `docker-compose.yml` se suffit désormais à lui-même** : configuration en
  `environment:` et configuration Caddy écrite au démarrage, sans `.env` ni `Caddyfile` à
  déposer à côté. Il peut être collé tel quel dans l'interface Docker d'un NAS. Le
  `.env.example` reste la référence complète des variables.

## [1.2.0] — 2026-08-11

### Ajouté

- **Le SUDOC** (catalogue des bibliothèques universitaires) rejoint les sources, juste
  après la BnF. Sur 18 livres français, il remplit le résumé sur 4 titres de plus et le
  genre sur 8 de plus, avec des étiquettes plus précises (« Mangas », « Shônen »). Il sert
  aussi de source de secours quand le SRU de la BnF coupe la connexion, ce qu'il fait par
  intermittence.
- **Plafond global de recherche** (`LOOKUP_DEADLINE`, 4 s par défaut) : la fiche s'affiche
  avec les réponses déjà arrivées, les catalogues en retard étant signalés « trop lent ».
  La médiane reste à 0,6 s et le temps d'attente est désormais borné.

### Modifié

- Le genre provient maintenant de la zone UNIMARC 608 (forme de l'œuvre) et non plus des
  vedettes matière 606, qui donnaient des résultats déroutants — « Littérature
  bas-allemande » sur un polar français. Les vedettes matière ne servent plus que de repli
  quand aucune source ne fournit de genre.
- La comparaison des auteurs ignore les accents : la BnF écrit « Eiichirô Oda » là où le
  SUDOC écrit « Eiichiro Oda », et les deux notices étaient à tort tenues pour deux livres
  différents, ce qui faisait perdre l'apport du SUDOC.
- La lecture des notices UNIMARC est mutualisée entre la BnF et le SUDOC : même format
  bibliographique, seul l'emballage XML diffère.

## [1.1.0] — 2026-08-11

### Ajouté

- **Le numéro lu est affiché en grand sur la fiche**, en chiffres à chasse fixe groupés
  par trois, afin de le comparer à celui imprimé sur le livre. Il est mis en évidence en
  couleur d'alerte quand aucun catalogue n'a répondu, accompagné des boutons
  **Rescanner** et **Corriger le numéro**. Un ISBN-10 est montré tel qu'il a été lu, à
  côté de sa conversion en ISBN-13.

### Supprimé

- Fonction d'affichage `isbn.hyphenate()`, inutilisée et trompeuse : la césure d'un ISBN
  dépend de tables de préfixes d'éditeurs, un découpage fixe produisait de faux groupes.

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

[1.2.2]: https://github.com/zangets1/scan_koillection/releases/tag/v1.2.2
[1.2.1]: https://github.com/zangets1/scan_koillection/releases/tag/v1.2.1
[1.2.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.2.0
[1.1.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.1.0
[1.0.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.0.0
