# Bibliothèques tierces embarquées

## `zxing.min.js`

- Projet : [zxing-js/library](https://github.com/zxing-js/library) — version **0.21.3**
- Licence : Apache 2.0
- Origine : `https://cdn.jsdelivr.net/npm/@zxing/library@0.21.3/umd/index.min.js`

Le fichier est versionné dans le dépôt à dessein : l'application doit pouvoir tourner sur
un NAS sans accès Internet au moment de la construction de l'image, et aucun script ne
doit être chargé depuis un CDN tiers depuis le navigateur.

Pour le mettre à jour :

```bash
curl -sSL -o static/vendor/zxing.min.js \
  https://cdn.jsdelivr.net/npm/@zxing/library@<version>/umd/index.min.js
```

Seuls `MultiFormatReader`, `BinaryBitmap`, `HybridBinarizer`,
`HTMLCanvasElementLuminanceSource`, `DecodeHintType` et `BarcodeFormat` sont utilisés
(voir `static/app.js`).
