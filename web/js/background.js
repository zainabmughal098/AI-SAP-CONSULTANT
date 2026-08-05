(function initBackground() {
  const canvas = document.getElementById("bg-canvas");
  if (!canvas) return;

  const ctx = canvas.getContext("2d");
  let width = 0;
  let height = 0;
  let animationFrame = 0;
  let lastTime = 0;

  const blobs = [
    { x: 0.22, y: 0.28, radius: 0.36, color: [88, 114, 196], vx: 0.018, vy: 0.014, phase: 0.0 },
    { x: 0.72, y: 0.18, radius: 0.30, color: [124, 92, 196], vx: -0.015, vy: 0.012, phase: 1.8 },
    { x: 0.58, y: 0.72, radius: 0.34, color: [72, 132, 188], vx: 0.012, vy: -0.016, phase: 3.2 },
    { x: 0.38, y: 0.58, radius: 0.26, color: [156, 98, 210], vx: -0.013, vy: -0.011, phase: 4.6 },
  ];

  blobs.forEach((blob) => {
    blob.posX = blob.x;
    blob.posY = blob.y;
    blob.baseRadius = blob.radius;
  });

  function resize() {
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * window.devicePixelRatio);
    canvas.height = Math.floor(height * window.devicePixelRatio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
  }

  function drawBlob(blob, elapsedSeconds) {
    const driftX = Math.sin(elapsedSeconds * blob.vx + blob.phase) * 0.045;
    const driftY = Math.cos(elapsedSeconds * blob.vy + blob.phase * 1.2) * 0.04;

    blob.posX += (blob.x + driftX - blob.posX) * 0.008;
    blob.posY += (blob.y + driftY - blob.posY) * 0.008;

    const cx = blob.posX * width;
    const cy = blob.posY * height;
    const breathe = 1 + Math.sin(elapsedSeconds * 0.08 + blob.phase) * 0.025;
    const radius = blob.baseRadius * Math.min(width, height) * breathe;

    const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius);
    gradient.addColorStop(0, `rgba(${blob.color.join(",")}, 0.16)`);
    gradient.addColorStop(0.55, `rgba(${blob.color.join(",")}, 0.06)`);
    gradient.addColorStop(1, "rgba(14, 14, 17, 0)");

    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  function render(time) {
    const elapsedSeconds = time * 0.001;
    const delta = Math.min((time - lastTime) * 0.001, 0.05);
    lastTime = time;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#0e0e11";
    ctx.fillRect(0, 0, width, height);

    ctx.globalCompositeOperation = "source-over";
    blobs.forEach((blob) => drawBlob(blob, elapsedSeconds));

    animationFrame = requestAnimationFrame(render);
  }

  resize();
  lastTime = performance.now();
  render(lastTime);
  window.addEventListener("resize", resize);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      cancelAnimationFrame(animationFrame);
    } else {
      lastTime = performance.now();
      animationFrame = requestAnimationFrame(render);
    }
  });
})();
