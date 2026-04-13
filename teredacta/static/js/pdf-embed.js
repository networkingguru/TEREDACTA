import * as pdfjsLib from "/static/js/pdfjs/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/js/pdfjs/pdf.worker.min.mjs";

var container = document.getElementById("viewerContainer");
var errorEl = document.getElementById("error");
var pdfUrl = container.dataset.pdfUrl;
var pdfDoc = null;

async function renderPDF() {
  container.innerHTML = "";
  try {
    if (!pdfDoc) {
      pdfDoc = await pdfjsLib.getDocument(pdfUrl).promise;
    }
    var containerWidth = container.clientWidth;

    for (var i = 1; i <= pdfDoc.numPages; i++) {
      var page = await pdfDoc.getPage(i);
      var baseViewport = page.getViewport({ scale: 1 });
      var scale = (containerWidth - 16) / baseViewport.width;
      var viewport = page.getViewport({ scale: scale });

      var canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      container.appendChild(canvas);

      await page.render({
        canvasContext: canvas.getContext("2d"),
        viewport: viewport,
      }).promise;
    }
  } catch (e) {
    console.error("PDF render error:", e);
    errorEl.style.display = "block";
  }
}

var resizeTimer;
window.addEventListener("resize", function () {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(renderPDF, 300);
});

renderPDF();
