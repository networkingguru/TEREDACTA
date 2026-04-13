(function () {
  var container = document.querySelector(".pdf-comparison");
  var groupId = container.dataset.groupId;
  var primaryPane = document.getElementById("primary-pane");
  var primaryPdfPath = primaryPane ? primaryPane.dataset.pdfPath : "";
  var primaryDocId = primaryPane ? primaryPane.dataset.docId : "";

  function loadText(pane, docId) {
    var viewer = pane.querySelector(".log-viewer");
    if (!viewer) return;
    fetch(
      "/recoveries/" +
        groupId +
        "/member-text?doc_id=" +
        encodeURIComponent(docId)
    )
      .then(function (r) {
        if (!r.ok) throw new Error("Failed to load text");
        return r.text();
      })
      .then(function (html) {
        viewer.innerHTML = html;
      })
      .catch(function () {
        viewer.textContent = "Failed to load document text.";
      });
  }

  function isPdfMode(primaryPath, donorPath) {
    return !!(primaryPath && donorPath);
  }

  function renderPrimaryAsText() {
    var pane = document.getElementById("primary-pane");
    var h4 = pane.querySelector("h4");
    pane.innerHTML = "";
    if (h4) pane.appendChild(h4);
    var div = document.createElement("div");
    div.className = "log-viewer";
    div.id = "primary-text";
    div.style.cssText = "max-height:600px;font-size:0.85rem;line-height:1.7;";
    div.textContent = "Loading...";
    pane.appendChild(div);
    loadText(pane, primaryDocId);
  }

  function renderPrimaryAsPdf() {
    if (!primaryPdfPath) return;
    var pane = document.getElementById("primary-pane");
    var h4 = pane.querySelector("h4");
    pane.innerHTML = "";
    if (h4) pane.appendChild(h4);
    var iframe = document.createElement("iframe");
    iframe.src =
      "/pdf/embed?type=cache&path=" + encodeURIComponent(primaryPdfPath);
    iframe.style.cssText =
      "width:100%;height:600px;border:none;background:#525659;";
    pane.appendChild(iframe);
  }

  window.updateDonor = function (option) {
    var docId = option.value;
    var donorPdfPath = option.dataset.pdfPath;
    var pdfMode = isPdfMode(primaryPdfPath, donorPdfPath);

    var pane = document.getElementById("donor-pane");
    pane.dataset.docId = docId;
    pane.dataset.pdfPath = donorPdfPath || "";
    pane.innerHTML = "";
    var title = document.createElement("h4");
    title.id = "donor-title";
    title.textContent = docId;
    pane.appendChild(title);

    if (pdfMode) {
      var iframe = document.createElement("iframe");
      iframe.id = "donor-iframe";
      iframe.src =
        "/pdf/embed?type=cache&path=" + encodeURIComponent(donorPdfPath);
      iframe.style.cssText =
        "width:100%;height:600px;border:none;background:#525659;";
      pane.appendChild(iframe);
      if (!document.querySelector("#primary-pane iframe")) {
        renderPrimaryAsPdf();
      }
      if (window.setupScrollSync) window.setupScrollSync();
    } else {
      var div = document.createElement("div");
      div.className = "log-viewer";
      div.id = "donor-text";
      div.style.cssText =
        "max-height:600px;font-size:0.85rem;line-height:1.7;";
      div.textContent = "Loading...";
      pane.appendChild(div);
      loadText(pane, docId);
      if (!document.querySelector("#primary-pane .log-viewer")) {
        renderPrimaryAsText();
      }
      if (window.setupScrollSync) window.setupScrollSync();
    }
  };

  // Initial load: if text panes exist, fetch their content
  if (document.getElementById("primary-text")) {
    loadText(document.getElementById("primary-pane"), primaryDocId);
  }
  if (document.getElementById("donor-text")) {
    var donorDocId = document.getElementById("donor-pane").dataset.docId;
    loadText(document.getElementById("donor-pane"), donorDocId);
  }
})();
