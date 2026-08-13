# Journal des modifications

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/)
et le versionnage [SemVer](https://semver.org/lang/fr/).

## Non publié

### Ajouté

- **K10plus** (`k10plus`), catalogue collectif des bibliothèques allemandes, interrogé sur
  les seuls ISBN anglophones. Sur 55 ISBN testés, il ne fait découvrir aucun livre
  qu'OpenLibrary ignore mais comble la pagination (73 % → 84 %) et la série (17 % → 24 %).
  Ses zones de résumé et de genre sont écartées : leur langue dépend de la bibliothèque qui
  a rédigé la notice, et rien dans le format ne permet de le savoir à l'avance.
- **Lecteur MARC21** (`app/providers/marc21.py`), pendant d'`unimarc.py` pour les catalogues
  anglo-saxons et allemands. Il ouvre la voie à la Library of Congress, sous réserve que son
  service — HTTP en clair sur le port 210 — soit joignable depuis le serveur.
- **Pays d'édition** dans la réponse de `/api/lookup` (champ `country`), lu dans la notice
  MARC et jamais déduit de l'ISBN. Renseigné pour environ un livre anglophone sur cinq, ce
  qui est trop rare pour justifier un champ dans le formulaire ou dans Koillection.
- **Tri automatique des issues** : chaque nouvelle issue reçoit une analyse — nature de la
  demande, vérification qu'elle n'est pas déjà corrigée, causes de configuration connues,
  informations manquantes — et une étiquette. Ce workflow ne modifie jamais le code.
- **Correction assistée sur demande** (étiquette `claude-fix` ou commentaire `@claude` d'un
  mainteneur) : reproduction par un test qui échoue, correctif, suite de tests, puis pull
  request. Jamais de commit direct sur `main`, et rien ne se déclenche à l'initiative d'un
  inconnu.
- **Formulaires d'issue** (bogue / évolution) réclamant d'emblée la version et le résultat
  du diagnostic de connexion.
- **README en anglais** (`README.md`), la version française devenant `README.fr.md`. Les
  deux se renvoient l'une à l'autre. Le tri des issues et la correction assistée répondent
  désormais dans la langue de l'issue.

### Modifié

- **Un catalogue n'est plus interrogé que sur les ISBN qu'il peut connaître.** Les trois
  premiers chiffres d'un ISBN désignent l'agence qui a enregistré l'éditeur, donc l'aire
  linguistique du livre : la BnF n'est plus sollicitée que sur les `978-2`, openBD que sur
  les `978-4`. Mesuré sur 87 ISBN, la BnF ne référence qu'un livre anglophone sur 55 ;
  l'interroger pour un roman anglais ouvrait une connexion dont la réponse était connue.
  Les catalogues tournant en parallèle, en retirer deux **raccourcit** la recherche :
  −0,7 s sur un scan anglophone, −0,3 s sur un scan français.

  Le défaut reste « toutes les aires » : un fournisseur qui ne déclare rien est interrogé
  comme avant, et un ISBN dont le groupe n'est pas répertorié n'écarte personne.

  > À noter, parce que c'est contre-intuitif : `978-0` et `978-1` forment un **unique**
  > groupe « langue anglaise », partagé par le Royaume-Uni, les États-Unis, l'Australie et
  > l'Irlande. Aucun ISBN ne permet de distinguer une édition anglaise d'une américaine.

- Le test `startswith("9784")` qu'openBD portait en dur dans son `fetch()` est remplacé par
  la déclaration commune `groups`.

## [1.3.2] — 2026-08-11

### Modifié

- Le `docker-compose.yml` fourni joint désormais Koillection **par son nom de conteneur**
  (`http://koillection:80`), avec le réseau partagé déclaré et actif plutôt qu'en
  commentaire : c'est la configuration attendue quand les deux services tournent sur le
  même NAS. Un nom de réseau erroné fait échouer le démarrage avec un message explicite,
  au lieu d'aboutir à une liste de collections vide et inexpliquée. L'alternative par
  l'adresse IP reste documentée.
  Vérifié de bout en bout avec deux piles Compose distinctes, profil HTTPS compris.

## [1.3.1] — 2026-08-11

### Ajouté

- Le diagnostic distingue désormais **un nom d'hôte non résolu** d'un port fermé et nomme
  la cause : deux piles Compose ne partagent pas leur réseau, si bien qu'une URL du type
  `http://koillection:80` reste introuvable tant que les conteneurs n'ont pas été
  rattachés. Le `docker-compose.yml` et le README expliquent comment le faire.

## [1.3.0] — 2026-08-11

### Ajouté

- **Diagnostic de la connexion à Koillection.** « Aucune collection trouvée » recouvrait
  trois situations très différentes — serveur injoignable, identifiants refusés, ou compte
  réellement sans collection — que rien ne permettait de distinguer à l'écran. La liste
  vide déclenche maintenant un contrôle affiché étape par étape dans la page, et un bouton
  **« Diagnostiquer la connexion »** permet de le relancer à tout moment. Le message final
  nomme la cause, y compris la plus déroutante : une collection créée sous un autre compte
  Koillection, invisible au compte configuré.

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

[1.3.2]: https://github.com/zangets1/scan_koillection/releases/tag/v1.3.2
[1.3.1]: https://github.com/zangets1/scan_koillection/releases/tag/v1.3.1
[1.3.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.3.0
[1.2.2]: https://github.com/zangets1/scan_koillection/releases/tag/v1.2.2
[1.2.1]: https://github.com/zangets1/scan_koillection/releases/tag/v1.2.1
[1.2.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.2.0
[1.1.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.1.0
[1.0.0]: https://github.com/zangets1/scan_koillection/releases/tag/v1.0.0
