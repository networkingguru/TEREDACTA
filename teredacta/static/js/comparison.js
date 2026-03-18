(function() {
    let syncing = false;

    function attachScrollSync(iframe, otherIframe) {
        iframe.addEventListener('load', function() {
            const doc = iframe.contentDocument || iframe.contentWindow.document;
            const container = doc.getElementById('viewerContainer');
            if (!container) return;
            container.addEventListener('scroll', function() {
                if (syncing) return;
                syncing = true;
                try {
                    const otherDoc = otherIframe.contentDocument || otherIframe.contentWindow.document;
                    const otherContainer = otherDoc.getElementById('viewerContainer');
                    if (otherContainer && container.scrollHeight > container.clientHeight) {
                        const ratio = container.scrollTop / (container.scrollHeight - container.clientHeight);
                        const otherMax = otherContainer.scrollHeight - otherContainer.clientHeight;
                        if (otherMax > 0) {
                            otherContainer.scrollTop = ratio * otherMax;
                        }
                    }
                } catch (e) { /* cross-origin or not loaded yet */ }
                requestAnimationFrame(function() { syncing = false; });
            });
        });
    }

    function setupComparison() {
        const panes = document.querySelectorAll('.pdf-pane iframe');
        if (panes.length < 2) return;
        attachScrollSync(panes[0], panes[1]);
        attachScrollSync(panes[1], panes[0]);
    }

    window.toggleComparison = function(btn) {
        const container = document.querySelector('.pdf-comparison');
        if (container) {
            container.classList.toggle('single-view');
            btn.textContent = container.classList.contains('single-view') ? 'Side by Side' : 'Single View';
        }
    };

    // Re-setup scroll sync when donor iframe changes
    window.setupScrollSync = function() {
        setupComparison();
    };

    document.addEventListener('DOMContentLoaded', setupComparison);
    document.addEventListener('htmx:afterSwap', setupComparison);
})();
