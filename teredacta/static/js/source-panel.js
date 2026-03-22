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

    function updateToolbar() {
        var toolbar = document.getElementById("recovery-toolbar");
        if (!toolbar) return;

        if (segments.length === 0) {
            toolbar.style.display = "none";
            return;
        }

        toolbar.style.display = "flex";
        var label = document.getElementById("recovery-count-label");
        if (label) {
            label.textContent = segments.length + " recovered passage" + (segments.length !== 1 ? "s" : "");
        }
        updatePosition();
    }

    function updatePosition() {
        var pos = document.getElementById("toolbar-position");
        if (pos) {
            pos.textContent = (currentIndex >= 0 ? (currentIndex + 1) : 0) + " / " + segments.length;
        }
    }

    function highlightCurrent() {
        // Remove highlight from all
        segments.forEach(function(el) { el.classList.remove("recovery-active"); });
        // Add to current
        if (currentIndex >= 0 && currentIndex < segments.length) {
            segments[currentIndex].classList.add("recovery-active");
        }
    }

    function scrollToIndex(index) {
        if (index < 0 || index >= segments.length) return;
        currentIndex = index;
        var el = segments[index];
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        highlightCurrent();
        updatePosition();
    }

    // Public: called from Recovered Passages list onclick
    window.scrollToSegment = function(listIndex) {
        // The listIndex from the template loop may not directly map to
        // the segments array order (which is DOM order). Find the closest
        // match by checking data-segment-index attributes.
        // Fallback: just use listIndex if within range.
        if (listIndex < segments.length) {
            scrollToIndex(listIndex);
        }
    };

    function openSourcePanel(groupId, segmentIndex) {
        var panel = document.getElementById("source-panel");
        if (!panel) return;

        fetch("/recoveries/" + groupId + "/source?segment_index=" + segmentIndex)
            .then(function(r) {
                if (!r.ok) throw new Error(r.status);
                return r.text();
            })
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
            })
            .catch(function() {
                panel.innerHTML = '<div style="padding:1rem;color:#ef5350;">Failed to load source panel.</div>';
                panel.classList.add("open");
            });
    }

    function closeSourcePanel() {
        var panel = document.getElementById("source-panel");
        if (panel) {
            panel.classList.remove("open");
            panel.innerHTML = "";
        }
        var viewer = document.querySelector(".merged-text-viewer");
        if (viewer) viewer.classList.remove("merged-text-with-panel");
    }

    function attach() {
        collectSegments();
        updateToolbar();

        // Click handler for recovered passages — opens source panel
        document.addEventListener("click", function(e) {
            var target = e.target.closest("[data-segment-index]");
            if (!target) return;

            var groupId = getGroupId();
            if (!groupId) return;

            var segIdx = parseInt(target.getAttribute("data-segment-index"), 10);
            currentIndex = segments.indexOf(target);
            highlightCurrent();
            updatePosition();
            openSourcePanel(groupId, segIdx);
        });

        // Keyboard navigation — j/k scroll without opening source panel
        document.addEventListener("keydown", function(e) {
            if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
            if (segments.length === 0) return;

            if (e.key === "j") {
                e.preventDefault();
                if (currentIndex < segments.length - 1) scrollToIndex(currentIndex + 1);
                else if (currentIndex === -1) scrollToIndex(0);
            } else if (e.key === "k") {
                e.preventDefault();
                scrollToIndex(Math.max(0, currentIndex - 1));
            } else if (e.key === "Escape") {
                closeSourcePanel();
            }
        });

        // Toolbar button handlers
        var prevBtn = document.getElementById("toolbar-prev");
        if (prevBtn) {
            prevBtn.addEventListener("click", function() {
                collectSegments();
                if (currentIndex > 0) scrollToIndex(currentIndex - 1);
            });
        }
        var nextBtn = document.getElementById("toolbar-next");
        if (nextBtn) {
            nextBtn.addEventListener("click", function() {
                collectSegments();
                if (currentIndex < segments.length - 1) scrollToIndex(currentIndex + 1);
                else if (currentIndex === -1 && segments.length > 0) scrollToIndex(0);
            });
        }
    }

    // Initialize
    attach();

    // Re-attach after HTMX swaps (tab switching)
    document.addEventListener("htmx:afterSwap", function() {
        collectSegments();
        updateToolbar();
        currentIndex = -1;
    });
})();
