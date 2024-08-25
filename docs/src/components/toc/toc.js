// WeakMaps for efficient storage of link distances
const linkStarts = new WeakMap();
const linkEnds = new WeakMap();
const sectionsMap = new Map();

// Initialize observers on page load
document.addEventListener('DOMContentLoaded', () => {
  addIntersectionObserver();
  addResizeObserver();
});

// Tags to look for in the DOM hierarchy
const headingTags = ["h2", "h3", "h4", "h5"];

// Utility function to find previous heading siblings
function findPreviousHeadings(el) {
  const result = [];
  while (el && el.previousElementSibling) {
    el = el.previousElementSibling;
    if (headingTags.includes(el.tagName.toLowerCase())) {
      result.push(el);
    } else {
      break;
    }
  }
  return result;
}

// Add an IntersectionObserver to track section visibility
function addIntersectionObserver() {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(({ target, intersectionRatio }) => {
      const ids = sectionsMap.get(target)?.ids || findPreviousHeadings(target).map(h => h.id);
      sectionsMap.set(target, { ids, intersectionRatio });
    });

    updateActiveLinks();
  });

  document.querySelectorAll(".sl-markdown-content > :not(h2, h3, h4, h5)").forEach(section => observer.observe(section));
}

// Add a ResizeObserver to handle TOC resizing
function addResizeObserver() {
  const toc = document.querySelector("nav.toc-new");
  if (!toc) return;

  const observer = new ResizeObserver(() => {
    drawPath();
    updatePath();
  });

  observer.observe(toc);
}

// Draw the path that connects TOC links
function drawPath() {
  const path = document.querySelector("path.toc-marker");
  const links = Array.from(document.querySelectorAll("nav.toc-new a"));
  if (!links.length || !path) return;

  let pathData = [];
  let previousX = 0;

  links.forEach((link, i) => {
    const x = link.offsetLeft;
    const y = link.offsetTop;
    const height = link.offsetHeight;

    if (i === 0) {
      pathData.push("M", x, y, "L", x, y + height);
      linkStarts.set(link, 0);
    } else {
      if (previousX !== x) pathData.push("L", previousX, y);
      pathData.push("L", x, y);
      linkStarts.set(link, path.getTotalLength());
      pathData.push("L", x, y + height);
    }

    previousX = x;
    path.setAttribute("d", pathData.join(" "));
    linkEnds.set(link, path.getTotalLength());
  });
}

// Update the path visibility based on active links
function updatePath() {
  const path = document.querySelector("path.toc-marker");
  const pathLength = path?.getTotalLength();
  const activeLinks = document.querySelectorAll("nav.toc-new a.active");

  if (!activeLinks.length || !path) return;

  let linkStart = pathLength;
  let linkEnd = 0;

  activeLinks.forEach(link => {
    linkStart = Math.min(linkStart, linkStarts.get(link));
    linkEnd = Math.max(linkEnd, linkEnds.get(link));
  });

  path.style.display = activeLinks.length ? "inline" : "none";
  path.setAttribute("stroke-dasharray", `1 ${linkStart} ${linkEnd - linkStart} ${pathLength}`);
}

// Update active links based on intersection ratios
function updateActiveLinks() {
  const idMap = {};

  sectionsMap.forEach(({ ids, intersectionRatio }) => {
    ids.forEach(id => {
      idMap[id] = (idMap[id] || 0) + intersectionRatio;
    });
  });

  Object.entries(idMap).forEach(([id, ratio]) => {
    const link = document.querySelector(`nav.toc-new li a[href="#${id}"]`);
    if (link) link.classList.toggle("active", ratio > 0);
  });

  updatePath();
}
