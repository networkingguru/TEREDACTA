(function () {
  var container = document.querySelector(".pdf-comparison");
  var groupId = container.dataset.groupId;
  var pane = document.getElementById("primary-pane");
  var viewer = pane ? pane.querySelector(".log-viewer") : null;
  if (viewer) {
    var docId = pane.dataset.docId;
    fetch(
      "/recoveries/" +
        groupId +
        "/member-text?doc_id=" +
        encodeURIComponent(docId)
    )
      .then(function (r) {
        return r.ok ? r.text() : Promise.reject();
      })
      .then(function (html) {
        viewer.innerHTML = html;
      })
      .catch(function () {
        viewer.textContent = "Failed to load document text.";
      });
  }
})();
