(function() {
    var syncing = false;
    var cleanupFns = [];

    function cleanup() {
        cleanupFns.forEach(function(fn) { fn(); });
        cleanupFns = [];
    }

    function addScrollListener(el, handler) {
        el.addEventListener('scroll', handler);
        cleanupFns.push(function() { el.removeEventListener('scroll', handler); });
    }

    function attachIframeScrollSync(iframe, otherIframe) {
        iframe.addEventListener('load', function() {
            var doc = iframe.contentDocument || iframe.contentWindow.document;
            var container = doc.getElementById('viewerContainer');
            if (!container) return;
            var handler = function() {
                if (syncing) return;
                syncing = true;
                try {
                    var otherDoc = otherIframe.contentDocument || otherIframe.contentWindow.document;
                    var otherContainer = otherDoc.getElementById('viewerContainer');
                    if (otherContainer && container.scrollHeight > container.clientHeight) {
                        var ratio = container.scrollTop / (container.scrollHeight - container.clientHeight);
                        var otherMax = otherContainer.scrollHeight - otherContainer.clientHeight;
                        if (otherMax > 0) {
                            otherContainer.scrollTop = ratio * otherMax;
                        }
                    }
                } catch (e) { /* cross-origin or not loaded yet */ }
                requestAnimationFrame(function() { syncing = false; });
            };
            addScrollListener(container, handler);
        });
    }

    function attachTextScrollSync(div1, div2) {
        function syncScroll(source, target) {
            var handler = function() {
                if (syncing) return;
                syncing = true;
                var maxScroll = source.scrollHeight - source.clientHeight;
                if (maxScroll > 0) {
                    var ratio = source.scrollTop / maxScroll;
                    var targetMax = target.scrollHeight - target.clientHeight;
                    if (targetMax > 0) {
                        target.scrollTop = ratio * targetMax;
                    }
                }
                requestAnimationFrame(function() { syncing = false; });
            };
            addScrollListener(source, handler);
        }
        syncScroll(div1, div2);
        syncScroll(div2, div1);
    }

    function setupComparison() {
        cleanup();
        var textPanes = document.querySelectorAll('.pdf-pane .log-viewer');
        if (textPanes.length >= 2) {
            attachTextScrollSync(textPanes[0], textPanes[1]);
            return;
        }
        var iframes = document.querySelectorAll('.pdf-pane iframe');
        if (iframes.length >= 2) {
            attachIframeScrollSync(iframes[0], iframes[1]);
            attachIframeScrollSync(iframes[1], iframes[0]);
        }
    }

    window.toggleComparison = function(btn) {
        var container = document.querySelector('.pdf-comparison');
        if (container) {
            container.classList.toggle('single-view');
            btn.textContent = container.classList.contains('single-view') ? 'Side by Side' : 'Single View';
        }
    };

    window.setupScrollSync = function() {
        setTimeout(setupComparison, 100);
    };

    document.addEventListener('DOMContentLoaded', setupComparison);
    document.addEventListener('htmx:afterSwap', setupComparison);
})();
