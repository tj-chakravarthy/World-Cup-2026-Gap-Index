// True 3D splash ball. Renders a real-time three.js sphere lit by a fixed key light (gloss
// highlight stays put while it spins). If web/public/trionda.glb is present it loads + spins
// that model (the real ball); otherwise it keeps the photo-textured sphere. Falls back to the
// still ball.png on reduced-motion or WebGL failure. Vendored three.js (no CDN).
//
// Timing: JS controls the fade so we WAIT for the ball to be ready (the glb is large) before
// dismissing — show it ~1s, then fade — capped so a slow/failed load never hangs. The CSS
// `splash-out` animation stays as the no-JS fallback and is disabled here once JS takes over.
import * as THREE from "three";
import { GLTFLoader } from "./vendor/GLTFLoader.js";

const splash = document.getElementById("splash");
const canvas = document.getElementById("splash-ball-canvas");
const still = document.querySelector(".splash-ball img");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

const HOLD = 1000;   // show the ready ball this long before fading
const CAP = 3600;    // never wait longer than this for the model
let dismissed = false, readyFired = false;

if (splash) splash.style.animation = "none";   // take over timing from the CSS fallback

function dismiss() {
  if (dismissed || !splash) return;
  dismissed = true;
  splash.style.transition = "opacity .6s ease";
  splash.style.opacity = "0";
  setTimeout(() => splash.remove(), 650);
}
function ready() { if (!readyFired) { readyFired = true; setTimeout(dismiss, HOLD); } }
setTimeout(dismiss, CAP);   // hard cap

if (canvas && !reduce) {
  try {
    run(ready);
    if (still) still.style.display = "none";
  } catch (e) {
    if (canvas) canvas.style.display = "none";   // keep the static ball.png
    ready();
  }
} else {
  ready();   // reduced-motion / no canvas -> still ball.png, then dismiss
}

function run(onReady) {
  const RES = 512;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(RES, RES, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1.07, 1.07, 1.07, -1.07, 0.1, 10);
  camera.position.z = 5;

  const key = new THREE.DirectionalLight(0xfff6e6, 2.1); key.position.set(-4, 4, 5);
  const fill = new THREE.DirectionalLight(0xa8c0ff, 0.55); fill.position.set(4, -1, 2);
  scene.add(key, fill, new THREE.AmbientLight(0xffffff, 0.5),
            new THREE.HemisphereLight(0xffffff, 0x3a3a44, 0.35));

  const tex = new THREE.TextureLoader().load("ball-equirect.jpg");
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(1, 96, 96),
    new THREE.MeshPhongMaterial({ map: tex, specular: 0x2c2c2c, shininess: 20 })
  );
  sphere.rotation.z = 0.14;
  scene.add(sphere);
  let spin = sphere;

  new GLTFLoader().load("trionda.glb", (gltf) => {
    const m = gltf.scene;
    const box = new THREE.Box3().setFromObject(m);
    m.position.sub(box.getCenter(new THREE.Vector3()));
    const s = box.getSize(new THREE.Vector3());
    m.scale.setScalar(1.9 / (Math.max(s.x, s.y, s.z) || 1));
    const pivot = new THREE.Group(); pivot.add(m); pivot.rotation.z = 0.14;
    scene.remove(sphere); scene.add(pivot); spin = pivot;
    onReady();
  }, undefined, () => onReady());   // no/failed trionda.glb -> keep the sphere

  let raf;
  (function loop() {
    spin.rotation.y += 0.02;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  })();
  setTimeout(() => cancelAnimationFrame(raf), 5000);   // stop after the splash is gone
}
