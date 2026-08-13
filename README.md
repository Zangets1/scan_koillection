<div align="center">

# 📚 Scan Koillection

**Scan a book's barcode, it lands in Koillection.**

A self-hosted web app built for a NAS and a phone.
Metadata from the **BnF**, the **SUDOC**, **OpenLibrary** and **openBD** — no reliance on Google Books.

[![CI](https://github.com/zangets1/scan_koillection/actions/workflows/ci.yml/badge.svg)](https://github.com/zangets1/scan_koillection/actions/workflows/ci.yml)
[![Docker image](https://img.shields.io/badge/ghcr.io-scan__koillection-2f6df6)](https://github.com/zangets1/scan_koillection/pkgs/container/scan_koillection)
[![MIT licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)

**English** · [Français](README.fr.md)

</div>

---

## What it does

1. Open the page on your phone and scan the barcode on the back of the book.
2. The ISBN is verified — checksum plus two matching reads in a row, so no false positives.
3. Catalogues are queried **in parallel** and their answers merged — half a second typically, four at the very worst.
4. A pre-filled form appears: correct whatever you like, tick **"I have read this book"**, confirm.
5. The item is created in Koillection with its cover; **if the book belongs to a series, it goes into a sub-collection named after it**, created on the fly.

Fields written to Koillection: **title, author, publisher, publication date, page count, genre, synopsis, series, volume, language, ISBN, and the "Read" checkbox**.

---

## Why the BnF rather than Google Books

This project was built for French-language books, and that choice drives the whole design.

| Source | No API key | French books | French synopsis | Series + volume | Genre |
|---|:--:|:--:|:--:|:--:|:--:|
| **BnF** (SRU / UNIMARC) | ✅ | ✅✅ | ✅ (Electre records) | ✅ (field 461) | ✅ |
| **SUDOC** (French academic libraries) | ✅ | ✅✅ | ✅ (back cover) | ✅ (field 200) | ✅✅ |
| **OpenLibrary** | ✅ | ⚠️ partial | 🇬🇧 English | ⚠️ sometimes | ⚠️ keywords |
| **K10plus** (MARC21) | ✅ | — English-language only | ❌ | ✅ (field 830) | ❌ |
| **openBD** (Japan) | ✅ | ❌ | 🇯🇵 Japanese | ✅ | ⚠️ |
| Google Books | ✅ | ⚠️ inconsistent | ⚠️ | ❌ | ⚠️ |

The BnF is queried first and takes precedence. The others only **fill in the blanks**.
Google Books is a last resort and can be dropped with one variable: `PROVIDERS=bnf,sudoc,openbd`.

**Why SUDOC comes second.** Measured across 18 French books, it turns up almost no title the
BnF misses — but it fills the synopsis on **4 more books** and the genre on **8 more**, with
far more useful labels ("Manga", "Shōnen" instead of "Comics"). It also acts as a spare
wheel: the BnF's SRU service drops connections intermittently, and SUDOC covers for it.

### Each catalogue only where it can answer

The first digits of an ISBN identify the agency that registered the publisher, and therefore
the book's language area. A catalogue is only queried for the areas it covers:

| Area | Prefixes | Catalogues queried |
|---|---|---|
| French-language | `978-2`, `979-10` | BnF, SUDOC, OpenLibrary, Google Books |
| English-language | `978-0`, `978-1`, `979-8` | SUDOC, OpenLibrary, K10plus, Google Books |
| Japan | `978-4` | SUDOC, OpenLibrary, openBD, Google Books |

Measured across 87 ISBNs, the BnF holds **one English-language book out of fifty-five**:
querying it for an English novel opened a connection whose answer was known in advance.
Since catalogues run in parallel, total time is the slowest one — dropping two therefore
**shortens** the lookup: −0.7 s on an English scan, −0.3 s on a French one.

An unrecognised area excludes nobody: for an ISBN whose group is not listed, everyone is
queried, exactly as before.

> **No, the ISBN does not tell you the country.** `978-0` and `978-1` form a **single**
> "English language" group shared by the UK, the US, Australia and Ireland. No barcode can
> separate a British edition from an American one: `978-0-7475-3274-3` is Bloomsbury's Harry
> Potter in London, `978-0-590-35340-3` is Scholastic's in New York. Only the catalogue record
> carries the country of publication — K10plus supplies it for roughly one English-language
> book in five, and the API returns it in the `country` field. That is too rare to deserve a
> box in the form.

**Why K10plus for English-language books.** The union catalogue of German libraries is well
stocked in Anglo-American editions, speaks MARC21, and needs no key or quota. Measured across
55 English-language ISBNs it turns up **no** book OpenLibrary misses, but it fills the page
count (73 % → 84 %) and the series (17 % → 24 %). Its summary and genre fields are discarded:
their language depends on whichever library wrote the record, German or English, and nothing
in the format says which. It stays confined to English-language ISBNs — on `978-2` codes it
fills nothing the BnF and SUDOC do not already have, at the cost of one more connection.

> **Guard against mixed-up records.** Some ISBNs are assigned to two different works
> depending on the catalogue. When a secondary source clearly describes another book
> (unrelated title **and** no author in common), its record is discarded rather than merged:
> an empty field beats a chimera.

If you mostly collect English-language books, reorder the sources —
`PROVIDERS=openlibrary,bnf,sudoc,googlebooks` — or plug in your own catalogue, see
[Adding a catalogue](#adding-a-catalogue).

---

## Installing on a NAS

### 1. Docker Compose

The [`docker-compose.yml`](docker-compose.yml) **stands on its own**: configuration lives
inside it rather than in a neighbouring `.env`. It can therefore be pasted as-is into the
Docker UI of a NAS (UGREEN, Synology, QNAP…) that offers no way to drop extra files.

It reaches Koillection **by container name** (`http://koillection:80`), which assumes a
shared Docker network. So there is exactly one thing to check before starting: the name of
your Koillection network, at the bottom of the file.

```bash
docker network ls        # look for « koillection_default » or its equivalent
```

```yaml
networks:
  koillection:
    external: true
    name: koillection_default    # the name you just found
```

Get it wrong and Compose refuses to start with an unambiguous message
(`network … declared as external, but could not be found`) — you won't be left staring at
an empty collection list wondering why.

> **Rather avoid network configuration?** Just point `KOILLECTION_URL` at your NAS IP and
> the port Koillection publishes (`http://192.168.1.10:81`), then drop the `networks` block
> along with the two `networks:` lines on the service.

The remaining values to fill in: your Koillection credentials, `PUID`/`PGID`, and the NAS
address for HTTPS.

From a terminal:

```bash
mkdir -p /volume1/docker/scan-koillection && cd $_
curl -O https://raw.githubusercontent.com/zangets1/scan_koillection/main/docker-compose.yml
nano docker-compose.yml     # the lines marked « À RENSEIGNER »
docker compose --profile https up -d
```

> Prefer a separate `.env`? Replace the `environment:` block with `env_file: [.env]` and
> start from [`.env.example`](.env.example), which documents **every** available variable.

The interface answers on `http://YOUR_NAS_IP:8080`.

### 2. The part that trips everyone up: HTTPS

**iOS and Android both refuse camera access on an `http://` page** (except on `localhost`).
On `http://192.168.1.x:8080`, typing the ISBN by hand will work, but scanning will not.

Three ways out, from quickest to cleanest:

<details>
<summary><b>a. The bundled reverse proxy (Caddy, self-signed certificate)</b></summary>

It is already in the `docker-compose.yml`. Set `NAS_HOST` to **exactly** the address you
will type in the browser — the certificate is issued for it — then:

```bash
docker compose --profile https up -d
```

Go to `https://YOUR_NAS_IP:8443` and accept the security warning once. On iOS you sometimes
need to tap "Show details" → "visit this website".

No config file to create: Caddy writes its own at startup. The [`Caddyfile`](Caddyfile) in
the repository is only there if you prefer a separate file.
</details>

<details>
<summary><b>b. A real certificate (recommended if you own a domain)</b></summary>

Use the repository's [`Caddyfile`](Caddyfile), mounted into the Caddy container in place of
the `command:` block, containing:

```
scan.mydomain.com {
    reverse_proxy scan-koillection:8080
}
```

Caddy obtains and renews the Let's Encrypt certificate on its own. Most NAS boxes
(Synology, UGREEN, TrueNAS) can also do this from their own reverse proxy.
</details>

<details>
<summary><b>c. Tailscale / WireGuard</b></summary>

With Tailscale, `tailscale serve` gives you a `*.ts.net` name and a valid certificate
without exposing anything to the internet.
</details>

### 3. Create a collection in Koillection

The scanner never creates a root collection: it files books into the one you pick. Create
one ("Books", "Manga"…) in Koillection before your first scan, otherwise the dropdown stays
empty.

A collection added while the scanner is running shows up **within a minute**, or right away
via the **"⟳ Recharger depuis Koillection"** button below the list. The list is cached for
one minute so the API isn't queried on every page view.

> **List still empty?** The **"Diagnostiquer la connexion"** button walks the chain
> step by step and names the exact cause:
>
> ```
> ✓ Configuration — http://192.168.1.10:81
> ✓ Koillection joignable — Réponse HTTP 200.
> ✓ Identifiants acceptés — Connecté en tant que « damien ».
> ✗ Collections visibles — Le compte « damien » n'a aucune collection.
> ```
>
> The usual traps:
>
> - **`http://koillection:80` without a shared network.** Every Compose stack creates its
>   own: the Koillection container name simply doesn't resolve from the scanner.
> - **`localhost` or `127.0.0.1`**, which from inside the container means the container
>   itself, not the NAS.
> - **A collection created under a different Koillection account**: it belongs to its
>   creator and stays invisible to other accounts.
>
> `KOILLECTION_DEFAULT_COLLECTION` is never the culprit: that variable pre-selects an entry
> in the list, it does not filter it.

#### Container name won't resolve?

`http://koillection:80` only works when both stacks share a network. Check the `networks`
block at the end of `docker-compose.yml`, and that the container really joined both:

```bash
docker inspect scan-koillection --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'
# → koillection_default scan_default
```

### 4. Add the app to your home screen

It's a PWA: **Share → Add to Home Screen** (iOS) or **Menu → Install app** (Android). It
then opens full screen, with no address bar.

> **Interface language.** The app itself is in French. Everything it writes into Koillection
> comes from the catalogues, so an English-language book yields English metadata. Field
> labels are renamable through `FIELD_LABELS`, see below.

---

## Configuration

Everything goes through environment variables, declared either straight in
`docker-compose.yml` or in a separate `.env` ([commented template](.env.example)).

### The essentials

| Variable | Purpose |
|---|---|
| `KOILLECTION_URL` | Koillection URL **as seen from inside the container** |
| `KOILLECTION_USERNAME` / `KOILLECTION_PASSWORD` | Account used against the API |
| `KOILLECTION_DEFAULT_COLLECTION` | Collection offered by default (title, path or UUID) |
| `APP_PASSWORD` | Password guarding the interface (empty = open) |

### The rest

| Variable | Default | Purpose |
|---|---|---|
| `PROVIDERS` | `bnf,sudoc,openlibrary,openbd,googlebooks` | Catalogues, in priority order |
| `PROVIDER_TIMEOUT` | `8` | Per-catalogue timeout (s) |
| `LOOKUP_DEADLINE` | `4` | Overall ceiling for one lookup (s) |
| `SERIES_SUBCOLLECTIONS` | `1` | Create one sub-collection per series |
| `SERIES_ITEM_NAME` | `{series} - T{volume:02d} - {title}` | Item name for a book in a series |
| `GENRES_AS_TAGS` | `1` | Also create genres as Koillection tags |
| `UPLOAD_COVER` | `1` | Upload the cover image |
| `FIELD_LABELS` | — | Rename the fields created (JSON) |
| `CACHE_TTL` | `86400` | In-memory lookup cache (s) |
| `SESSION_SECRET` | — | Session signing key |
| `PUID` / `PGID` | `10001` | Owner of the `./data` folder (see below) |

> **Permissions on `./data`.** The container does not run as root. At startup it aligns the
> volume's owner with `PUID:PGID`. If your NAS mandates a specific user (often `1000:1000`,
> `1026:100` on Synology), set it: this is the number one cause of a container refusing to
> start with "impossible d'écrire l'historique".

### Matching the field names to your Koillection

If your records already use "Writer" rather than "Auteur":

```env
FIELD_LABELS={"authors":"Writer","published":"Published","read":"Finished"}
```

An empty value removes the field entirely: `FIELD_LABELS={"language":"","source":""}`.

> The publication date is written as **text**, not as a "date" type: the BnF usually only
> provides the year, and Koillection rejects an incomplete date. The field therefore keeps
> the same type from one book to the next, and still sorts correctly (`2013` < `2016-04`).

---

## How long does a lookup take

Measured across 18 French books, cache cleared, all five catalogues enabled:

| | median | 9 times out of 10 | worst case |
|---|:--:|:--:|:--:|
| Full lookup | **0.6 s** | 1.1 s | 4.0 s |

Catalogues are queried **all at once**: total time is the slowest one, not the sum. Adding a
source therefore costs nothing as long as it answers in time — going from four to five
catalogues cost 0.13 s of median.

The converse holds too, and that is what makes routing by language area pay off: **dropping**
a source removes a candidate for the "slowest" title. Compared across three servers measured
in alternation on the same ISBNs, paired book by book:

| | requests per scan | difference |
|---|:--:|:--:|
| English scan, before | 5 | baseline |
| English scan, after | 3 | **−0.7 s** |
| French scan, before | 5 | baseline |
| French scan, after | 4 | **−0.3 s** |

The worst case is no accident: it is `LOOKUP_DEADLINE`. Past that, the form appears with
whatever arrived and the stragglers are marked "trop lent" next to the sources. Nobody waits
indefinitely in front of a bookshelf because a remote server hiccuped.

---

## The scanner

- **Two engines.** The browser's `BarcodeDetector` API where it exists (Android), otherwise
  **ZXing** in JavaScript — the latter is what carries iOS, where Safari still doesn't
  implement `BarcodeDetector`.
- **Cropped decoding.** Only the central band of the frame is analysed: faster, and it
  avoids catching the barcode of the book next to it.
- **Three-stage validation.** EAN-13 checksum → Bookland prefix (978/979) → **two identical
  reads in a row**. A magazine ISSN (977) or a supermarket barcode is rejected with a plain
  explanation instead of being looked up in vain.
- **Physical confirmation.** Vibration, beep, and the frame turning green.
- **Torch** where the device exposes it (Android).
- **Always a way out.** The ISBN field sits at the top of the first page, and the "type the
  ISBN" button stays reachable from the scanning screen.

### When the book can't be found

No catalogue knows the ISBN? The form still opens, empty, inviting you to fill in title and
author. Everything else is optional, the "Read" checkbox is there, and the item reaches
Koillection like any other.

Above all, **the number actually read is shown large**, in monospaced digits grouped in
threes: enough to compare it against the one printed on the book and tell straight away
whether the scanner misread or the book is simply absent from the databases. Two buttons
follow — **rescan** and **fix the number**, which returns to the home screen with the code
ready to edit.

The grouping deliberately avoids hyphens: real ISBN hyphenation depends on publisher prefix
ranges, and an invented split (`978-2-72-348989-8` instead of `978-2-7234-8989-8`) would
defeat the very comparison it is meant to help. An ISBN-10 read off an older book is shown
as-is, next to its ISBN-13 conversion.

The **"Saisir le livre à la main"** button on the home screen opens the same form with no
ISBN at all (old books, editions without a barcode).

---

## Duplicate detection

Before each creation, items in the destination collection are compared on their ISBN field.
If the book is already there, a confirmation appears with a link to the existing record.

> **A known limit.** Koillection's API exposes no search filter, so the check is confined to
> the target collection (and its series sub-collection). The same book filed elsewhere won't
> be caught. The local history, on the other hand, flags any ISBN the tool has seen before.

---

## Development

```bash
git clone https://github.com/zangets1/scan_koillection.git
cd scan_koillection
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest pytest-asyncio
.venv/bin/python -m pytest                 # 79 tests, no network access
KOILLECTION_URL=... .venv/bin/uvicorn app.main:app --reload --port 8080
```

### Layout

```
app/
  main.py         FastAPI routes, sessions, static file serving
  lookup.py       parallel catalogue calls, time ceiling, merging, cache
  providers/      one module per catalogue, plus `unimarc.py` shared between
                  the BnF and SUDOC (same format, different XML wrapper)
  koillection.py  Koillection API client (JWT, collections, items, data)
  importer.py     turns a book record into a Koillection item and its fields
  series.py       series/volume extraction from a title
  isbn.py         validation, ISBN-10 ↔ ISBN-13 conversion
  covers.py       cover resolution (allow-list + real verification)
static/           the PWA: one page, one CSS, one JS, ZXing vendored in
tests/            unit tests plus real BnF fixtures
```

Source comments and the changelog are in French, as is the interface. Contributions in
English are welcome all the same — say so in your pull request and we'll sort out the
wording together.

### Adding a catalogue

Create `app/providers/my_catalogue.py`, subclass `Provider`, return a `BookMeta`, register
the class in `build_providers()` and add its name to `PROVIDERS`. A provider that fails is
simply ignored: it cannot hold up a lookup.

Declare `groups` if the catalogue only covers part of the world — it will then be queried
for those areas only (`fr`, `en`, `ja`, `de`, `es`, `it`, `ru`, `zh`, `ko`):

```python
class MyCatalogue(Provider):
    name = "my_catalogue"
    label = "My catalogue"
    groups = frozenset({"en"})   # omit the attribute for every area
```

Two readers for library records already exist: `unimarc.py` for French-language catalogues
(BnF, SUDOC) and `marc21.py` for Anglo-American and German ones (K10plus, Library of
Congress). Both describe the same books, but the fields do not carry the same numbers.

### Trying a branch before merging it

Pushing to a `v*` branch publishes an image named after it, for example
`ghcr.io/zangets1/scan_koillection:v2`. It is built for both amd64 and arm64, and
**`:latest` is never touched**: your production install cannot pick it up through a
`docker compose pull`.

Run it alongside the existing one, on a different port and data directory:

```yaml
services:
  scan-koillection-test:
    image: ghcr.io/zangets1/scan_koillection:v2
    ports: ["8081:8080"]
    volumes: ["./data-test:/data"]
    env_file: .env
```

`GET /healthz` returns the exact version (`v2-<commit>`), so you can check what is actually
running. The workflow can also be re-run by hand from **Actions → Image d'essai**.

### What about the Library of Congress?

It is the only genuine US national catalogue available without a key, and `marc21.py`
already knows how to read its records. But it only exposes SRU on
`http://lx2.loc.gov:210/LCDB` — in the clear, on a non-standard port that many home networks
filter. Before writing the provider, check that it answers **from the machine that will make
the requests**:

```bash
python3 tools/test-loc.py
```

The script has no dependencies and changes nothing: it opens a connection, looks up three
sample ISBNs and prints what it gets back.

---

## Versions and rolling back

Every version ships as a **GitHub release** with a tagged Docker image. An update went
badly? Go back in one line:

```yaml
image: ghcr.io/zangets1/scan_koillection:1.0.0   # instead of :latest
```

```bash
docker compose up -d
```

The `:latest`, `:1`, `:1.0` and `:1.0.0` tags are all maintained. The `./data` folder
(history) is compatible across versions, and no Koillection data is touched by a rollback.

**Branches.** `main` carries the published stable version; development happens on dedicated
branches merged into `main` afterwards. See the [CHANGELOG](CHANGELOG.md).

**Publishing a version.** Either way works:

- from GitHub: **Actions → Release → Run workflow**, enter `v1.0.0`;
- from a terminal: `git tag -a v1.0.0 -m "…" && git push origin v1.0.0`.

Both build the `amd64` + `arm64` image, push it to GHCR and create the GitHub release with
its notes.

---

## Reporting a problem

[Issues](https://github.com/zangets1/scan_koillection/issues) are open. Two forms guide the
report and ask up front for what is almost always missing: the version, and the output of
the **"Diagnostiquer la connexion"** button.

Every new issue gets a **first automated analysis**: what kind of request it is, whether it
is already fixed in a published version, known configuration causes, and what information is
missing. That analysis never touches the code.

Fixes only start **at a maintainer's request** — the `claude-fix` label or an `@claude`
comment — and always end in a reviewed pull request, never a direct commit on `main`.

<details>
<summary><b>Enabling the automation on your own fork</b></summary>

Both workflows stay dormant until the secret exists: they stop at the first step and say so,
without failing anything.

1. **Settings → Secrets and variables → Actions → New repository secret**
   named `ANTHROPIC_API_KEY` ([create a key here](https://console.anthropic.com/settings/keys)).
2. For assisted fixing, create the `claude-fix` label (it can also be created on the fly by
   applying it to an issue).

The analysis burns API tokens on every issue opened: on a public repository, that is spending
anyone can trigger. Triage is deliberately short to limit it, but keep an eye on consumption
and pull the secret if it runs away.

</details>

---

## Credits and licence

- Data: [BnF – Catalogue général](https://api.bnf.fr/fr/api-sru-catalogue-general),
  [SUDOC / ABES](https://abes.fr/reseau-sudoc/documentation-technique/),
  [OpenLibrary](https://openlibrary.org/developers/api), [openBD](https://openbd.jp/),
  Electre summaries distributed by the BnF.
- Decoding: [ZXing for JavaScript](https://github.com/zxing-js/library) (Apache 2.0),
  vendored in `static/vendor/`.
- [Koillection](https://github.com/benjaminjonard/koillection) by Benjamin Jonard.

This project is released under the [MIT licence](LICENSE). It is affiliated with neither the
BnF nor Koillection.
