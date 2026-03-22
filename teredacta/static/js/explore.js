(function() {
    'use strict';

    var currentType = '';
    var currentFilter = '';
    var currentPage = 1;
    var debounceTimer = null;
    var errMsg = '<p style="color:#ef5350;padding:1rem;">Failed to load. Please try again.</p>';

    // --- Entity list ---

    function fetchEntityList(page) {
        currentPage = page || 1;
        var params = new URLSearchParams();
        if (currentType) params.set('type', currentType);
        if (currentFilter) params.set('filter', currentFilter);
        params.set('page', currentPage);

        var panel = document.getElementById('entity-list');
        fetch('/api/entities?' + params.toString())
            .then(function(r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function(html) {
                panel.innerHTML = html;
            })
            .catch(function() {
                panel.innerHTML = errMsg;
            });
    }

    // Expose for "Load more" button in template
    window.loadMoreEntities = function(page) {
        fetchEntityList(page);
    };

    // --- Filter input (debounced) ---

    var filterInput = document.getElementById('entity-filter');
    if (filterInput) {
        filterInput.addEventListener('input', function() {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(function() {
                currentFilter = filterInput.value.trim();
                fetchEntityList(1);
            }, 300);
        });
    }

    // --- Type tabs ---

    var tabContainer = document.getElementById('entity-type-tabs');
    if (tabContainer) {
        tabContainer.addEventListener('click', function(e) {
            var btn = e.target.closest('.tab');
            if (!btn) return;
            // Update active state
            tabContainer.querySelectorAll('.tab').forEach(function(t) {
                t.classList.remove('active');
            });
            btn.classList.add('active');
            currentType = btn.getAttribute('data-type') || '';
            fetchEntityList(1);
        });
    }

    // --- Entity click → connections ---

    document.getElementById('entity-list').addEventListener('click', function(e) {
        var item = e.target.closest('.entity-item');
        if (!item) return;
        var entityId = item.getAttribute('data-entity-id');
        if (!entityId) return;

        // Mark active
        document.querySelectorAll('.entity-item').forEach(function(el) {
            el.classList.remove('active');
        });
        item.classList.add('active');

        // Fetch connections
        var panel = document.getElementById('connections-content');
        fetch('/api/entities/' + entityId + '/connections')
            .then(function(r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function(html) {
                panel.innerHTML = html;
                // Clear preview
                document.getElementById('preview-content').innerHTML =
                    '<p style="color:var(--text-secondary);padding:1rem;">Select a connection to preview.</p>';
            })
            .catch(function() {
                panel.innerHTML = errMsg;
            });

        // Update URL
        history.pushState({ entityId: entityId }, '', '/?entity=' + entityId);
    });

    // --- Connection click → preview or slide ---

    document.getElementById('connections-content').addEventListener('click', function(e) {
        var item = e.target.closest('.connection-item');
        if (!item) return;
        var type = item.getAttribute('data-type');
        var id = item.getAttribute('data-id');
        if (!type || !id) return;

        if (type === 'entity') {
            // Slide to new entity: fetch its connections
            var panel = document.getElementById('connections-content');
            fetch('/api/entities/' + id + '/connections')
                .then(function(r) { if (!r.ok) throw new Error(r.status); return r.text(); })
                .then(function(html) {
                    panel.innerHTML = html;
                    document.getElementById('preview-content').innerHTML =
                        '<p style="color:var(--text-secondary);padding:1rem;">Select a connection to preview.</p>';
                    // Highlight in entity list if visible
                    document.querySelectorAll('.entity-item').forEach(function(el) {
                        el.classList.toggle('active', el.getAttribute('data-entity-id') === id);
                    });
                    history.pushState({ entityId: id }, '', '/?entity=' + id);
                })
                .catch(function() {
                    panel.innerHTML = errMsg;
                });
        } else {
            // Recovery or document → preview in right column
            var url = '/api/preview/' + type + '/' + id;
            var previewPanel = document.getElementById('preview-content');
            fetch(url)
                .then(function(r) { if (!r.ok) throw new Error(r.status); return r.text(); })
                .then(function(html) {
                    previewPanel.innerHTML = html;
                })
                .catch(function() {
                    previewPanel.innerHTML = errMsg;
                });
        }
    });

    // --- Back button support ---

    window.addEventListener('popstate', function(e) {
        if (e.state && e.state.entityId) {
            var panel = document.getElementById('connections-content');
            fetch('/api/entities/' + e.state.entityId + '/connections')
                .then(function(r) { if (!r.ok) throw new Error(r.status); return r.text(); })
                .then(function(html) {
                    panel.innerHTML = html;
                })
                .catch(function() {
                    panel.innerHTML = errMsg;
                });
        } else {
            document.getElementById('connections-content').innerHTML =
                '<p style="color:var(--text-secondary);padding:1rem;">Select an entity to see connections.</p>';
            document.getElementById('preview-content').innerHTML =
                '<p style="color:var(--text-secondary);padding:1rem;">Select a connection to preview.</p>';
        }
    });

    // --- Load entity from URL on page load ---

    var params = new URLSearchParams(window.location.search);
    var initialEntity = params.get('entity');
    if (initialEntity) {
        var panel = document.getElementById('connections-content');
        fetch('/api/entities/' + initialEntity + '/connections')
            .then(function(r) {
                if (!r.ok) throw new Error(r.status);
                return r.text();
            })
            .then(function(html) {
                if (html) {
                    panel.innerHTML = html;
                    history.replaceState({ entityId: initialEntity }, '', '/?entity=' + initialEntity);
                }
            })
            .catch(function() {
                panel.innerHTML = errMsg;
            });
    }
})();
