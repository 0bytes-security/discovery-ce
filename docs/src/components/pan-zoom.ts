import { PanZoomUi } from "@beoe/pan-zoom";
import "@beoe/pan-zoom/css/PanZoomUi.css";

document
  .querySelectorAll(
    ".sl-markdown-content > img[src$='.svg' i]," +
      ".sl-markdown-content > p > img[src$='.svg' i]," +
      ".sl-markdown-content > img[src$='f=svg' i]," +
      ".sl-markdown-content > img[src$='f=svg' i]"
  )
  .forEach((element) => {
    if (element.parentElement?.tagName === "PICTURE") {
      element = element.parentElement;
    }
    const container = document.createElement("figure");
    container.classList.add("beoe", "not-content");
    element.replaceWith(container);
    container.append(element);
    // @ts-expect-error
    new PanZoomUi({ element, container }).on();
  });
