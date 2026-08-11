<div align="center">

# 📚 Scan Koillection

**Scannez le code-barres d'un livre, il arrive dans Koillection.**

Application web auto-hébergée, pensée pour un NAS et un téléphone.
Métadonnées issues de la **BnF**, d'**OpenLibrary** et d'**openBD** — pas de dépendance à Google Books.

[![CI](https://github.com/zangets1/scan_koillection/actions/workflows/ci.yml/badge.svg)](https://github.com/zangets1/scan_koillection/actions/workflows/ci.yml)
[![Image Docker](https://img.shields.io/badge/ghcr.io-scan__koillection-2f6df6)](https://github.com/zangets1/scan_koillection/pkgs/container/scan_koillection)
[![Licence MIT](https://img.shields.io/badge/licence-MIT-green)](LICENSE)

</div>

---

## Ce que ça fait

1. Vous ouvrez la page sur votre téléphone et vous scannez le code-barres au dos du livre.
2. L'ISBN est vérifié (clé de contrôle + double lecture concordante) — pas de faux positifs.
3. Les catalogues sont interrogés **en parallèle** et leurs réponses fusionnées.
4. Une fiche pré-remplie s'affiche : vous corrigez ce que vous voulez, vous cochez **« J'ai lu ce livre »**, vous validez.
5. L'item est créé dans Koillection avec sa couverture ; **si le livre appartient à une série, il est rangé dans une sous-collection à son nom**, créée automatiquement.

Champs remontés dans Koillection : **titre, auteur, éditeur, date de parution, nombre de pages, genre, synopsis, série, tome, langue, ISBN, et la case « Lu »**.

---

## Pourquoi la BnF plutôt que Google Books

| Source | Sans clé | Livres FR | Synopsis FR | Série + tome | Pages |
|---|:--:|:--:|:--:|:--:|:--:|
| **BnF** (SRU / UNIMARC) | ✅ | ✅✅ | ✅ (notices Electre) | ✅ (zone 461) | ✅ |
| **OpenLibrary** | ✅ | ⚠️ partiel | 🇬🇧 anglais | ⚠️ parfois | ✅ |
| **openBD** (Japon) | ✅ | ❌ | 🇯🇵 japonais | ✅ | ⚠️ |
| Google Books | ✅ | ⚠️ irrégulier | ⚠️ | ❌ | ⚠️ souvent faux |

La BnF est interrogée en premier et fait autorité. Les autres ne servent qu'à **combler les champs vides**.
Google Books reste présent en dernier recours et se retire d'une variable : `PROVIDERS=bnf,openlibrary,openbd`.

> **Garde-fou anti-mélange.** Certains ISBN sont attribués à deux ouvrages différents selon les catalogues.
> Si une source secondaire décrit visiblement un autre livre (titre sans rapport **et** aucun auteur commun),
> sa notice est écartée plutôt que fusionnée : mieux vaut un champ vide qu'une fiche chimérique.

---

## Installation sur le NAS

### 1. Docker Compose

```bash
mkdir -p /volume1/docker/scan-koillection && cd $_
curl -O https://raw.githubusercontent.com/zangets1/scan_koillection/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/zangets1/scan_koillection/main/.env.example
nano .env          # renseignez au minimum les trois variables KOILLECTION_*
docker compose up -d
```

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

```bash
curl -O https://raw.githubusercontent.com/zangets1/scan_koillection/main/Caddyfile
docker compose --profile https up -d
```

Rendez-vous sur `https://IP_DU_NAS:8443` et acceptez l'avertissement de sécurité une fois.
Sur iOS, il faut parfois appuyer sur « Afficher les détails » → « visiter ce site web ».
</details>

<details>
<summary><b>b. Un vrai certificat (recommandé si vous avez un domaine)</b></summary>

Remplacez le contenu du `Caddyfile` par :

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

### 3. Ajouter l'application à l'écran d'accueil

C'est une PWA : **Partager → Sur l'écran d'accueil** (iOS) ou **Menu → Installer l'application** (Android).
Elle s'ouvre alors en plein écran, sans barre d'adresse.

---

## Configuration

Tout passe par le fichier `.env` ([modèle commenté](.env.example)).

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
| `PROVIDERS` | `bnf,openlibrary,openbd,googlebooks` | Catalogues et ordre de priorité |
| `PROVIDER_TIMEOUT` | `8` | Délai maximal par catalogue (s) |
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
.venv/bin/python -m pytest                 # 46 tests, sans accès réseau
KOILLECTION_URL=... .venv/bin/uvicorn app.main:app --reload --port 8080
```

### Organisation

```
app/
  main.py         routes FastAPI, sessions, service des fichiers statiques
  lookup.py       appels parallèles aux catalogues, fusion, cache TTL
  providers/      un module par catalogue (bnf, openlibrary, openbd, …)
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

## Crédits et licence

- Données : [BnF – Catalogue général](https://api.bnf.fr/fr/api-sru-catalogue-general),
  [OpenLibrary](https://openlibrary.org/developers/api), [openBD](https://openbd.jp/),
  résumés Electre diffusés par la BnF.
- Décodage : [ZXing pour JavaScript](https://github.com/zxing-js/library) (Apache 2.0), embarqué dans `static/vendor/`.
- [Koillection](https://github.com/benjaminjonard/koillection) de Benjamin Jonard.

Ce projet est sous licence [MIT](LICENSE). Il n'est affilié ni à la BnF ni à Koillection.
