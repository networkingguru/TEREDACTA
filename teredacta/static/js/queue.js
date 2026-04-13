(function () {
  var card = document.getElementById("queue-card");
  var tid = card.dataset.ticket;
  var url = card.dataset.redirect;
  var iv = setInterval(async function () {
    try {
      var r = await fetch("/_queue/status?ticket=" + tid);
      var d = await r.json();
      if (d.ready) {
        clearInterval(iv);
        document.getElementById("status").textContent =
          "Your turn! Redirecting\u2026";
        document.getElementById("bar").style.width = "100%";
        window.location.href = url;
        return;
      }
      if (d.requeue) {
        clearInterval(iv);
        document.getElementById("status").textContent =
          "Re-entering queue\u2026";
        window.location.href = url;
        return;
      }
      document.getElementById("pos").textContent = d.position;
      document.getElementById("wait").textContent =
        "Estimated wait: " + Math.round(d.wait_estimate_seconds) + "s";
    } catch (e) {}
  }, 3000);
})();
