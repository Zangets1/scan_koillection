<div align="center">

# 📚 Scan Koillection

**Scannez le code-barres d'un livre, il arrive dans Koillection.**

Application web auto-hébergée, pensée pour un NAS et un téléphone.
Métadonnées issues de la **BnF**, du **SUDOC**, d'**OpenLibrary** et d'**openBD** — pas de dépendance à Google Books.

[![CI](https://github.com/zangets1/scan_koillection/actions/workflows/ci.yml/badge.svg)](https://github.com/zangets1/scan_koillection/actions/workflows/ci.yml)
[![Image Docker](https://img.shields.io/badge/ghcr.io-scan__koillection-2f6df6)](https://github.com/zangets1/scan_koillection/pkgs/container/scan_koillection)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-green)](LICENSE)

[English](README.md) · **Français**

</div>

> Cette page est la version française du [README](README.md). Les deux sont tenues à jour
> ensemble ; en cas de divergence, la version anglaise fait foi.

---

## Ce que ça fait

1. Vous ouvrez la page sur votre téléphone et vous scannez le code-barres au dos du livre.
2. L'ISBN est vérifié (clé de contrôle + double lecture concordante) — pas de faux positifs.
3. Les catalogues sont interrogés **en parallèle** et leurs réponses fusionnées — une demi-seconde en général, quatre au grand maximum.
4. Une fiche pré-remplie s'affiche : vous corrigez ce que vous voulez, vous cochez **« J'ai lu ce livre »**, vous validez.
5. L'item est créé dans Koillection avec sa couverture ; **si le livre appartient à une série, il est rangé dans une sous-collection à son nom**, créée automatiquement.

Champs remontés dans Koillection : **titre, auteur, éditeur, date de parution, nombre de pages, genre, synopsis, série, tome, langue, ISBN, et la case « Lu »**.

---

## Pourquoi la BnF plutôt que Google Books

| Source | Sans clé | Livres FR | Synopsis FR | Série + tome | Genre |
|---|:--:|:--:|:--:|:--:|:--:|
| **BnF** (SRU / UNIMARC) | ✅ | ✅✅ | ✅ (notices Electre) | ✅ (zone 461) | ✅ |
| **SUDOC** (bibliothèques universitaires) | ✅ | ✅✅ | ✅ (4e de couverture) | ✅ (zone 200) | ✅✅ |
| **OpenLibrary** | ✅ | ⚠️ partiel | 🇬🇧 anglais | ⚠️ parfois | ⚠️ mots-clés |
| **K10plus** (MARC21) | ✅ | — anglophone seulement | ❌ | ✅ (zone 830) | ❌ |
| **openBD** (Japon) | ✅ | ❌ | 🇯🇵 japonais | ✅ | ⚠️ |
| Google Books | ✅ | ⚠️ irrégulier | ⚠️ | ❌ | ⚠️ |

La BnF est interrogée en premier et fait autorité. Les autres ne servent qu'à **combler les champs vides**.
Google Books reste présent en dernier recours et se retire d'une variable : `PROVIDERS=bnf,sudoc,openbd`.

**Pourquoi le SUDOC en second.** Mesuré sur 18 livres français, il n'apporte quasiment
aucun titre que la BnF ignore — mais il remplit le résumé sur **4 livres de plus** et le
genre sur **8 de plus**, avec des étiquettes bien plus utiles (« Mangas », « Shônen »
plutôt que « Bandes dessinées »). Il sert aussi de roue de secours : le service SRU de la
BnF coupe la connexion par intermittence, et le SUDOC prend alors le relais.

### Chaque catalogue là où il sait répondre

Les trois premiers chiffres d'un ISBN désignent l'agence qui a enregistré l'éditeur, donc
l'aire linguistique du livre. Un catalogue n'est interrogé que sur les aires qu'il couvre :

| Aire | Préfixes | Catalogues interrogés |
|---|---|---|
| Francophone | `978-2`, `979-10` | BnF, SUDOC, OpenLibrary, Google Books |
| Anglophone | `978-0`, `978-1`, `979-8` | SUDOC, OpenLibrary, K10plus, Google Books |
| Japon | `978-4` | SUDOC, OpenLibrary, openBD, Google Books |

Mesuré sur 87 ISBN, la BnF ne référence qu'**un livre anglophone sur cinquante-cinq** :
l'interroger pour un roman anglais ouvrait une connexion dont la réponse était connue
d'avance. Les catalogues étant lancés en parallèle, le temps total est celui du plus lent —
en retirer deux **raccourcit** la recherche : −0,7 s sur un scan anglophone, −0,3 s sur un
scan français.

Une aire inconnue n'écarte personne : sur un ISBN dont le groupe n'est pas répertorié, tout
le monde est interrogé, comme avant.

> **Non, l'ISBN ne dit pas le pays.** `978-0` et `978-1` forment un **unique** groupe
> « langue anglaise », partagé par le Royaume-Uni, les États-Unis, l'Australie et l'Irlande.
> Aucun code-barres ne permet de distinguer une édition anglaise d'une édition américaine :
> `978-0-7475-3274-3` est le Harry Potter de Bloomsbury à Londres, `978-0-590-35340-3` celui
> de Scholastic à New York. Seule la notice du catalogue porte le pays d'édition — K10plus le
> renseigne pour environ un livre anglophone sur cinq, et l'API le renvoie dans le champ
> `country`. C'est trop rare pour mériter une case dans le formulaire.

**Pourquoi K10plus sur l'anglophone.** Catalogue collectif des bibliothèques allemandes, bien
fourni en éditions anglo-saxonnes, en MARC21, sans clé ni quota. Mesuré sur 55 ISBN
anglophones, il ne fait découvrir **aucun** livre qu'OpenLibrary ignore, mais il comble la
pagination (73 % → 84 %) et la série (17 % → 24 %). Ses zones de résumé et de genre sont
écartées : leur langue dépend de la bibliothèque qui a rédigé la notice, allemande ou
anglaise, et rien dans le format ne permet de le savoir. Il reste cantonné à l'anglophone —
sur les ISBN `978-2` il ne comble rien que la BnF et le SUDOC n'aient déjà, pour une
connexion de plus.

> **Garde-fou anti-mélange.** Certains ISBN sont attribués à deux ouvrages différents selon les catalogues.
> Si une source secondaire décrit visiblement un autre livre (titre sans rapport **et** aucun auteur commun),
> sa notice est écartée plutôt que fusionnée : mieux vaut un champ vide qu'une fiche chimérique.

---

## Installation sur le NAS

### 1. Docker Compose

Le [`docker-compose.yml`](docker-compose.yml) **se suffit à lui-même** : la configuration
est écrite dedans, pas dans un `.env` à côté. Il peut donc être collé tel quel dans
l'interface Docker d'un NAS (UGREEN, Synology, QNAP…) qui ne permet pas de déposer des
fichiers annexes.

Il joint Koillection **par son nom de conteneur** (`http://koillection:80`), ce qui suppose
un réseau Docker partagé. Une seule chose est donc à vérifier avant de démarrer : le nom du
réseau de votre Koillection, en bas du fichier.

```bash
docker network ls        # relevez « koillection_default » ou son équivalent
```

```yaml
networks:
  koillection:
    external: true
    name: koillection_default    # le nom relevé ci-dessus
```

Si le nom est faux, Compose refuse de démarrer avec un message sans ambiguïté
(`network … declared as external, but could not be found`) — vous ne resterez pas devant
une liste de collections vide sans savoir pourquoi.

> **Vous préférez éviter la configuration réseau ?** Remplacez simplement `KOILLECTION_URL`
> par l'IP du NAS et le port publié par Koillection (`http://192.168.1.10:81`), et retirez
> le bloc `networks` ainsi que les deux lignes `networks:` du service.

Les autres valeurs à renseigner : vos identifiants Koillection, `PUID`/`PGID`, et
l'adresse du NAS pour le HTTPS.

En ligne de commande :

```bash
mkdir -p /volume1/docker/scan-koillection && cd $_
curl -O https://raw.githubusercontent.com/zangets1/scan_koillection/main/docker-compose.yml
nano docker-compose.yml     # les lignes « À RENSEIGNER »
docker compose --profile https up -d
```

> Si vous préférez un `.env` séparé, remplacez le bloc `environment:` par
> `env_file: [.env]` et partez du [`.env.example`](.env.example), qui documente
> **toutes** les variables disponibles.

L'interface répond sur `http://IP_DU_NAS:8080`.

> **Dépôt privé ?** Tant que le dépôt GitHub reste privé, l'image publiée sur GHCR l'est
> aussi : le NAS doit s'authentifier avant de la télécharger.
>
> ```bash
> echo VOTRE_TOKEN | docker login ghcr.io -u zangets1 --password-stdin
> ```
>
> Le jeton est un *personal access token* (classic) avec la seule portée `read:packages`.
> Pour éviter cette étape, rendez le paquet public depuis
> **GitHub → Packages → scan_koillection → Package settings → Change visibility**,
> ou construisez l'image localement avec `build: .` dans `docker-compose.yml`.

### 2. Le point qui bloque tout le monde : HTTPS

**iOS comme Android refusent l'accès à la caméra sur une page en `http://`** (hors `localhost`).
En `http://192.168.1.x:8080`, la saisie manuelle de l'ISBN fonctionnera, mais pas le scan.

Trois solutions, de la plus simple à la plus propre :

<details>
<summary><b>a. Le reverse proxy fourni (Caddy, certificat auto-signé)</b></summary>

Il est déjà dans le `docker-compose.yml`. Renseignez `NAS_HOST` avec **exactement**
l'adresse que vous taperez dans le navigateur — le certificat est émis pour elle — puis :

```bash
docker compose --profile https up -d
```

Rendez-vous sur `https://IP_DU_NAS:8443` et acceptez l'avertissement de sécurité une fois.
Sur iOS, il faut parfois appuyer sur « Afficher les détails » → « visiter ce site web ».

Aucun fichier de configuration à créer : Caddy écrit la sienne au démarrage. Le
[`Caddyfile`](Caddyfile) du dépôt n'est là que si vous préférez un fichier séparé.
</details>

<details>
<summary><b>b. Un vrai certificat (recommandé si vous avez un domaine)</b></summary>

Utilisez le [`Caddyfile`](Caddyfile) du dépôt, monté dans le conteneur Caddy en
remplacement du bloc `command:`, avec pour contenu :

```
scan.mondomaine.fr {
    reverse_proxy scan-koillection:8080
}
```

Caddy obtient et renouvelle le certificat Let's Encrypt tout seul.
La plupart des NAS (Synology, UGREEN, TrueNAS) savent aussi le faire depuis leur propre reverse proxy.
</details>

<details>
<summary><b>c. Tailscale / WireGuard</b></summary>

Avec Tailscale, `tailscale serve` fournit un nom en `*.ts.net` et un certificat valide sans rien exposer sur Internet.
</details>

### 3. Créer une collection dans Koillection

Le scanner ne crée pas de collection racine : il range les livres dans celle que vous
choisissez. Créez-en une (« Livres », « Mangas »…) depuis Koillection avant le premier
scan, sinon la liste déroulante restera vide.

Une collection ajoutée pendant que le scanner tourne apparaît **au bout d'une minute**,
ou tout de suite avec le bouton **« ⟳ Recharger depuis Koillection »** sous la liste. La
liste est mise en cache une minute pour ne pas interroger l'API à chaque affichage.

> **La liste reste vide ?** Le bouton **« Diagnostiquer la connexion »** déroule la chaîne
> étape par étape et nomme la cause exacte :
>
> ```
> ✓ Configuration — http://192.168.1.10:81
> ✓ Koillection joignable — Réponse HTTP 200.
> ✓ Identifiants acceptés — Connecté en tant que « damien ».
> ✗ Collections visibles — Le compte « damien » n'a aucune collection.
> ```
>
> Les pièges habituels :
>
> - **`http://koillection:80` sans réseau partagé.** Chaque pile Compose crée son propre
>   réseau : le nom du conteneur Koillection n'est pas résolu depuis le scanner. Voir
>   ci-dessous.
> - **`localhost` ou `127.0.0.1`** qui, depuis le conteneur, désigne le conteneur lui-même
>   et non le NAS.
> - **Une collection créée sous un autre compte Koillection** : elle appartient à son
>   créateur et reste invisible aux autres comptes.
>
> `KOILLECTION_DEFAULT_COLLECTION` n'est jamais en cause : cette variable présélectionne
> une entrée dans la liste, elle ne la filtre pas.

#### Le nom de conteneur ne se résout pas ?

`http://koillection:80` ne fonctionne que si les deux piles partagent un réseau : chaque
pile Compose crée le sien. Vérifiez le bloc `networks` en fin de `docker-compose.yml`, et
que le conteneur a bien rejoint les deux réseaux :

```bash
docker inspect scan-koillection --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
# → koillection_default scan_default
```

### 4. Ajouter l'application à l'écran d'accueil

C'est une PWA : **Partager → Sur l'écran d'accueil** (iOS) ou **Menu → Installer l'application** (Android).
Elle s'ouvre alors en plein écran, sans barre d'adresse.

---

## Configuration

Tout passe par des variables d'environnement, déclarées soit directement dans le
`docker-compose.yml`, soit dans un `.env` séparé ([modèle commenté](.env.example)).

### L'essentiel

| Variable | Rôle |
|---|---|
| `KOILLECTION_URL` | URL de Koillection **vue depuis le conteneur** |
| `KOILLECTION_USERNAME` / `KOILLECTION_PASSWORD` | Compte utilisé par l'API |
| `KOILLECTION_DEFAULT_COLLECTION` | Collection proposée par défaut (titre, chemin ou UUID) |
| `APP_PASSWORD` | Mot de passe d'accès à l'interface (vide = libre) |

### Le reste

| Variable | Défaut | Rôle |
|---|---|---|
| `PROVIDERS` | `bnf,sudoc,openlibrary,openbd,googlebooks` | Catalogues et ordre de priorité |
| `PROVIDER_TIMEOUT` | `8` | Délai maximal par catalogue (s) |
| `LOOKUP_DEADLINE` | `4` | Plafond global d'une recherche (s) |
| `SERIES_SUBCOLLECTIONS` | `1` | Créer une sous-collection par série |
| `SERIES_ITEM_NAME` | `{series} - T{volume:02d} - {title}` | Nom de l'item pour une série |
| `GENRES_AS_TAGS` | `1` | Créer aussi les genres comme tags |
| `UPLOAD_COVER` | `1` | Téléverser la couverture |
| `FIELD_LABELS` | — | Renommer les champs créés (JSON) |
| `CACHE_TTL` | `86400` | Cache mémoire des recherches (s) |
| `SESSION_SECRET` | — | Clé de signature des sessions |
| `PUID` / `PGID` | `10001` | Propriétaire du dossier `./data` (voir ci-dessous) |

> **Droits sur `./data`.** Le conteneur ne tourne pas en root. Au démarrage, il aligne le
> propriétaire du volume sur `PUID:PGID`. Si votre NAS impose un utilisateur précis
> (souvent `1000:1000`, `1026:100` chez Synology), renseignez-le : c'est la cause n°1
> d'un conteneur qui refuse de démarrer avec « impossible d'écrire l'historique ».

### Adapter les noms de champs à votre Koillection

Si vos fiches utilisent déjà « Écrivain » plutôt que « Auteur » :

```env
FIELD_LABELS={"authors":"Écrivain","published":"Parution","read":"Terminé"}
```

Une valeur vide supprime le champ : `FIELD_LABELS={"language":"","source":""}`.

> La date de parution est écrite en **texte** et non en type « date » : la BnF ne fournit
> le plus souvent que l'année, et Koillection refuse une date incomplète. Le champ garde
> ainsi le même type d'un livre à l'autre, et reste triable (`2013` < `2016-04`).

---

## Combien de temps prend une recherche

Mesuré sur 18 livres français, cache vidé, les cinq catalogues activés :

| | médiane | 9 fois sur 10 | maximum |
|---|:--:|:--:|:--:|
| Recherche complète | **0,6 s** | 1,1 s | 4,0 s |

Les catalogues sont interrogés **tous en même temps** : le temps total est celui du plus
lent, pas la somme. Ajouter une source ne rallonge donc pas la recherche tant qu'elle
répond dans les temps — passer de quatre à cinq catalogues a coûté 0,13 s de médiane.

Le corollaire vaut dans l'autre sens, et c'est ce qui rend le tri par aire linguistique
payant : **retirer** une source retire un candidat au titre de « plus lent ». Comparé sur
trois serveurs mesurés en alternance sur les mêmes ISBN, écart apparié livre par livre :

| | requêtes par scan | écart |
|---|:--:|:--:|
| Scan anglophone, avant | 5 | référence |
| Scan anglophone, après | 3 | **−0,7 s** |
| Scan français, avant | 5 | référence |
| Scan français, après | 4 | **−0,3 s** |

Le maximum n'est pas un hasard : c'est `LOOKUP_DEADLINE`. Passé ce délai, la fiche
s'affiche avec ce qui est arrivé et les retardataires sont marqués « trop lent » à côté
des sources. Personne n'attend indéfiniment devant son étagère parce qu'un serveur
distant a hoqueté.

---

## Le scanner

- **Deux moteurs.** L'API `BarcodeDetector` du navigateur quand elle existe (Android), sinon
  **ZXing** en JavaScript — c'est ce dernier qui fait tourner iOS, où Safari n'implémente
  toujours pas `BarcodeDetector`.
- **Décodage recadré.** Seule la bande centrale de l'image est analysée : plus rapide, et
  cela évite d'attraper le code-barres du livre d'à côté.
- **Validation en trois temps.** Clé de contrôle EAN-13 → préfixe Bookland (978/979) →
  **deux lectures identiques d'affilée**. Un ISSN de revue (977) ou un code de supermarché
  est refusé avec un message explicite plutôt que cherché en vain.
- **Confirmation sensorielle.** Vibration, bip et cadre qui vire au vert.
- **Lampe torche** quand l'appareil l'expose (Android).
- **Toujours une porte de sortie.** Le champ ISBN est en haut de la première page, et le
  bouton « Saisir l'ISBN » reste accessible depuis l'écran de scan.

### Quand le livre est introuvable

Aucun catalogue ne connaît l'ISBN ? La fiche s'ouvre quand même, vide, avec le message qui
invite à renseigner le titre et l'auteur. Le reste est facultatif, la case « Lu » est là,
et l'item part dans Koillection comme les autres.

Surtout, **le numéro réellement lu est affiché en grand**, en chiffres à chasse fixe
groupés par trois : de quoi le comparer à celui imprimé sur le livre et savoir tout de
suite si le lecteur s'est trompé ou si l'ouvrage est simplement absent des bases. Deux
boutons sont proposés dans la foulée — **Rescanner** et **Corriger le numéro**, qui
renvoie à l'accueil avec le code prêt à être modifié.

Le découpage est volontairement sans tirets : la vraie césure d'un ISBN dépend de tables
de préfixes d'éditeurs, et un découpage inventé (`978-2-72-348989-8` au lieu de
`978-2-7234-8989-8`) gênerait précisément la comparaison. Un ISBN-10 lu au dos d'un livre
ancien reste affiché tel quel, à côté de sa conversion en ISBN-13.

Le bouton **« Saisir le livre à la main »** de l'accueil ouvre la même fiche, sans ISBN du tout
(livres anciens, éditions sans code-barres).

---

## Détection des doublons

Avant chaque création, les items de la collection de destination sont comparés sur leur champ ISBN.
Si le livre y est déjà, une confirmation s'affiche avec un lien vers la fiche existante.

> **Limite assumée.** L'API de Koillection n'expose aucun filtre de recherche : la vérification
> se limite à la collection visée (et à sa sous-collection de série). Un même livre rangé
> ailleurs ne sera pas détecté. L'historique local, lui, signale tout ISBN déjà passé par l'outil.

---

## Développement

```bash
git clone https://github.com/zangets1/scan_koillection.git
cd scan_koillection
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest                 # 79 tests, sans accès réseau
KOILLECTION_URL=... .venv/bin/uvicorn app.main:app --reload --port 8080
```

### Organisation

```
app/
  main.py         routes FastAPI, sessions, service des fichiers statiques
  lookup.py       appels parallèles aux catalogues, plafond de temps, fusion, cache
  providers/      un module par catalogue, plus `unimarc.py` mutualisé
                  entre la BnF et le SUDOC (même format, emballage XML différent)
  koillection.py  client de l'API Koillection (JWT, collections, items, data)
  importer.py     traduction d'une fiche livre en item + champs Koillection
  series.py       extraction série/tome depuis un titre
  isbn.py         validation, conversion ISBN-10 ↔ ISBN-13
  covers.py       résolution des couvertures (liste blanche + vérification)
static/           PWA : une page, un CSS, un JS, ZXing embarqué
tests/            tests unitaires + fixtures BnF réelles
```

### Ajouter un catalogue

Créez `app/providers/mon_catalogue.py`, héritez de `Provider`, renvoyez un `BookMeta`,
inscrivez la classe dans `build_providers()` puis ajoutez son nom à `PROVIDERS`.
Un fournisseur qui échoue est simplement ignoré : il ne peut pas bloquer une recherche.

Déclarez `groups` si le catalogue ne couvre qu'une partie du monde — il ne sera alors
interrogé que sur ces aires (`fr`, `en`, `ja`, `de`, `es`, `it`, `ru`, `zh`, `ko`) :

```python
class MonCatalogue(Provider):
    name = "mon_catalogue"
    label = "Mon catalogue"
    groups = frozenset({"en"})   # omettre l'attribut = toutes les aires
```

Deux lecteurs de notices bibliothécaires sont déjà disponibles : `unimarc.py` pour les
catalogues francophones (BnF, SUDOC) et `marc21.py` pour les catalogues anglo-saxons et
allemands (K10plus, Library of Congress). Les deux décrivent les mêmes livres, mais les
zones n'y portent pas les mêmes numéros.

### Essayer une branche avant de la fusionner

Pousser sur une branche `v*` publie une image portant son nom, par exemple
`ghcr.io/zangets1/scan_koillection:v2`. Elle est construite pour amd64 et arm64, et
**`:latest` n'est jamais touchée** : votre installation de production ne peut pas
l'attraper par un `docker compose pull`.

Faites-la tourner à côté de l'existante, sur un autre port et un autre dossier de données :

```yaml
services:
  scan-koillection-essai:
    image: ghcr.io/zangets1/scan_koillection:v2
    ports: ["8081:8080"]
    volumes: ["./data-essai:/data"]
    env_file: .env
```

`GET /healthz` renvoie la version exacte (`v2-<commit>`), de quoi vérifier ce qui tourne
réellement. Le workflow se relance aussi à la main depuis **Actions → Image d'essai**.

### Et la Library of Congress ?

C'est le seul véritable catalogue national américain accessible sans clé, et `marc21.py`
sait déjà lire ses notices. Mais elle n'expose son service SRU que sur
`http://lx2.loc.gov:210/LCDB` — en clair, sur un port non standard que beaucoup de réseaux
domestiques filtrent. Avant d'écrire le fournisseur, vérifiez qu'elle répond **depuis la
machine qui fera les requêtes** :

```bash
python3 tools/test-loc.py
```

Le script n'a aucune dépendance et ne modifie rien : il ouvre une connexion, interroge trois
ISBN témoins et affiche ce qu'il obtient.

---

## Versions et retour arrière

Chaque version est publiée en **release GitHub** avec une image Docker étiquetée.
Une mise à jour se passe mal ? Revenez à la précédente en une ligne :

```yaml
image: ghcr.io/zangets1/scan_koillection:1.0.0   # au lieu de :latest
```

```bash
docker compose up -d
```

Les tags `:latest`, `:1`, `:1.0` et `:1.0.0` sont maintenus. Le dossier `./data` (historique)
est compatible entre versions ; aucune donnée Koillection n'est touchée par un retour arrière.

**Branches.** `main` porte la version stable publiée ; le développement se fait sur des
branches dédiées (`claude/…`, `feat/…`) fusionnées ensuite dans `main`. Voir le
[CHANGELOG](CHANGELOG.md).

**Publier une version.** Deux possibilités, au choix :

- depuis GitHub : onglet **Actions → Release → Run workflow**, saisissez `v1.0.0` ;
- depuis un terminal : `git tag -a v1.0.0 -m "…" && git push origin v1.0.0`.

Dans les deux cas, le workflow construit l'image `amd64` + `arm64`, la publie sur GHCR et
crée la release GitHub avec ses notes.

---

## Signaler un problème

Les [issues](https://github.com/zangets1/scan_koillection/issues) sont ouvertes. Deux
formulaires guident la saisie (bogue / évolution) et demandent d'emblée ce qui manque
presque toujours : la version, et le résultat du bouton **« Diagnostiquer la connexion »**.

Chaque nouvelle issue reçoit une **première analyse automatique** : nature de la demande,
vérification qu'elle n'est pas déjà corrigée dans une version publiée, causes de
configuration connues, et informations manquantes. Cette analyse ne touche jamais au code.

La correction, elle, ne se déclenche **que sur demande d'un mainteneur** — étiquette
`claude-fix` ou commentaire `@claude` — et aboutit toujours à une pull request relue, jamais
à un commit direct sur `main`.

<details>
<summary><b>Activer l'automatisation sur votre propre copie</b></summary>

Les deux workflows restent inertes tant que le secret n'existe pas : ils s'arrêtent à la
première étape en le signalant, sans faire échouer quoi que ce soit.

1. **Settings → Secrets and variables → Actions → New repository secret**
   nommé `ANTHROPIC_API_KEY` ([clé à créer ici](https://console.anthropic.com/settings/keys)).
2. Pour la correction assistée, créez l'étiquette `claude-fix` (elle peut aussi être créée
   à la volée en l'appliquant à une issue).

L'analyse consomme des jetons d'API à chaque issue ouverte : sur un dépôt public, c'est une
dépense que n'importe qui peut déclencher. Le tri est volontairement court pour la limiter,
mais surveillez la consommation, et retirez le secret si elle s'emballe.

</details>

---

## Crédits et licence

- Données : [BnF – Catalogue général](https://api.bnf.fr/fr/api-sru-catalogue-general),
  [SUDOC / ABES](https://abes.fr/reseau-sudoc/documentation-technique/),
  [OpenLibrary](https://openlibrary.org/developers/api), [openBD](https://openbd.jp/),
  résumés Electre diffusés par la BnF.
- Décodage : [ZXing pour JavaScript](https://github.com/zxing-js/library) (Apache 2.0), embarqué dans `static/vendor/`.
- [Koillection](https://github.com/benjaminjonard/koillection) de Benjamin Jonard.

Ce projet est sous licence [MIT](LICENSE). Il n'est affilié ni à la BnF ni à Koillection.
