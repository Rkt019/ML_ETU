/**
 * copy-mediapipe-wasm.js
 *
 * Runs automatically after `npm install` (see package.json "postinstall").
 *
 * WHY THIS EXISTS:
 * Loading MediaPipe's vision_bundle.js and WASM files from a public CDN
 * (jsdelivr / unpkg) is unreliable — paths change between versions, CORS
 * headers are inconsistent, and CDN edge nodes sometimes serve stale or
 * wrong-MIME-type responses (this is exactly what caused the 404 / CORS /
 * "Refused to execute script" errors in the browser console).
 *
 * Instead: @mediapipe/tasks-vision is installed as a real npm dependency
 * (see package.json). This script copies its WASM runtime files from
 * node_modules into public/mediapipe/wasm/, so they're served by YOUR OWN
 * dev server / build output at a same-origin path. Zero external CDN
 * requests for the WASM runtime.
 *
 * The vision_bundle itself is imported directly in JS (ESM import), so
 * webpack bundles it — also zero CDN dependency for that part.
 */

const fs = require('fs');
const path = require('path');

const SRC_DIR  = path.join(__dirname, '..', 'node_modules', '@mediapipe', 'tasks-vision', 'wasm');
const DEST_DIR = path.join(__dirname, '..', 'public', 'mediapipe', 'wasm');

function copyFile(src, dest) {
  fs.copyFileSync(src, dest);
  console.log(`  copied ${path.basename(src)}`);
}

function main() {
  if (!fs.existsSync(SRC_DIR)) {
    console.warn('[copy-mediapipe-wasm] WARNING: source dir not found:', SRC_DIR);
    console.warn('[copy-mediapipe-wasm] Did `npm install` finish installing @mediapipe/tasks-vision?');
    process.exit(0); // don't fail the whole install over this
  }

  fs.mkdirSync(DEST_DIR, { recursive: true });

  const files = fs.readdirSync(SRC_DIR);
  console.log(`[copy-mediapipe-wasm] Copying ${files.length} files to public/mediapipe/wasm/...`);

  for (const file of files) {
    copyFile(path.join(SRC_DIR, file), path.join(DEST_DIR, file));
  }

  console.log('[copy-mediapipe-wasm] Done. WASM assets are now served from /mediapipe/wasm/ (same-origin).');
}

main();
