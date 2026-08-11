/* Scan Koillection — interface unique (aucune dépendance hors ZXing). */
'use strict';

// ═══ Utilitaires ════════════════════════════════════════════════════════
const $ = (id) => document.getElementById(id);

const state = {
  config: null,
  collections: [],
  collectionId: localStorage.getItem('collection') || '',
  book: null,
  //: Ce qui a été lu ou saisi, conservé pour être affiché sur la fiche
  scan: null,
  continuous: false,
};

function show(view) {
  for (const section of document.querySelectorAll('.view')) section.hidden = true;
  $(view).hidden = false;
  window.scrollTo(0, 0);
}

let toastTimer = null;
function toast(message, isError = false) {
  const node = $('toast');
  node.textContent = message;
  node.classList.toggle('error', isError);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, isError ? 5200 : 3000);
}

function busy(label) {
  $('busy-label').textContent = label || 'Patientez…';
  $('busy').hidden = false;
}
function idle() { $('busy').hidden = true; }

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    ...options,
  });
  if (response.status === 401 && state.config && state.config.auth_required) {
    show('view-login');
    throw new Error('Session expirée, reconnectez-vous.');
  }
  let payload = null;
  try { payload = await response.json(); } catch { /* réponse vide */ }
  if (!response.ok) {
    throw new Error((payload && (payload.detail || payload.message)) || `Erreur ${response.status}`);
  }
  return payload;
}

// ═══ ISBN : validation côté navigateur ══════════════════════════════════
// Le serveur revalide systématiquement ; ce contrôle sert au retour immédiat
// pendant la saisie et à filtrer les mauvaises lectures du scanner.
function cleanIsbn(raw) {
  return String(raw || '').replace(/[^0-9Xx]/g, '').toUpperCase();
}

function isValidIsbn13(value) {
  if (!/^\d{13}$/.test(value)) return false;
  let sum = 0;
  for (let i = 0; i < 13; i += 1) sum += Number(value[i]) * (i % 2 === 0 ? 1 : 3);
  return sum % 10 === 0;
}

function isValidIsbn10(value) {
  if (!/^\d{9}[\dX]$/.test(value)) return false;
  let sum = 0;
  for (let i = 0; i < 10; i += 1) {
    const digit = value[i] === 'X' ? 10 : Number(value[i]);
    sum += (10 - i) * digit;
  }
  return sum % 11 === 0;
}

function toIsbn13(value) {
  if (isValidIsbn13(value)) return value;
  if (!isValidIsbn10(value)) return null;
  const core = `978${value.slice(0, 9)}`;
  let sum = 0;
  for (let i = 0; i < 12; i += 1) sum += Number(core[i]) * (i % 2 === 0 ? 1 : 3);
  return core + String((10 - (sum % 10)) % 10);
}

/** Renvoie `{ isbn }` ou `{ error }` — messages destinés à l'utilisateur. */
function checkIsbn(raw) {
  const value = cleanIsbn(raw);
  if (!value) return { error: '' };
  if (value.length === 13) {
    if (!isValidIsbn13(value)) return { error: 'Clé de contrôle incorrecte : vérifiez un chiffre.' };
    if (value.startsWith('977')) return { error: "Ce code est celui d'une revue (ISSN), pas d'un livre." };
    if (!value.startsWith('978') && !value.startsWith('979')) {
      return { error: "Ce code-barres n'est pas un ISBN (il doit commencer par 978 ou 979)." };
    }
    return { isbn: value };
  }
  if (value.length === 10) {
    const converted = toIsbn13(value);
    if (!converted) return { error: 'Clé de contrôle ISBN-10 incorrecte.' };
    return { isbn: converted };
  }
  return { error: `${value.length} chiffre(s) sur 10 ou 13.` };
}

/**
 * Met les chiffres en paquets de trois pour les relire sans se perdre.
 *
 * Volontairement sans tirets : la vraie césure d'un ISBN dépend de tables de
 * préfixes d'éditeurs, et un découpage inventé (978-2-72-348989-8 au lieu de
 * 978-2-7234-8989-8) gênerait justement la comparaison avec le livre.
 */
function groupDigits(value) {
  return cleanIsbn(value).replace(/(.{3})(?=.)/g, '$1 ');
}

// ═══ Scanner ════════════════════════════════════════════════════════════
const scanner = {
  stream: null,
  track: null,
  reader: null,
  detector: null,
  timer: null,
  canvas: null,
  ctx: null,
  reads: new Map(),
  running: false,
  torchOn: false,
};

/** Nombre de lectures identiques exigées avant d'accepter un code. */
const REQUIRED_READS = 2;
/** Intervalle entre deux tentatives de décodage (ms). */
const SCAN_INTERVAL = 120;

function scanStatus(message) { $('scan-status').textContent = message; }

function feedback() {
  if (navigator.vibrate) navigator.vibrate([40, 30, 40]);
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const audio = new Ctx();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = 1150;
    gain.gain.setValueAtTime(0.0001, audio.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.25, audio.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.16);
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + 0.18);
    setTimeout(() => audio.close(), 400);
  } catch { /* le son n'est qu'un confort */ }
}

function buildZXingReader() {
  if (typeof ZXing === 'undefined') return null;
  const hints = new Map();
  hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
    ZXing.BarcodeFormat.EAN_13,
    ZXing.BarcodeFormat.EAN_8,
    ZXing.BarcodeFormat.UPC_A,
    ZXing.BarcodeFormat.UPC_E,
  ]);
  hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
  const reader = new ZXing.MultiFormatReader();
  reader.setHints(hints);
  return reader;
}

async function startScanner() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast(
      "Caméra inaccessible : les navigateurs mobiles l'exigent en HTTPS. Saisissez l'ISBN à la main.",
      true,
    );
    return;
  }

  show('view-scan');
  scanStatus('Ouverture de la caméra…');
  scanner.reads.clear();
  $('scan-frame').classList.remove('hit');

  try {
    scanner.stream = await navigator.mediaDevices.getUserMedia({
      video: {
        facingMode: { ideal: 'environment' },
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
      audio: false,
    });
  } catch (error) {
    stopScanner();
    show('view-home');
    const denied = error && (error.name === 'NotAllowedError' || error.name === 'SecurityError');
    toast(
      denied
        ? "Accès caméra refusé. Autorisez-le dans les réglages du navigateur, ou saisissez l'ISBN."
        : `Caméra indisponible (${error.name || error}). Saisissez l'ISBN à la main.`,
      true,
    );
    return;
  }

  const video = $('video');
  video.setAttribute('playsinline', 'true');
  video.srcObject = scanner.stream;
  try { await video.play(); } catch { /* iOS relance seul après le geste */ }

  scanner.track = scanner.stream.getVideoTracks()[0];
  // Mise au point continue : sans elle, les codes-barres restent flous de près.
  try {
    await scanner.track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
  } catch { /* non géré par iOS */ }

  const capabilities = scanner.track.getCapabilities ? scanner.track.getCapabilities() : {};
  $('btn-torch').hidden = !('torch' in capabilities);
  scanner.torchOn = false;

  if (!scanner.canvas) {
    scanner.canvas = document.createElement('canvas');
    scanner.ctx = scanner.canvas.getContext('2d', { willReadFrequently: true });
  }

  if ('BarcodeDetector' in window) {
    try {
      const formats = await window.BarcodeDetector.getSupportedFormats();
      if (formats.includes('ean_13')) {
        scanner.detector = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a'] });
      }
    } catch { scanner.detector = null; }
  }
  if (!scanner.detector) scanner.reader = buildZXingReader();

  if (!scanner.detector && !scanner.reader) {
    stopScanner();
    show('view-home');
    toast("Moteur de décodage indisponible. Saisissez l'ISBN à la main.", true);
    return;
  }

  scanner.running = true;
  scanStatus('Placez le code-barres dans le cadre');
  scanLoop();
}

function stopScanner() {
  scanner.running = false;
  clearTimeout(scanner.timer);
  scanner.timer = null;
  if (scanner.stream) {
    for (const track of scanner.stream.getTracks()) track.stop();
    scanner.stream = null;
  }
  scanner.track = null;
  scanner.detector = null;
  scanner.reader = null;
  const video = $('video');
  video.pause();
  video.srcObject = null;
  $('btn-torch').hidden = true;
}

/** Recadre la bande centrale de l'image : plus rapide et bien plus fiable. */
function grabFrame() {
  const video = $('video');
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) return null;

  const cropWidth = Math.round(width * 0.86);
  const cropHeight = Math.round(height * 0.42);
  const left = Math.round((width - cropWidth) / 2);
  const top = Math.round((height - cropHeight) / 2);

  const scale = Math.min(1, 1024 / cropWidth);
  scanner.canvas.width = Math.round(cropWidth * scale);
  scanner.canvas.height = Math.round(cropHeight * scale);
  scanner.ctx.drawImage(
    video, left, top, cropWidth, cropHeight,
    0, 0, scanner.canvas.width, scanner.canvas.height,
  );
  return scanner.canvas;
}

async function decodeFrame(canvas) {
  if (scanner.detector) {
    const codes = await scanner.detector.detect(canvas);
    return codes.length ? codes[0].rawValue : null;
  }
  try {
    const source = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
    const bitmap = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(source));
    return scanner.reader.decode(bitmap).getText();
  } catch {
    return null; // NotFoundException : image sans code-barres, cas normal
  } finally {
    if (scanner.reader) scanner.reader.reset();
  }
}

async function scanLoop() {
  if (!scanner.running) return;
  try {
    const canvas = grabFrame();
    if (canvas) {
      const raw = await decodeFrame(canvas);
      if (raw) handleRead(raw);
    }
  } catch (error) {
    console.warn('Décodage interrompu', error);
  }
  if (scanner.running) scanner.timer = setTimeout(scanLoop, SCAN_INTERVAL);
}

function handleRead(raw) {
  const check = checkIsbn(raw);
  if (check.error) {
    scanner.reads.clear();
    scanStatus(`Code lu (${cleanIsbn(raw)}) — ${check.error}`);
    return;
  }
  if (!check.isbn) return;

  const count = (scanner.reads.get(check.isbn) || 0) + 1;
  scanner.reads.clear();          // deux lectures d'affilée, pas deux au total
  scanner.reads.set(check.isbn, count);

  if (count < REQUIRED_READS) {
    scanStatus(`Vérification… (${count}/${REQUIRED_READS})`);
    return;
  }

  $('scan-frame').classList.add('hit');
  scanStatus(`ISBN ${check.isbn} — trouvé !`);
  feedback();
  stopScanner();
  lookup(check.isbn, { raw: cleanIsbn(raw), manual: false });
}

async function toggleTorch() {
  if (!scanner.track) return;
  try {
    scanner.torchOn = !scanner.torchOn;
    await scanner.track.applyConstraints({ advanced: [{ torch: scanner.torchOn }] });
    $('btn-torch').textContent = scanner.torchOn ? '🔦 Éteindre' : '🔦 Lampe';
  } catch {
    toast('Lampe non pilotable sur cet appareil.', true);
  }
}

// ═══ Recherche et formulaire ════════════════════════════════════════════
async function lookup(isbn13, origin = { raw: '', manual: true }) {
  state.scan = { isbn13, raw: origin.raw || isbn13, manual: Boolean(origin.manual) };
  busy('Interrogation des catalogues…');
  try {
    const result = await api(`/api/lookup/${isbn13}`);
    idle();
    if (result.found && result.book) {
      fillForm(result.book, result);
    } else {
      fillForm(
        { isbn13, title: '', authors: [] },
        result,
        'Aucun catalogue ne connaît ce numéro. Comparez-le d’abord avec celui imprimé '
        + 'sur le livre : s’il correspond, renseignez le titre et l’auteur à la main.',
      );
      setTimeout(() => $('f-title').focus(), 150);
    }
    show('view-book');
  } catch (error) {
    idle();
    toast(error.message, true);
    show('view-home');
  }
}

function manualEntry(isbn13 = '') {
  state.book = null;
  state.scan = isbn13 ? { isbn13, raw: isbn13, manual: true } : null;
  fillForm({ isbn13, title: '', authors: [] }, null, 'Saisie manuelle : le titre et l’auteur suffisent.');
  show('view-book');
  setTimeout(() => $('f-title').focus(), 150);
}

function fillForm(book, result, banner) {
  state.book = book;

  $('f-title').value = book.title || '';
  $('f-authors').value = (book.authors || []).join(', ');
  $('f-publisher').value = book.publisher || '';
  $('f-date').value = book.published_date || '';
  $('f-pages').value = book.page_count || '';
  $('f-language').value = book.language || '';
  $('f-genres').value = (book.genres || []).join(', ');
  $('f-series').value = book.series || '';
  $('f-volume').value = book.volume != null ? book.volume : '';
  $('f-synopsis').value = book.synopsis || '';
  $('f-read').checked = false;

  renderScannedCode(book, result);
  $('book-heading').textContent = book.title ? book.title : 'Nouveau livre';

  const sources = result && result.providers
    ? Object.entries(result.providers)
      .filter(([, status]) => status === 'trouvé')
      .map(([name]) => name)
    : [];
  $('book-sources').textContent = sources.length
    ? `Source : ${sources.join(', ')}${result.elapsed_ms ? ` · ${result.elapsed_ms} ms` : ''}`
    : 'Aucune source automatique';

  const cover = $('book-cover');
  if (book.isbn13 && result && result.found) {
    cover.hidden = false;
    cover.src = `/api/cover/${book.isbn13}`;
    cover.onerror = () => { cover.hidden = true; };
  } else {
    cover.hidden = true;
    cover.removeAttribute('src');
  }

  const message = banner || (result && result.message) || '';
  $('book-banner-card').hidden = !message;
  $('book-banner').textContent = message;
  $('book-banner').classList.toggle('info', Boolean(banner));

  $('book-error').hidden = true;
  fillCollectionSelect($('f-collection'));
  updateSeriesHint();
}

/**
 * Affiche le code réellement lu, groupé comme sur la quatrième de couverture.
 *
 * Quand aucun catalogue ne répond, c'est la seule façon de savoir si le
 * lecteur s'est trompé ou si le livre est simplement absent des bases : il
 * suffit de comparer les chiffres à l'écran avec ceux imprimés sur le livre.
 */
function renderScannedCode(book, result) {
  const scan = state.scan;
  const code = (scan && scan.isbn13) || book.isbn13 || '';
  const found = Boolean(result && result.found);

  const label = $('code-label');
  const value = $('book-isbn');
  const detail = $('code-detail');
  const actions = $('code-actions');

  if (!code) {
    label.textContent = 'Sans ISBN';
    value.textContent = '—';
    value.classList.remove('warn');
    detail.hidden = true;
    actions.hidden = true;
    return;
  }

  label.textContent = scan && !scan.manual ? 'Code-barres lu' : 'ISBN saisi';
  value.textContent = groupDigits(code);
  value.classList.toggle('warn', !found);

  // Un ISBN-10 lu au dos d'un livre ancien est converti : on montre les deux
  // pour que la comparaison avec le livre reste possible.
  const raw = scan && cleanIsbn(scan.raw);
  if (raw && raw !== code) {
    detail.textContent = `Lu sur le livre : ${groupDigits(raw)} — ISBN-10, converti en ISBN-13.`;
    detail.hidden = false;
  } else {
    detail.hidden = true;
  }

  // Les corrections n'ont d'intérêt que si la recherche a échoué.
  actions.hidden = found;
}

function updateSeriesHint() {
  const series = $('f-series').value.trim();
  const hint = $('series-hint');
  if (!state.config || !state.config.series_subcollections) {
    hint.textContent = series
      ? 'La série est enregistrée comme champ, sans sous-collection (option désactivée).'
      : '';
    return;
  }
  hint.textContent = series
    ? `Le livre ira dans la sous-collection « ${series} », créée si besoin.`
    : 'Sans série renseignée, le livre est ajouté directement dans la collection choisie.';
}

function readForm() {
  const list = (value) => value.split(',').map((part) => part.trim()).filter(Boolean);
  const number = (value) => (value === '' ? null : Number(value));
  return {
    isbn13: (state.book && state.book.isbn13) || '',
    title: $('f-title').value.trim(),
    authors: list($('f-authors').value),
    publisher: $('f-publisher').value.trim() || null,
    published_date: $('f-date').value.trim() || null,
    page_count: number($('f-pages').value),
    genres: list($('f-genres').value),
    synopsis: $('f-synopsis').value.trim() || null,
    series: $('f-series').value.trim() || null,
    volume: number($('f-volume').value),
    language: $('f-language').value.trim() || null,
    cover_url: (state.book && (state.book.cover_url || (state.book.cover_candidates || [])[0])) || null,
    source_url: (state.book && state.book.source_url) || null,
    read: $('f-read').checked,
    collection: $('f-collection').value || null,
  };
}

async function submitBook(event) {
  event.preventDefault();
  const payload = readForm();
  const error = $('book-error');

  if (!payload.title) {
    error.textContent = 'Le titre est obligatoire.';
    error.hidden = false;
    $('f-title').focus();
    return;
  }
  if (!payload.authors.length) {
    error.textContent = "Renseignez au moins un auteur.";
    error.hidden = false;
    $('f-authors').focus();
    return;
  }
  if (!payload.collection) {
    error.textContent = 'Choisissez une collection de destination.';
    error.hidden = false;
    return;
  }
  error.hidden = true;

  await sendBook(payload);
}

async function sendBook(payload) {
  busy('Envoi vers Koillection…');
  try {
    const result = await api('/api/add', { method: 'POST', body: JSON.stringify(payload) });
    idle();

    if (result.duplicate) {
      const confirmed = window.confirm(
        `${result.message}\n\nL'ajouter quand même ?`,
      );
      if (!confirmed) {
        if (result.duplicate_of) window.open(result.duplicate_of, '_blank', 'noopener');
        return;
      }
      await sendBook({ ...payload, force: true });
      return;
    }

    $('done-title').textContent = payload.read ? 'Livre ajouté et marqué comme lu' : 'Livre ajouté';
    $('done-message').textContent = result.message || '';
    const link = $('done-link');
    if (result.item_url) {
      link.href = result.item_url;
      link.hidden = false;
    } else {
      link.hidden = true;
    }
    show('view-done');
    loadHistory();
  } catch (err) {
    idle();
    const error = $('book-error');
    error.textContent = err.message;
    error.hidden = false;
    toast(err.message, true);
  }
}

// ═══ Collections et historique ══════════════════════════════════════════
function fillCollectionSelect(select) {
  select.innerHTML = '';
  if (!state.collections.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Aucune collection trouvée';
    select.append(option);
    return;
  }
  for (const collection of state.collections) {
    const option = document.createElement('option');
    option.value = collection.iri;
    option.textContent = collection.path;
    select.append(option);
  }
  select.value = state.collectionId || state.collections[0].iri;
  state.collectionId = select.value;
}

/** Affiche l'accueil et resynchronise ce qui a pu changer dans Koillection. */
function goHome() {
  show('view-home');
  loadCollections();
  loadHistory();
}

async function loadCollections(refresh = false) {
  try {
    state.collections = await api(`/api/collections${refresh ? '?refresh=true' : ''}`);
  } catch (error) {
    state.collections = [];
    toast(error.message, true);
  }
  fillCollectionSelect($('collection-select'));
  const preset = state.config && state.config.default_collection;
  $('collection-hint').textContent = state.collections.length
    ? (preset ? `Collection par défaut configurée : ${preset}` : '')
    : "Aucune collection trouvée. Créez-en une dans Koillection (par exemple « Livres »), "
      + 'puis rechargez la liste ci-dessous.';
}

async function loadHistory() {
  let entries = [];
  try { entries = await api('/api/history?limit=15'); } catch { return; }
  const list = $('history-list');
  list.innerHTML = '';
  if (!entries.length) {
    list.innerHTML = '<li class="muted small">Aucun ajout pour le moment.</li>';
    return;
  }
  for (const entry of entries) {
    const item = document.createElement('li');
    const title = document.createElement('div');
    title.className = 'h-title';
    title.textContent = entry.title;
    const meta = document.createElement('div');
    meta.className = 'h-meta';
    const parts = [entry.authors, entry.collection].filter(Boolean);
    meta.textContent = parts.join(' · ');
    item.append(title, meta);
    if (entry.read) {
      const read = document.createElement('span');
      read.className = 'h-read small';
      read.textContent = '✓ lu';
      item.append(read);
    }
    list.append(item);
  }
}

// ═══ Démarrage ══════════════════════════════════════════════════════════
async function boot() {
  try {
    state.config = await api('/api/config');
  } catch (error) {
    toast(`Serveur injoignable : ${error.message}`, true);
    return;
  }

  $('app-version').textContent = `version ${state.config.version}`;
  if (state.config.koillection_url) {
    const link = $('koillection-link');
    link.href = state.config.koillection_url;
    link.hidden = false;
  }

  if (state.config.auth_required && !state.config.authenticated) {
    show('view-login');
    return;
  }
  await enterApp();
}

async function enterApp() {
  show('view-home');
  if (!state.config.koillection_configured) {
    toast('Koillection non configuré : renseignez KOILLECTION_URL / USERNAME / PASSWORD.', true);
  }
  await Promise.all([loadCollections(), loadHistory()]);
  $('isbn-input').focus();
}

function bind() {
  $('login-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const error = $('login-error');
    error.hidden = true;
    try {
      await api('/api/login', {
        method: 'POST',
        body: JSON.stringify({ password: $('login-password').value }),
      });
      state.config.authenticated = true;
      $('login-password').value = '';
      await enterApp();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });

  $('isbn-input').addEventListener('input', () => {
    const hint = $('isbn-hint');
    const check = checkIsbn($('isbn-input').value);
    hint.classList.remove('ok', 'ko');
    if (check.isbn) {
      hint.textContent = `ISBN valide : ${check.isbn}`;
      hint.classList.add('ok');
    } else if (check.error) {
      hint.textContent = check.error;
      hint.classList.add('ko');
    } else {
      hint.textContent = '';
    }
  });

  $('isbn-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const check = checkIsbn($('isbn-input').value);
    if (!check.isbn) {
      toast(check.error || 'Saisissez un ISBN.', true);
      return;
    }
    $('isbn-input').blur();
    lookup(check.isbn, { raw: cleanIsbn($('isbn-input').value), manual: true });
  });

  $('btn-scan').addEventListener('click', () => { state.continuous = false; startScanner(); });
  $('btn-scan-close').addEventListener('click', () => { stopScanner(); goHome(); });
  $('btn-torch').addEventListener('click', toggleTorch);
  $('btn-scan-manual').addEventListener('click', () => {
    stopScanner();
    show('view-home');
    $('isbn-input').focus();
  });
  $('btn-manual').addEventListener('click', () => manualEntry(''));

  $('btn-reload-collections').addEventListener('click', async () => {
    busy('Lecture des collections…');
    await loadCollections(true);
    idle();
    toast(
      state.collections.length
        ? `${state.collections.length} collection(s) trouvée(s).`
        : 'Toujours aucune collection dans Koillection.',
      !state.collections.length,
    );
  });

  $('btn-refresh').addEventListener('click', async () => {
    busy('Rafraîchissement…');
    await loadCollections(true);
    idle();
    toast('Collections rafraîchies.');
  });

  $('collection-select').addEventListener('change', (event) => {
    state.collectionId = event.target.value;
    localStorage.setItem('collection', state.collectionId);
  });
  $('f-collection').addEventListener('change', (event) => {
    state.collectionId = event.target.value;
    localStorage.setItem('collection', state.collectionId);
  });

  $('btn-rescan').addEventListener('click', startScanner);
  $('btn-fix-isbn').addEventListener('click', () => {
    const code = (state.scan && state.scan.isbn13) || '';
    show('view-home');
    const input = $('isbn-input');
    input.value = code;
    input.dispatchEvent(new Event('input'));
    input.focus();
    input.select();
  });

  $('f-series').addEventListener('input', updateSeriesHint);
  $('book-form').addEventListener('submit', submitBook);
  $('btn-cancel').addEventListener('click', goHome);
  $('btn-book-back').addEventListener('click', goHome);

  $('btn-scan-next').addEventListener('click', () => { $('isbn-input').value = ''; startScanner(); });
  $('btn-home').addEventListener('click', () => {
    $('isbn-input').value = '';
    $('isbn-hint').textContent = '';
    goHome();
  });

  // La caméra doit être relâchée dès que l'onglet passe en arrière-plan :
  // iOS coupe le flux et ne le rétablit pas tout seul.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && scanner.running) {
      stopScanner();
      show('view-home');
      toast('Scan interrompu (application en arrière-plan).');
    }
  });
}

bind();
boot();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* hors ligne facultatif */ });
  });
}
