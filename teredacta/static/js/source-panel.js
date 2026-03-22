(function() {
    "use strict";

    var currentIndex = -1;
    var segments = [];

    function getGroupId() {
        var el = document.querySelector("[data-group-id]");
        return el ? el.getAttribute("data-group-id") : null;
    }

    function collectSegments() {
        segments = Array.from(document.querySelectorAll("[data-segment-index]"));
    }

    function openSourcePanel(groupId, segmentIndex) {
        var panel = document.getElementById("source-panel");
        if (!panel) return;

        fetch("/recoveries/" + groupId + "/source?segment_index=" + segmentIndex)
            .then(function(r) { return r.ok ? r.text() : ""; })
            .then(function(html) {
                if (!html) return;
                panel.innerHTML = html;
                panel.classList.add("open");
                // Shift merged text to make room
                var viewer = document.querySelector(".merged-text-viewer");
                if (viewer) viewer.classList.add("merged-text-with-panel");
                // Attach close handler
                var closeBtn = panel.querySelector(".source-panel-close");
                if (closeBtn) {
                    closeBtn.addEventListener("click", closeSourcePanel);
                }
            });
    }

    function closeSourcePanel() {
        var panel = document.getElementById("source-panel");
        if (panel) {
            panel.classList.remove("open");
        }
        var viewer = document.querySelector(".merged-text-viewer");
        if (viewer) viewer.classList.remove("merged-text-with-panel");
        currentIndex = -1;
    }

    function navigateTo(index) {
        if (index < 0 || index >= segments.length) return;
        currentIndex = index;
        var el = segments[index];
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.click();
    }

    function attach() {
        collectSegments();

        // Click handler for recovered passages
        document.addEventListener("click", function(e) {
            var target = e.target.closest("[data-segment-index]");
            if (!target) return;

            var groupId = getGroupId();
            if (!groupId) return;

            var segIdx = parseInt(target.getAttribute("data-segment-index"), 10);
            currentIndex = segments.indexOf(target);
            openSourcePanel(groupId, segIdx);
        });

        // Keyboard navigation
        document.addEventListener("keydown", function(e) {
            // Don't intercept when typing in inputs
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
            if (segments.length === 0) return;

            if (e.key === "j") {
                e.preventDefault();
                navigateTo(currentIndex + 1);
            } else if (e.key === "k") {
                e.preventDefault();
                navigateTo(Math.max(0, currentIndex - 1));
            } else if (e.key === "Escape") {
                closeSourcePanel();
            }
        });
    }

    // Build nav arrows
    function buildNav() {
        var nav = document.createElement("div");
        nav.className = "recovery-nav";
        nav.id = "recovery-nav";

        var upBtn = document.createElement("button");
        upBtn.innerHTML = "&#9650;";
        upBtn.title = "Jump to previous recovered passage (keyboard: k)";
        upBtn.addEventListener("click", function() {
            collectSegments();
            if (currentIndex > 0) navigateTo(currentIndex - 1);
        });

        var downBtn = document.createElement("button");
        downBtn.innerHTML = "&#9660;";
        downBtn.title = "Jump to next recovered passage (keyboard: j)";
        downBtn.addEventListener("click", function() {
            collectSegments();
            if (currentIndex < segments.length - 1) navigateTo(currentIndex + 1);
            else if (currentIndex === -1 && segments.length > 0) navigateTo(0);
        });

        nav.appendChild(upBtn);
        nav.appendChild(downBtn);
        document.body.appendChild(nav);
    }

    // Initialize
    attach();
    buildNav();

    // Re-attach after HTMX swaps
    document.addEventListener("htmx:afterSwap", function() {
        collectSegments();
        // Rebuild nav if missing
        if (!document.getElementById("recovery-nav")) buildNav();
    });
})();
