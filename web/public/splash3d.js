// True 3D splash ball. Renders a real-time three.js sphere lit by a fixed key light so the
// gloss highlight stays put while it spins. If web/public/trionda.glb is present it loads and
// spins that model instead (the real ball); otherwise it keeps the photo-textured sphere.
// Falls back to the still ball.png on reduced-motion or any WebGL failure. Vendored three.js.
import * as THREE from "three";
import { GLTFLoader } from "./vendor/GLTFLoader.js";

const canvas = document.getElementById("splash-ball-canvas");
const still = document.querySelector(".splash-ball img");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

if (canvas && !reduce) {
  try {
    run();
    if (still) still.style.display = "none";   // the 3D ball replaces the static one
  } catch (e) {
    if (canvas) canvas.style.display = "none"; // keep the static ball.png
  }
}

function run() {
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

  // default: a sphere textured from the photo ball
  const tex = new THREE.TextureLoader().load("ball-equirect.jpg");
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(1, 96, 96),
    new THREE.MeshPhongMaterial({ map: tex, specular: 0x2c2c2c, shininess: 20 })
  );
  sphere.rotation.z = 0.14;
  scene.add(sphere);
  let spin = sphere;

  // upgrade to the real Adidas Trionda model if web/public/trionda.glb is present; centered
  // and scaled to fit, spun about its own centre. Missing/failed load just keeps the sphere.
  new GLTFLoader().load("trionda.glb", (gltf) => {
    const m = gltf.scene;
    const box = new THREE.Box3().setFromObject(m);
    m.position.sub(box.getCenter(new THREE.Vector3()));
    const s = box.getSize(new THREE.Vector3());
    m.scale.setScalar(1.9 / (Math.max(s.x, s.y, s.z) || 1));
    const pivot = new THREE.Group(); pivot.add(m); pivot.rotation.z = 0.14;
    scene.remove(sphere); scene.add(pivot); spin = pivot;
  }, undefined, () => { /* no trionda.glb -> keep the textured sphere */ });

  let raf;
  (function loop() {
    spin.rotation.y += 0.02;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  })();
  setTimeout(() => cancelAnimationFrame(raf), 2400);   // splash is gone by then
}
