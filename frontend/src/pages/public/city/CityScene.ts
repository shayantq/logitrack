/**
 * شهر ایزومتریک سه‌بعدی صفحه اصلی — کاملاً رویه‌ای (procedural)، بدون مدل یا تصویر خارجی.
 * یک ون از «انبار» تا «مشتری» روی مسیر خط‌چین حرکت می‌کند؛ پیشرفت مسیر را اسکرول تعیین می‌کند
 * (setProgress) و ترافیک پس‌زمینه فقط وقتی بخش دیده می‌شود انیمیت می‌شود.
 */
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

type ThemeName = "light" | "dark";

// هم‌رنگ پالت سایت (styles.css): روز آبی روشن، شب سرمه‌ای. چراغ‌ها (پنجره، خیابان، خودرو) در شب گرم‌اند
const PALETTE = {
  light: {
    bg: "#f7fbfc", ground: "#ecf3f9", plate: "#e2edf6", road: "#d6e6f2", roadLine: "#f7fbfc",
    building: "#ffffff", buildingAlt: "#eff5fa", roof: "#dae8f3", window: "#b9d7ea", windowLit: "#b9d7ea",
    tree: "#86c3a8", treeAlt: "#b0dbc6", trunk: "#b9a58c", dash: "#b9d7ea", route: "#4672ad",
    van: "#ffffff", vanStripe: "#4672ad", glass: "#29405c", wheel: "#22344a",
    warehouse: "#ffffff", warehouseRoof: "#769fcd", accent: "#769fcd", customer: "#769fcd", success: "#1e8e5a",
    lampPole: "#8fa9c4", lampOff: "#dfe9f2", lampOn: "#dfe9f2", headlampOff: "#e8eef4", taillampOff: "#c7807f",
    hemiSky: "#ffffff", hemiGround: "#d6e6f2", hemi: 1.6, sun: 2.2, shadow: 0.18, night: 0,
  },
  dark: {
    bg: "#091540", ground: "#0a1747", plate: "#0d1c51", road: "#13225c", roadLine: "#22357a",
    building: "#1a2b6b", buildingAlt: "#162563", roof: "#203476", window: "#203476", windowLit: "#ffd27a",
    tree: "#1d5a63", treeAlt: "#246b72", trunk: "#2f2b45", dash: "#2b4290", route: "#7692ff",
    van: "#eaf2fd", vanStripe: "#7692ff", glass: "#08123a", wheel: "#050a24",
    warehouse: "#1d2f72", warehouseRoof: "#7692ff", accent: "#abd2fa", customer: "#abd2fa", success: "#43d08e",
    lampPole: "#3b4f93", lampOff: "#2b3a74", lampOn: "#ffe2a3", headlampOff: "#fff4d6", taillampOff: "#ff4d5e",
    hemiSky: "#7d93d6", hemiGround: "#091540", hemi: 0.85, sun: 0.9, shadow: 0.45, night: 1,
  },
} as const;

/** بافت‌های نور (بدون فایل تصویری): لکه گرد زیر تیر چراغ و مخروط نور جلوی خودرو */
function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, "rgba(255,255,255,0.95)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.45)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}

function beamTexture() {
  // بالای بافت = نزدیک خودرو (پرنور و باریک) ← پایین = دور (کم‌نور و پهن)؛
  // صفحه با چرخش -۹۰ درجه حول x خوابانده می‌شود و بالای بافت رو به خودرو قرار می‌گیرد
  const c = document.createElement("canvas");
  c.width = 128; c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createLinearGradient(0, 0, 0, 256);
  grad.addColorStop(0, "rgba(255,255,255,0.9)");
  grad.addColorStop(0.5, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.filter = "blur(10px)";
  g.fillStyle = grad;
  g.beginPath();
  g.moveTo(48, 6); g.lineTo(80, 6); g.lineTo(124, 248); g.lineTo(4, 248);
  g.closePath();
  g.fill();
  return new THREE.CanvasTexture(c);
}

/**
 * لایه‌های نور (مخروط چراغ خودرو و لکه نور چراغ خیابان) کمی بالاتر از همه خط‌کشی‌ها (بالاترین: خط‌چین مسیر تا ۰٫۰۹)
 * و پیاده‌رو (۰٫۱۴) رسم می‌شوند و با polygonOffset به دوربین نزدیک‌تر حساب می‌شوند؛ هم‌سطح بودن نور با رویه خط‌ها
 * باعث سوسو (z-fighting) و بریده شدن نور روی خط‌چین‌ها بود.
 */
const LIGHT_Y = 0.16;
const lightMaterial = (map: THREE.Texture, opacity = 1) => new THREE.MeshBasicMaterial({
  map, opacity, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
});

/** تولید عدد شبه‌تصادفی تکرارپذیر — شهر در هر بار بارگذاری یکسان است */
function rng(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
}

const PITCH = 8;           // فاصله مرکز تا مرکز بلوک‌ها
const ROAD = 2;            // عرض خیابان
const N = 6;               // تعداد بلوک در هر ضلع
const HALF = (N * PITCH) / 2;
const roadAt = (k: number) => -HALF + k * PITCH;
const blockCenter = (k: number) => roadAt(k) + PITCH / 2;

const WAREHOUSE_BLOCK = [0, 1] as const;
const CUSTOMER_BLOCK = [4, 4] as const;
const PARK_BLOCKS = new Set(["2,3", "5,0", "1,5"]);

/** مسیر خیابانی با گوشه‌های گرد: خط مستقیم + منحنی درجه دو در هر پیچ */
function streetPath(points: THREE.Vector3[], radius = 1.6) {
  const path = new THREE.CurvePath<THREE.Vector3>();
  let cursor = points[0].clone();
  for (let i = 1; i < points.length; i++) {
    const corner = points[i];
    const next = points[i + 1];
    if (!next) { path.add(new THREE.LineCurve3(cursor, corner.clone())); break; }
    const inDir = corner.clone().sub(points[i - 1]).normalize();
    const outDir = next.clone().sub(corner).normalize();
    const a = corner.clone().addScaledVector(inDir, -radius);
    const b = corner.clone().addScaledVector(outDir, radius);
    path.add(new THREE.LineCurve3(cursor, a));
    path.add(new THREE.QuadraticBezierCurve3(a, corner.clone(), b));
    cursor = b;
  }
  return path;
}

type Car = { mesh: THREE.Group; path: THREE.CurvePath<THREE.Vector3>; speed: number; offset: number };

export type CityLabels = { warehouse?: HTMLElement | null; customer?: HTMLElement | null; van?: HTMLElement | null };

export class CityScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  /** اجزای ثابت شهر؛ در پایان ساخت، بر اساس متریال در چند مش ادغام می‌شوند (کاهش draw call) */
  private staticGroup = new THREE.Group();
  private camera: THREE.OrthographicCamera;
  private hemi: THREE.HemisphereLight;
  private sun: THREE.DirectionalLight;
  private materials = new Map<string, THREE.MeshStandardMaterial>();
  private windows!: THREE.InstancedMesh;
  private windowLit: boolean[] = [];
  private dashes!: THREE.InstancedMesh;
  private dashU: number[] = [];
  private route: THREE.CurvePath<THREE.Vector3>;
  private van = new THREE.Group();
  private pin = new THREE.Group();
  private pulse!: THREE.Mesh;
  private cars: Car[] = [];
  /** چراغ‌های خیابانی: سر چراغ و لکه نور روی زمین (هر دو instanced؛ رنگ هر نمونه = شدت نورش) */
  private lampHeads!: THREE.InstancedMesh;
  private lampPools!: THREE.InstancedMesh;
  private lampDelay: number[] = [];
  /** مخروط نور جلوی همه خودروها یک متریال مشترک دارد؛ شب با opacity روشن می‌شود */
  private beamMaterial = lightMaterial(beamTexture(), 0);
  private glowMap = glowTexture();
  /** ۰ = روز، ۱ = شب کامل؛ روشن/خاموش شدن چراغ‌ها نرم و پشت‌سرهم انیمیت می‌شود */
  private night = 0;
  private nightTarget = 0;
  private nightFrame = 0;
  private progress = 0;
  private routeU = 0;
  private lastPaint = -1;
  private theme: ThemeName = "light";
  private frame = 0;
  private running = false;
  private clock = new THREE.Clock();
  private size = { w: 1, h: 1 };
  private resizeObserver: ResizeObserver;
  private disposed = false;

  constructor(private canvas: HTMLCanvasElement, private labels: CityLabels = {}) {
    const mobile = window.matchMedia("(max-width: 768px)").matches;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: !mobile, alpha: false, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, mobile ? 1.5 : 2));
    this.renderer.shadowMap.enabled = !mobile;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 400);
    this.camera.position.set(60, 58, 60);
    this.camera.lookAt(0, 0, 0);

    this.hemi = new THREE.HemisphereLight("#ffffff", "#dddddd", 1.5);
    this.sun = new THREE.DirectionalLight("#ffffff", 2);
    this.sun.position.set(-30, 60, 25);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    Object.assign(this.sun.shadow.camera, { left: -40, right: 40, top: 40, bottom: -40, near: 1, far: 160 });
    this.sun.shadow.bias = -0.0005;
    this.scene.add(this.hemi, this.sun);

    this.route = streetPath([
      new THREE.Vector3(roadAt(1), 0, blockCenter(WAREHOUSE_BLOCK[1])),
      new THREE.Vector3(roadAt(1), 0, roadAt(2)),
      new THREE.Vector3(roadAt(4), 0, roadAt(2)),
      new THREE.Vector3(roadAt(4), 0, roadAt(5)),
      new THREE.Vector3(blockCenter(CUSTOMER_BLOCK[0]), 0, roadAt(5)),
    ]);

    this.buildGround();
    this.buildCity();
    this.buildRoute();
    this.buildVan();
    this.buildTraffic();
    this.buildStreetLights();
    this.mergeStatic();
    const initial = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    this.night = this.nightTarget = PALETTE[initial].night;   // بار اول بدون انیمیشن
    this.setTheme(initial);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(canvas);
    this.resize();
  }

  // ------------------------------------------------------------------ ساخت صحنه
  private mat(key: string) {
    let m = this.materials.get(key);
    if (!m) {
      m = new THREE.MeshStandardMaterial({ roughness: 0.92, metalness: 0, flatShading: true });
      this.materials.set(key, m);
    }
    return m;
  }

  private box(w: number, h: number, d: number, material: string, x: number, y: number, z: number, shadow = true) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), this.mat(material));
    mesh.position.set(x, y, z);
    mesh.castShadow = shadow;
    mesh.receiveShadow = true;
    return mesh;
  }

  private buildGround() {
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), this.mat("ground"));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.05;
    ground.receiveShadow = true;
    this.scene.add(ground);

    const size = N * PITCH + ROAD;
    const plate = this.box(size + 3, 0.3, size + 3, "plate", 0, -0.12, 0, false);
    this.addStatic(plate);
    for (let k = 0; k <= N; k++) {
      this.addStatic(this.box(ROAD, 0.04, size, "road", roadAt(k), 0.02, 0, false));
      this.addStatic(this.box(size, 0.04, ROAD, "road", 0, 0.021, roadAt(k), false));
    }
    // خط وسط خیابان‌ها
    const lines = new THREE.InstancedMesh(new THREE.BoxGeometry(0.08, 0.02, 0.9), this.mat("roadLine"), 2 * (N + 1) * N * 4);
    const m = new THREE.Matrix4();
    let i = 0;
    for (let k = 0; k <= N; k++) {
      for (let b = 0; b < N; b++) {
        for (let s = 0; s < 4; s++) {
          const t = roadAt(b) + 1.6 + s * 1.6;
          m.makeTranslation(roadAt(k), 0.05, t); lines.setMatrixAt(i++, m);
          m.makeRotationY(Math.PI / 2).setPosition(t, 0.05, roadAt(k)); lines.setMatrixAt(i++, m);
        }
      }
    }
    lines.count = i;
    this.scene.add(lines);
  }

  private buildCity() {
    const rand = rng(7);
    const windowSlots: THREE.Matrix4[] = [];
    const tmp = new THREE.Matrix4();

    for (let bx = 0; bx < N; bx++) {
      for (let bz = 0; bz < N; bz++) {
        const cx = blockCenter(bx), cz = blockCenter(bz);
        const inner = PITCH - ROAD - 0.6;
        this.addStatic(this.box(inner + 0.4, 0.14, inner + 0.4, "roadLine", cx, 0.07, cz, false)); // پیاده‌رو

        if (bx === WAREHOUSE_BLOCK[0] && bz === WAREHOUSE_BLOCK[1]) { this.buildWarehouse(cx, cz); continue; }
        if (bx === CUSTOMER_BLOCK[0] && bz === CUSTOMER_BLOCK[1]) { this.buildCustomer(cx, cz); continue; }
        if (PARK_BLOCKS.has(`${bx},${bz}`)) {
          for (let t = 0; t < 7; t++) this.tree(cx + (rand() - 0.5) * (inner - 1.2), cz + (rand() - 0.5) * (inner - 1.2), 0.8 + rand() * 0.6, rand() > 0.5);
          continue;
        }
        // هر بلوک به ۴ قطعه تقسیم می‌شود؛ بعضی قطعه‌ها خالی (درخت) می‌مانند
        const q = inner / 2;
        for (const [ox, oz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
          const px = cx + (ox * q) / 2, pz = cz + (oz * q) / 2;
          if (rand() < 0.22) { this.tree(px, pz, 0.7 + rand() * 0.5, rand() > 0.5); continue; }
          const w = q - 0.5 - rand() * 0.6, d = q - 0.5 - rand() * 0.6;
          const floors = 1 + Math.floor(rand() * (Math.abs(bx - bz) < 2 ? 6 : 3));
          const h = floors * 0.9 + 0.3;
          const b = this.box(w, h, d, rand() > 0.5 ? "building" : "buildingAlt", px, 0.14 + h / 2, pz);
          this.addStatic(b);
          this.addStatic(this.box(w * 0.4, 0.3, d * 0.4, "roof", px - w * 0.15, 0.14 + h + 0.15, pz + d * 0.1)); // تأسیسات پشت‌بام
          // پنجره‌ها فقط روی دو وجهی که دوربین می‌بیند (+x و +z)
          for (let f = 0; f < floors; f++) {
            const y = 0.14 + 0.75 + f * 0.9;
            for (let c = 0; c < Math.max(1, Math.floor(d / 0.8)); c++) {
              const z = pz - d / 2 + (c + 0.5) * (d / Math.max(1, Math.floor(d / 0.8)));
              tmp.makeRotationY(Math.PI / 2).setPosition(px + w / 2 + 0.01, y, z); windowSlots.push(tmp.clone());
            }
            for (let c = 0; c < Math.max(1, Math.floor(w / 0.8)); c++) {
              const x = px - w / 2 + (c + 0.5) * (w / Math.max(1, Math.floor(w / 0.8)));
              tmp.makeTranslation(x, y, pz + d / 2 + 0.01); windowSlots.push(tmp.clone());
            }
          }
        }
      }
    }

    this.windows = new THREE.InstancedMesh(new THREE.PlaneGeometry(0.34, 0.42), new THREE.MeshBasicMaterial(), windowSlots.length);
    windowSlots.forEach((matrix, i) => { this.windows.setMatrixAt(i, matrix); this.windowLit.push(rand() > 0.55); });
    this.scene.add(this.windows);
  }

  private addStatic(...objects: THREE.Object3D[]) {
    this.staticGroup.add(...objects);
  }

  private mergeStatic() {
    this.staticGroup.updateMatrixWorld(true);
    const buckets = new Map<THREE.Material, THREE.BufferGeometry[]>();
    this.staticGroup.traverse(o => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      // برخی هندسه‌ها اندیس‌دار و برخی بدون اندیس‌اند؛ ادغام نیاز به یکسان بودن دارد
      const geometry = mesh.geometry.index ? mesh.geometry.toNonIndexed() : mesh.geometry.clone();
      geometry.applyMatrix4(mesh.matrixWorld);
      const material = mesh.material as THREE.Material;
      if (!buckets.has(material)) buckets.set(material, []);
      buckets.get(material)!.push(geometry);
      mesh.geometry.dispose();
    });
    for (const [material, geometries] of buckets) {
      const merged = mergeGeometries(geometries);
      geometries.forEach(g => g.dispose());
      if (!merged) continue;
      const mesh = new THREE.Mesh(merged, material);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      this.scene.add(mesh);
    }
    this.staticGroup.clear();
  }

  private tree(x: number, z: number, scale: number, alt: boolean) {
    const trunk = this.box(0.18 * scale, 0.5 * scale, 0.18 * scale, "trunk", x, 0.14 + 0.25 * scale, z);
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(0.62 * scale, 0), this.mat(alt ? "treeAlt" : "tree"));
    crown.position.set(x, 0.14 + 0.5 * scale + 0.5 * scale, z);
    crown.castShadow = true;
    this.addStatic(trunk, crown);
  }

  private buildWarehouse(cx: number, cz: number) {
    const g = new THREE.Group();
    g.add(this.box(4.6, 2.2, 5.2, "warehouse", 0, 1.24, 0));
    // سقف شیروانی
    const roof = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 3.1, 1.2, 4, 1), this.mat("warehouseRoof"));
    roof.rotation.y = Math.PI / 4;
    roof.scale.set(1.05, 1, 1.18);
    roof.position.y = 2.95;
    roof.castShadow = true;
    g.add(roof);
    // درهای بارگیری رو به خیابان (+x)
    for (const z of [-1.4, 0, 1.4]) g.add(this.box(0.06, 1.2, 1, "glass", 2.32, 0.75, z, false));
    // پالت‌های بار
    for (let i = 0; i < 3; i++) g.add(this.box(0.6, 0.45 + (i % 2) * 0.3, 0.6, "accent", -1.3 + i * 0.8, 0.4, 3.1));
    g.position.set(cx, 0, cz);
    this.addStatic(g);

    this.pulse = new THREE.Mesh(new THREE.RingGeometry(0.9, 1.1, 40), new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide }));
    this.pulse.rotation.x = -Math.PI / 2;
    this.pulse.position.copy(this.route.getPointAt(0)).setY(0.09);
    this.scene.add(this.pulse);
  }

  private buildCustomer(cx: number, cz: number) {
    const g = new THREE.Group();
    g.add(this.box(2.6, 1.6, 2.6, "building", 0, 0.94, 0));
    const roof = new THREE.Mesh(new THREE.ConeGeometry(2.2, 1.2, 4), this.mat("customer"));
    roof.rotation.y = Math.PI / 4;
    roof.position.y = 2.34;
    roof.castShadow = true;
    g.add(roof, this.box(0.7, 1, 0.06, "glass", 0, 0.64, 1.33, false));
    this.tree(cx - 2.2, cz + 2.2, 0.8, true);
    g.position.set(cx, 0, cz);
    this.addStatic(g);

    // سنجاق مقصد
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.55, 20, 14), this.mat("customer"));
    const tip = new THREE.Mesh(new THREE.ConeGeometry(0.42, 0.9, 16), this.mat("customer"));
    tip.rotation.x = Math.PI;
    tip.position.y = -0.62;
    const dot = new THREE.Mesh(new THREE.SphereGeometry(0.22, 12, 8), this.mat("van"));
    dot.position.z = 0.42;
    this.pin.add(head, tip, dot);
    this.pin.position.set(cx, 4.4, cz);
    this.scene.add(this.pin);
  }

  private buildRoute() {
    const length = this.route.getLength();
    const count = Math.floor(length / 0.75);
    this.dashes = new THREE.InstancedMesh(new THREE.BoxGeometry(0.22, 0.04, 0.42), new THREE.MeshBasicMaterial(), count);
    const m = new THREE.Matrix4();
    const up = new THREE.Vector3(0, 1, 0);
    for (let i = 0; i < count; i++) {
      const u = (i + 0.5) / count;
      const p = this.route.getPointAt(u);
      const t = this.route.getTangentAt(u);
      m.makeRotationAxis(up, Math.atan2(t.x, t.z)).setPosition(p.x, 0.07, p.z);
      this.dashes.setMatrixAt(i, m);
      this.dashU.push(u);
    }
    this.scene.add(this.dashes);
  }

  private vehicle(bodyColor: string, length: number, cargo: boolean) {
    const g = new THREE.Group();
    const w = 0.92;
    g.add(this.box(w, cargo ? 0.95 : 0.45, cargo ? length * 0.68 : length, bodyColor, 0, cargo ? 0.72 : 0.42, cargo ? -length * 0.14 : 0));
    g.add(this.box(w * 0.98, 0.62, length * 0.3, bodyColor, 0, 0.56, length * 0.34));      // کابین
    g.add(this.box(w * 1.0, 0.32, 0.05, "glass", 0, 0.66, length * 0.495, false));        // شیشه جلو
    if (!cargo) g.add(this.box(w * 0.86, 0.35, length * 0.5, bodyColor, 0, 0.78, -0.05));
    if (cargo) g.add(this.box(w + 0.02, 0.16, length * 0.6, "vanStripe", 0, 0.62, -length * 0.14, false));
    const wheel = new THREE.CylinderGeometry(0.2, 0.2, 0.16, 12);
    for (const [x, z] of [[-1, 1], [1, 1], [-1, -1], [1, -1]]) {
      const mesh = new THREE.Mesh(wheel, this.mat("wheel"));
      mesh.rotation.z = Math.PI / 2;
      mesh.position.set((x * w) / 2, 0.2, z * length * 0.32);
      g.add(mesh);
    }
    g.traverse(o => { if ((o as THREE.Mesh).isMesh) o.castShadow = true; });

    // چراغ‌های جلو (+z) و عقب؛ شب روشن می‌شوند (رنگشان در applyNight تنظیم می‌شود)
    for (const side of [-1, 1]) {
      g.add(this.box(0.2, 0.12, 0.05, "headlamp", side * w * 0.33, 0.48, length * 0.5 + 0.01, false));
      g.add(this.box(0.16, 0.12, 0.05, "taillamp", side * w * 0.36, cargo ? 0.5 : 0.48, cargo ? -length * 0.48 - 0.01 : -length * 0.5 - 0.01, false));
    }
    // مخروط نور روی آسفالت جلوی خودرو
    const beam = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 3.6), this.beamMaterial);
    beam.rotation.x = -Math.PI / 2;
    beam.position.set(0, LIGHT_Y, length * 0.5 + 1.75);
    beam.renderOrder = 2;
    g.add(beam);
    return g;
  }

  /**
   * تیر چراغ کنار پیاده‌رو، وسط هر ضلع بلوک، یک‌درمیان دو طرف خیابان.
   * تیرها جزو اجزای ثابت (ادغام‌شده) هستند؛ سر چراغ و لکه نور زمین instanced تا شب روشن شوند.
   */
  private buildStreetLights() {
    const spots: { x: number; z: number; ax: number; az: number }[] = [];
    for (let k = 0; k <= N; k++) {
      for (let b = 0; b < N; b++) {
        const along = blockCenter(b);
        const side = (k + b) % 2 === 0 ? 1 : -1;
        const s = k === 0 ? 1 : k === N ? -1 : side;         // خیابان‌های لبه: فقط سمت داخل شهر
        const off = ROAD / 2 + 0.28;
        spots.push({ x: roadAt(k) + s * off, z: along, ax: -s, az: 0 });       // خیابان‌های امتداد z
        spots.push({ x: along, z: roadAt(k) + s * off, ax: 0, az: -s });       // خیابان‌های امتداد x
      }
    }
    const height = 1.7;
    for (const p of spots) {
      this.addStatic(this.box(0.09, height, 0.09, "lampPole", p.x, 0.14 + height / 2, p.z));
      this.addStatic(this.box(p.ax ? 0.55 : 0.07, 0.07, p.az ? 0.55 : 0.07, "lampPole", p.x + p.ax * 0.25, 0.14 + height, p.z + p.az * 0.25, false));
    }
    const m = new THREE.Matrix4();
    this.lampHeads = new THREE.InstancedMesh(new THREE.BoxGeometry(0.26, 0.1, 0.26), new THREE.MeshBasicMaterial(), spots.length);
    this.lampPools = new THREE.InstancedMesh(new THREE.PlaneGeometry(3.4, 3.4), lightMaterial(this.glowMap), spots.length);
    this.lampPools.renderOrder = 1;
    const flat = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
    spots.forEach((p, i) => {
      const hx = p.x + p.ax * 0.5, hz = p.z + p.az * 0.5;
      m.makeTranslation(hx, 0.14 + height - 0.02, hz); this.lampHeads.setMatrixAt(i, m);
      m.copy(flat).setPosition(hx, LIGHT_Y, hz); this.lampPools.setMatrixAt(i, m);
      // روشن شدن موجی از سمت انبار به بیرون
      this.lampDelay.push(Math.hypot(hx - blockCenter(WAREHOUSE_BLOCK[0]), hz - blockCenter(WAREHOUSE_BLOCK[1])) / (N * PITCH * 1.4));
    });
    this.scene.add(this.lampHeads, this.lampPools);
  }

  /** شدت نور شب را روی چراغ‌های خیابان، چراغ خودروها و مخروط نورشان اعمال می‌کند */
  private applyNight() {
    const day = PALETTE.light, dark = PALETTE.dark;
    const head = new THREE.Color(), pool = new THREE.Color();
    const off = new THREE.Color(this.theme === "dark" ? dark.lampOff : day.lampOff), on = new THREE.Color(dark.lampOn);
    const black = new THREE.Color(0, 0, 0);
    this.lampDelay.forEach((delay, i) => {
      // هر چراغ با کمی تأخیر نسبت به فاصله‌اش روشن می‌شود و لحظه روشن شدن یک چشمک کوتاه می‌زند
      const local = THREE.MathUtils.clamp((this.night * 1.6 - delay * 0.6), 0, 1);
      const flicker = this.nightTarget === 1 && local > 0 && local < 0.35 ? (Math.sin(local * 60 + i) > 0.3 ? 1 : 0.35) : 1;
      const level = local * flicker;
      head.copy(off).lerp(on, level);
      this.lampHeads.setColorAt(i, head);
      this.lampPools.setColorAt(i, pool.copy(black).lerp(on, level * 0.55));
    });
    if (this.lampHeads.instanceColor) this.lampHeads.instanceColor.needsUpdate = true;
    if (this.lampPools.instanceColor) this.lampPools.instanceColor.needsUpdate = true;
    this.lampPools.visible = this.night > 0.001;

    const n = this.night;
    this.mat("headlamp").color.set(this.theme === "dark" ? dark.headlampOff : day.headlampOff);
    this.mat("headlamp").emissive.set(dark.lampOn);
    this.mat("headlamp").emissiveIntensity = n * 1.4;
    this.mat("taillamp").color.set(this.theme === "dark" ? dark.taillampOff : day.taillampOff);
    this.mat("taillamp").emissive.set(dark.taillampOff);
    this.mat("taillamp").emissiveIntensity = n * 1.2;
    this.beamMaterial.color.set(dark.lampOn);
    this.beamMaterial.opacity = n * 0.9;
    this.beamMaterial.visible = n > 0.001;
    // برای تست خودکار: چراغ‌های شب کامل روشن‌اند یا نه
    this.canvas.dataset.night = n >= 0.999 ? "1" : n <= 0.001 ? "0" : "transition";
  }

  /** انیمیشن نرم بین روز و شب (حدود ۱٫۴ ثانیه)، مستقل از حلقه اصلی */
  private animateNight = () => {
    const step = 1 / (1.4 * 60);
    this.night = this.nightTarget > this.night ? Math.min(this.nightTarget, this.night + step) : Math.max(this.nightTarget, this.night - step * 1.6);
    this.applyNight();
    if (!this.running) this.render();
    this.nightFrame = this.night !== this.nightTarget && !this.disposed ? requestAnimationFrame(this.animateNight) : 0;
  };

  private buildVan() {
    this.van = this.vehicle("van", 1.9, true);
    this.scene.add(this.van);
  }

  private buildTraffic() {
    const loops: [number, number, number, number][] = [[0, 3, 3, 6], [2, 0, 6, 2], [3, 3, 6, 5], [0, 0, 2, 4], [4, 0, 6, 4]];
    const colors = ["building", "accent", "buildingAlt", "warehouseRoof", "building"];
    loops.forEach(([x0, z0, x1, z1], i) => {
      // حلقه‌ای روی خیابان‌ها با فاصله از وسط خیابان (لاین سمت راست)
      const lane = 0.48;
      const c0 = new THREE.Vector3(roadAt(x0) + lane, 0, roadAt(z0) + lane), c1 = new THREE.Vector3(roadAt(x1) - lane, 0, roadAt(z0) + lane);
      const c2 = new THREE.Vector3(roadAt(x1) - lane, 0, roadAt(z1) - lane), c3 = new THREE.Vector3(roadAt(x0) + lane, 0, roadAt(z1) - lane);
      const mid = c0.clone().lerp(c1, 0.5);
      const pts = [mid, c1, c2, c3, c0, mid.clone()];   // شروع و پایان وسط یک ضلع ← حلقه بی‌درز
      const path = streetPath(pts, 1.1);
      const mesh = this.vehicle(colors[i], 1.4, false);
      mesh.scale.setScalar(0.85);
      this.scene.add(mesh);
      this.cars.push({ mesh, path, speed: 0.022 + (i % 3) * 0.007, offset: i * 0.21 });
    });
  }

  // ------------------------------------------------------------------ وضعیت
  setTheme(theme: ThemeName) {
    this.theme = theme;
    const p = PALETTE[theme];
    this.scene.background = new THREE.Color(p.bg);
    for (const [key, material] of this.materials) {
      const color = (p as Record<string, string | number>)[key];
      if (typeof color === "string") material.color.set(color);
    }
    this.mat("glass").roughness = 0.3;
    this.mat("customer").emissive.set(theme === "dark" ? p.customer : "#000000");
    this.mat("customer").emissiveIntensity = theme === "dark" ? 0.25 : 0;
    this.hemi.color.set(p.hemiSky);
    this.hemi.groundColor.set(p.hemiGround);
    this.hemi.intensity = p.hemi;
    this.sun.intensity = p.sun;
    this.sun.shadow.intensity = 1 - p.shadow;

    const lit = new THREE.Color(p.windowLit), off = new THREE.Color(p.window);
    this.windowLit.forEach((isLit, i) => this.windows.setColorAt(i, isLit ? lit : off));
    if (this.windows.instanceColor) this.windows.instanceColor.needsUpdate = true;
    (this.pulse.material as THREE.MeshBasicMaterial).color.set(p.route);
    // شب: چراغ‌های خیابان و خودروها نرم و پشت‌سرهم روشن می‌شوند (روز: خاموش)
    this.nightTarget = p.night;
    if (this.night !== this.nightTarget && !this.nightFrame && !this.disposed) this.nightFrame = requestAnimationFrame(this.animateNight);
    else this.applyNight();
    this.lastPaint = -1;
    this.setProgress(this.progress);
  }

  private paintRoute() {
    const p = PALETTE[this.theme];
    const done = new THREE.Color(p.route), todo = new THREE.Color(p.dash);
    this.dashU.forEach((u, i) => this.dashes.setColorAt(i, u <= this.routeU ? done : todo));
    if (this.dashes.instanceColor) this.dashes.instanceColor.needsUpdate = true;
  }

  /** پیشرفت سفر بین ۰ (انبار) و ۱ (تحویل) — توسط اسکرول کنترل می‌شود */
  setProgress(value: number) {
    this.progress = THREE.MathUtils.clamp(value, 0, 1);
    // ۸٪ اول: بارگیری درِ انبار — ون هنوز حرکت نکرده
    const u = THREE.MathUtils.clamp((this.progress - 0.08) / 0.88, 0, 1);
    const pos = this.route.getPointAt(u);
    const tan = this.route.getTangentAt(Math.min(u, 0.999));
    this.van.position.set(pos.x, 0.02, pos.z);
    this.van.rotation.y = Math.atan2(tan.x, tan.z);

    const delivered = this.progress >= 0.97;
    this.mat("customer").color.set(delivered ? PALETTE[this.theme].success : PALETTE[this.theme].customer);
    this.routeU = u;
    const bucket = Math.round(u * 200);
    if (bucket !== this.lastPaint) { this.lastPaint = bucket; this.paintRoute(); }
    this.updateCamera();
    if (!this.running) this.render();
  }

  private updateCamera() {
    const { w, h } = this.size;
    const aspect = w / h;
    const wide = aspect > 1.15;
    // در صفحه پهن، شهر در سمت چپ و متن در راست (RTL) قرار می‌گیرد
    const view = wide ? 30 : 34 / Math.max(aspect, 0.55);
    this.camera.left = (-view * aspect) / 2;
    this.camera.right = (view * aspect) / 2;
    this.camera.top = view / 2;
    this.camera.bottom = -view / 2;
    // دوربین آرام ون را دنبال می‌کند
    const center = new THREE.Vector3(0, 0, 0).lerp(this.van.position, 0.42);
    const right = new THREE.Vector3(1, 0, -1).normalize();
    if (wide) center.addScaledVector(right, (view * aspect) * 0.17);
    else center.add(new THREE.Vector3(1, 0, 1).normalize().multiplyScalar(view * 0.12));
    this.camera.position.set(center.x + 60, 58, center.z + 60);
    this.camera.lookAt(center);
    this.camera.updateProjectionMatrix();
    this.sun.position.set(center.x - 30, 60, center.z + 25);
    this.sun.target.position.copy(center);
    this.sun.target.updateMatrixWorld();
  }

  private resize() {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.size = { w: rect.width, h: rect.height };
    this.renderer.setSize(rect.width, rect.height, false);
    this.updateCamera();
    this.render();
  }

  // ------------------------------------------------------------------ رندر
  /** انیمیشن پیوسته (ترافیک، سنجاق، پالس) فقط وقتی بخش در دید است */
  setRunning(running: boolean) {
    if (running === this.running || this.disposed) return;
    this.running = running;
    if (running) { this.clock.start(); this.loop(); } else cancelAnimationFrame(this.frame);
  }

  private loop = () => {
    if (!this.running) return;
    const t = this.clock.getElapsedTime();
    for (const car of this.cars) {
      const u = (t * car.speed + car.offset) % 1;
      const p = car.path.getPointAt(u), d = car.path.getTangentAt(u);
      car.mesh.position.set(p.x, 0.02, p.z);
      car.mesh.rotation.y = Math.atan2(d.x, d.z);
    }
    this.pin.position.y = 4.4 + Math.sin(t * 2.2) * 0.25;
    this.pin.rotation.y = t * 0.8;
    const s = 1 + ((t * 0.7) % 1) * 1.6;
    this.pulse.scale.set(s, s, s);
    (this.pulse.material as THREE.MeshBasicMaterial).opacity = this.progress < 0.1 ? 1 - ((t * 0.7) % 1) : 0;
    this.render();
    this.frame = requestAnimationFrame(this.loop);
  };

  private projected = new THREE.Vector3();
  private placeLabel(el: HTMLElement | null | undefined, point: THREE.Vector3) {
    if (!el) return;
    this.projected.copy(point).project(this.camera);
    const x = ((this.projected.x + 1) / 2) * this.size.w;
    const y = ((1 - this.projected.y) / 2) * this.size.h;
    el.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -100%)`;
  }

  render() {
    if (this.disposed) return;
    this.renderer.render(this.scene, this.camera);
    this.placeLabel(this.labels.warehouse, new THREE.Vector3(blockCenter(WAREHOUSE_BLOCK[0]), 4.2, blockCenter(WAREHOUSE_BLOCK[1])));
    this.placeLabel(this.labels.customer, this.pin.position.clone().setY(5.6));
    this.placeLabel(this.labels.van, this.van.position.clone().setY(2.1));
  }

  dispose() {
    this.disposed = true;
    this.running = false;
    cancelAnimationFrame(this.frame);
    cancelAnimationFrame(this.nightFrame);
    this.resizeObserver.disconnect();
    this.glowMap.dispose();
    this.beamMaterial.map?.dispose();
    this.scene.traverse(o => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.geometry.dispose();
        const material = mesh.material;
        (Array.isArray(material) ? material : [material]).forEach(m => m.dispose());
      }
    });
    this.renderer.dispose();
  }
}
