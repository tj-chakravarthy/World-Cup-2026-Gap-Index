// True 3D splash ball: a three.js sphere textured with the ball, lit by a fixed key light
// so the gloss highlight stays put while the ball spins (the real-spin cue). Falls back to
// the still ball.png on reduced-motion or any WebGL failure. Vendored three.js (no CDN).
import * as THREE from "./vendor/three.module.min.js";

const canvas = document.getElementById("splash-ball-canvas");
const still = document.querySelector(".splash-ball img");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

if (canvas && !reduce) {
  try {
    run();
    if (still) still.style.display = "none";   // 3D ball replaces the static one
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

  const tex = new THREE.TextureLoader().load("ball-equirect.jpg");
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;

  const ball = new THREE.Mesh(
    new THREE.SphereGeometry(1, 96, 96),
    new THREE.MeshPhongMaterial({ map: tex, specular: 0x2c2c2c, shininess: 20 })
  );
  ball.rotation.z = 0.14;                        // slight tilt, like resting on a fingertip
  scene.add(ball);

  const key = new THREE.DirectionalLight(0xfff6e6, 2.1); key.position.set(-4, 4, 5);
  const fill = new THREE.DirectionalLight(0xa8c0ff, 0.55); fill.position.set(4, -1, 2);
  scene.add(key, fill, new THREE.AmbientLight(0xffffff, 0.62));

  let raf;
  (function loop() {
    ball.rotation.y += 0.02;
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  })();
  setTimeout(() => cancelAnimationFrame(raf), 2400);   // splash is gone by then
}
