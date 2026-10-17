// Display sizing only: camera resolution and algorithm coordinates stay unchanged.
document.querySelectorAll("[data-resizable-preview]").forEach((surface) => {
  const image = surface.querySelector("img");
  const handle = surface.querySelector(".preview-resize-handle");
  let drag = null;

  function setWidth(width) {
    const maximum = surface.parentElement.clientWidth;
    const minimum = Math.min(240, maximum);
    const value = Math.round(Math.min(maximum, Math.max(minimum, width)));
    surface.style.width = `${value}px`;
    handle.setAttribute("aria-valuemin", minimum);
    handle.setAttribute("aria-valuemax", maximum);
    handle.setAttribute("aria-valuenow", value);
  }

  image.addEventListener("load", () => {
    if (image.naturalWidth && image.naturalHeight) {
      surface.style.aspectRatio = `${image.naturalWidth} / ${image.naturalHeight}`;
    }
  });
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = surface.getBoundingClientRect();
    drag = { x: event.clientX, y: event.clientY, width: rect.width, ratio: rect.width / rect.height };
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", (event) => {
    if (drag) {
      const dx = event.clientX - drag.x;
      const dy = (event.clientY - drag.y) * drag.ratio;
      setWidth(drag.width + (Math.abs(dx) >= Math.abs(dy) ? dx : dy));
    }
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    handle.addEventListener(name, () => { drag = null; });
  }
  handle.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const width = surface.getBoundingClientRect().width;
    setWidth(event.key === "Home" ? 240 : event.key === "End"
      ? surface.parentElement.clientWidth : width + (event.key === "ArrowRight" ? 24 : -24));
  });
  new ResizeObserver(() => {
    const width = surface.getBoundingClientRect().width;
    handle.setAttribute("aria-valuenow", Math.round(width));
    handle.setAttribute("aria-valuemin", Math.min(240, surface.parentElement.clientWidth));
    handle.setAttribute("aria-valuemax", surface.parentElement.clientWidth);
    surface.dispatchEvent(new Event("previewresize"));
  }).observe(surface);
});
