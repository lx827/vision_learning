const tabs = [...document.querySelectorAll(".module-tab")];
const pages = [...document.querySelectorAll(".page-view")];

function selectPage(pageId, updateHash = true) {
  tabs.forEach((tab) => tab.classList.toggle("selected", tab.dataset.page === pageId));
  pages.forEach((page) => page.classList.toggle("visible", page.id === pageId));
  if (updateHash) history.replaceState(null, "", `#${pageId.replace("-page", "")}`);
}

tabs.forEach((tab) => tab.addEventListener("click", () => selectPage(tab.dataset.page)));
const initialPage = location.hash === "#count" ? "count-page" : "camera-page";
selectPage(initialPage, false);
