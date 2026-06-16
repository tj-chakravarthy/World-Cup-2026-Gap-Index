// Intro splash. Shows a black "loading…" screen until the real Trionda model is loaded and
// rendered, then reveals the photo with the ball already spinning over it (no placeholder
// sphere, so the ball never changes mid-spin), holds, and fades to the site. If WebGL is
// unavailable / reduced-motion / the model fails, it just reveals the photo (which has its
// own ball). Vendored three.js (no CDN).
import * as THREE from "three";
import { GLTFLoader } from "./vendor/GLTFLoader.js";

const splash = document.getElementById("splash");
const loading = document.querySelector(".splash-loading");
const stage = document.querySelector(".splash-stage");
const canvas = document.getElementById("splash-ball-canvas");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

const HOLD = 1300;   // show the spinning Trionda this long after reveal, then fade
let revealed = false, dismissed = false;

function dismiss() {
  if (dismissed || !splash) return;
  dismissed = true;
  splash.style.transition = "opacity .6s ease";
  splash.style.opacity = "0";
  setTimeout(() => splash.remove(), 650);
}
function reveal() {
  if (revealed) return;
  revealed = true;
  if (loading) loading.style.display = "none";
  if (stage) stage.style.opacity = "1";
  setTimeout(dismiss, HOLD);
}
setTimeout(reveal, 6500);   // give up waiting for the model -> show the photo regardless

if (reduce || !canvas) {
  reveal();                 // no spin: reveal the photo (with its own ball)
} else {
  try { startThree(reveal); }
  catch (e) { reveal(); }   // WebGL failure -> reveal the photo
}

function startThree(onReady) {
  const RES = 512;
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(RES, RES, false);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1.01, 1.01, 1.01, -1.01, 0.1, 10);
  camera.position.z = 5;

  const key = new THREE.DirectionalLight(0xfff6e6, 2.1); key.position.set(-4, 4, 5);
  const fill = new THREE.DirectionalLight(0xa8c0ff, 0.55); fill.position.set(4, -1, 2);
  scene.add(key, fill, new THREE.AmbientLight(0xffffff, 0.5),
            new THREE.HemisphereLight(0xffffff, 0x3a3a44, 0.35));

  let raf, spin = null;
  new GLTFLoader().load("trionda.glb", (gltf) => {
    const m = gltf.scene;
    const box = new THREE.Box3().setFromObject(m);
    m.position.sub(box.getCenter(new THREE.Vector3()));
    const s = box.getSize(new THREE.Vector3());
    m.scale.setScalar(1.96 / (Math.max(s.x, s.y, s.z) || 1));
    const pivot = new THREE.Group(); pivot.add(m); pivot.rotation.z = 0.14;
    scene.add(pivot); spin = pivot;
    renderer.render(scene, camera);   // first frame on screen...
    onReady();                        // ...then reveal (no swap — Trionda from the start)
    (function loop() {
      spin.rotation.y += 0.02;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(loop);
    })();
  }, undefined, () => onReady());     // model failed -> reveal the photo (canvas stays empty)

  setTimeout(() => cancelAnimationFrame(raf), 9000);
}
