// Offline-only presentation. API/history retain the exact citation handles.
function readableReferences(text) {
  return text.replace(/\[(SRC-[^\]\s]+)\]/g, (citation, handle) => {
    const title = OFFLINE_CITATION_TITLES[handle];
    return title ? `[${title}]` : citation;
  });
}

function createSourcesPanel(sources) {
  const panel = document.createElement("div");
  panel.className = "sources-panel";
  sources.forEach((source) => {
    const chip = document.createElement("span");
    chip.className = "source-chip";
    chip.textContent = source.title || "Demo reference";
    chip.dataset.citationHandle = source.citation_handle || "";
    chip.title = JSON.stringify({
      citation_handle: source.citation_handle, id: source.id,
      source: source.source_file, metadata: source.metadata,
      authority: source.authority, url: source.source_url,
    });
    panel.appendChild(chip);
  });
  return panel;
}
