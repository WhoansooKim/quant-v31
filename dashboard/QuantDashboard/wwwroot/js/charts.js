/**
 * Quant V4 — Chart.js Helper (Blazor IJSRuntime interop)
 * - X-axis aligned BUY/SELL markers (sparse line datasets, not scatter)
 * - Custom drag zoom: left→right = zoom in, right→left = zoom out
 * - Right-click drag to pan (scroll) when zoomed in
 * - Double-click to reset zoom
 */
window.chartHelper = {
    _instances: {},

    /**
     * Zoom plugin config.
     * Pinch zoom enabled for touch devices.
     * Pan enabled for touch (one-finger when zoomed).
     * Drag zoom handled by custom _setupZoomable (mouse + touch).
     */
    _zoomOpts: {
        zoom: {
            mode: 'x',
            pinch: { enabled: true }
        },
        pan: {
            enabled: false,
            mode: 'x',
        },
        limits: { x: { minRange: 10 } }
    },

    /** Bind right-click drag → pan on a canvas/chart pair */
    _bindRightClickPan: function(canvas, chart) {
        var panning = false;
        var lastX = 0;

        canvas.addEventListener('contextmenu', function(e) { e.preventDefault(); });

        canvas.addEventListener('mousedown', function(e) {
            if (e.button === 2 && chart.__zoomed) {
                panning = true;
                lastX = e.clientX;
                canvas.style.cursor = 'grabbing';
                e.preventDefault();
            }
        });

        window.addEventListener('mousemove', function(e) {
            if (!panning) return;
            var dx = e.clientX - lastX;
            lastX = e.clientX;
            if (dx !== 0) {
                chart.pan({ x: dx }, undefined, 'none');
            }
        });

        window.addEventListener('mouseup', function(e) {
            if (panning) {
                panning = false;
                canvas.style.cursor = '';
            }
        });
    },

    /** Update __zoomed flag based on current scale range */
    _updateZoomFlag: function(chart) {
        var scale = chart.scales.x;
        var total = chart.data.labels.length;
        chart.__zoomed = !(scale.min <= 0 && scale.max >= total - 1);
    },

    /**
     * Full custom drag zoom: left-drag + selection overlay
     *   left→right = zoom into selection
     *   right→left = zoom out one step (expand range by 2x)
     * Also: double-click/double-tap = reset, right-click drag = pan
     * Touch: single-finger drag = zoom selection, pinch = zoom (via plugin), pan when zoomed (via plugin)
     */
    _setupZoomable: function(canvas, chart) {
        var self = this;
        var dragging = false;
        var startX = 0;
        var overlay = null;

        // Create selection overlay div (positioned over the canvas)
        function createOverlay() {
            var el = document.createElement('div');
            el.style.position = 'absolute';
            el.style.top = '0';
            el.style.height = '100%';
            el.style.pointerEvents = 'none';
            el.style.zIndex = '5';
            el.style.borderRadius = '2px';
            // Ensure parent is positioned
            var parent = canvas.parentElement;
            if (parent && getComputedStyle(parent).position === 'static') {
                parent.style.position = 'relative';
            }
            return el;
        }

        function updateOverlay(currentX) {
            if (!overlay) return;
            var rect = canvas.getBoundingClientRect();
            var dx = currentX - startX;
            if (dx >= 0) {
                overlay.style.left = (startX - rect.left) + 'px';
                overlay.style.width = dx + 'px';
                overlay.style.background = 'rgba(25,127,230,0.15)';
                overlay.style.border = '1px solid rgba(25,127,230,0.4)';
            } else {
                overlay.style.left = (currentX - rect.left) + 'px';
                overlay.style.width = (-dx) + 'px';
                overlay.style.background = 'rgba(249,115,22,0.15)';
                overlay.style.border = '1px solid rgba(249,115,22,0.4)';
            }
        }

        function applyZoom(endX) {
            var dx = endX - startX;
            var threshold = 30;

            if (dx > threshold) {
                var rect = canvas.getBoundingClientRect();
                var scale = chart.scales.x;
                var chartArea = chart.chartArea;
                var pixelStart = Math.max(startX - rect.left, chartArea.left);
                var pixelEnd = Math.min(endX - rect.left, chartArea.right);
                var idxStart = scale.getValueForPixel(pixelStart);
                var idxEnd = scale.getValueForPixel(pixelEnd);
                var minIdx = Math.max(0, Math.round(Math.min(idxStart, idxEnd)));
                var maxIdx = Math.min(chart.data.labels.length - 1, Math.round(Math.max(idxStart, idxEnd)));
                if (maxIdx - minIdx >= 2) {
                    chart.zoomScale('x', { min: minIdx, max: maxIdx }, 'default');
                    self._updateZoomFlag(chart);
                }
            } else if (dx < -threshold) {
                if (chart.__zoomed) {
                    var scale = chart.scales.x;
                    var currentMin = Math.round(scale.min);
                    var currentMax = Math.round(scale.max);
                    var currentRange = currentMax - currentMin;
                    var expand = Math.max(Math.round(currentRange * 0.5), 5);
                    var totalLabels = chart.data.labels.length;
                    var newMin = Math.max(0, currentMin - expand);
                    var newMax = Math.min(totalLabels - 1, currentMax + expand);
                    chart.zoomScale('x', { min: newMin, max: newMax }, 'default');
                    self._updateZoomFlag(chart);
                }
                // If not zoomed, right→left drag is a no-op (nothing to zoom out from)
            }
        }

        function removeOverlay() {
            if (overlay && overlay.parentElement) {
                overlay.parentElement.removeChild(overlay);
            }
            overlay = null;
        }

        // ─── Mouse events (desktop) ───
        canvas.addEventListener('mousedown', function(e) {
            if (e.button !== 0) return;
            // Clean up any stale overlay from a previous drag
            removeOverlay();
            dragging = true;
            startX = e.clientX;
            overlay = createOverlay();
            var rect = canvas.getBoundingClientRect();
            overlay.style.left = (e.clientX - rect.left) + 'px';
            overlay.style.width = '0px';
            canvas.parentElement.appendChild(overlay);
        });

        window.addEventListener('mousemove', function(e) {
            if (!dragging || !overlay) return;
            updateOverlay(e.clientX);
        });

        window.addEventListener('mouseup', function(e) {
            if (!dragging) return;
            dragging = false;
            applyZoom(e.clientX);
            removeOverlay();
            // Safety: remove any stale overlay children from parent
            var parent = canvas.parentElement;
            if (parent) {
                var stale = parent.querySelectorAll('div[style*="pointer-events: none"]');
                stale.forEach(function(el) { el.remove(); });
            }
        });

        // Double-click to reset zoom
        canvas.addEventListener('dblclick', function() {
            if (chart.__zoomed) {
                chart.resetZoom('default');
                chart.__zoomed = false;
            }
        });

        // Right-click drag to pan
        this._bindRightClickPan(canvas, chart);

        // ─── Touch events (mobile) ───
        var touchDragging = false;
        var touchStartX = 0;
        var touchStartY = 0;
        var touchLocked = false;   // true once we confirm horizontal drag
        var lastTapTime = 0;

        canvas.addEventListener('touchstart', function(e) {
            // Always clean up stale overlay on new touch
            removeOverlay();
            if (e.touches.length !== 1) {
                // Multi-touch: let plugin handle pinch
                touchDragging = false;
                touchLocked = false;
                return;
            }

            // Double-tap detection
            var now = Date.now();
            if (now - lastTapTime < 300) {
                // Double tap — reset zoom
                e.preventDefault();
                if (chart.__zoomed) {
                    chart.resetZoom('default');
                    chart.__zoomed = false;
                }
                touchDragging = false;
                lastTapTime = 0;
                return;
            }
            lastTapTime = now;

            var touch = e.touches[0];
            touchStartX = touch.clientX;
            touchStartY = touch.clientY;
            touchDragging = true;
            touchLocked = false;
        }, { passive: false });

        canvas.addEventListener('touchmove', function(e) {
            if (!touchDragging || e.touches.length !== 1) return;
            var touch = e.touches[0];
            var dx = touch.clientX - touchStartX;
            var dy = touch.clientY - touchStartY;

            // Direction lock: first 10px of movement determines horizontal vs vertical
            if (!touchLocked) {
                if (Math.abs(dx) > 10 || Math.abs(dy) > 10) {
                    if (Math.abs(dx) > Math.abs(dy)) {
                        // Horizontal — lock for chart zoom
                        touchLocked = true;
                        startX = touchStartX;
                        overlay = createOverlay();
                        var rect = canvas.getBoundingClientRect();
                        overlay.style.left = (touchStartX - rect.left) + 'px';
                        overlay.style.width = '0px';
                        canvas.parentElement.appendChild(overlay);
                    } else {
                        // Vertical — cancel, let page scroll
                        touchDragging = false;
                        return;
                    }
                } else {
                    return; // Not enough movement yet
                }
            }

            e.preventDefault();
            updateOverlay(touch.clientX);
        }, { passive: false });

        canvas.addEventListener('touchend', function(e) {
            if (!touchDragging || !touchLocked) {
                touchDragging = false;
                touchLocked = false;
                return;
            }
            var touch = e.changedTouches[0];
            applyZoom(touch.clientX);
            removeOverlay();
            touchDragging = false;
            touchLocked = false;
        });

        canvas.addEventListener('touchcancel', function() {
            touchDragging = false;
            touchLocked = false;
            removeOverlay();
        });

        // Update zoom flag after plugin pinch/pan events
        chart.options.plugins.zoom.zoom.onZoomComplete = function(ctx) {
            self._updateZoomFlag(ctx.chart);
        };
        chart.options.plugins.zoom.pan.onPanComplete = function(ctx) {
            self._updateZoomFlag(ctx.chart);
        };
    },

    /**
     * Adaptive x-axis tick config.
     * Labels should be full dates (yyyy-MM-dd).
     */
    _adaptiveXTicks: function(labels) {
        return {
            color: '#5b6280',
            font: { size: 10 },
            maxRotation: 0,
            autoSkip: true,
            callback: function(value, index) {
                var label = labels[value] || '';
                if (label.length < 10) return label;

                var scale = this;
                var minIdx = Math.max(0, Math.floor(scale.min));
                var maxIdx = Math.min(labels.length - 1, Math.ceil(scale.max));
                var visibleCount = maxIdx - minIdx + 1;

                var yyyy = label.substring(0, 4);
                var mm   = label.substring(5, 7);
                var dd   = label.substring(8, 10);

                if (visibleCount > 365 * 3) {
                    if (dd === '01') return yyyy + '-' + mm;
                    return null;
                } else if (visibleCount > 180) {
                    if (dd === '01') return yyyy + '-' + mm;
                    return null;
                } else if (visibleCount > 60) {
                    var dayNum = parseInt(dd, 10);
                    if (dayNum === 1 || dayNum === 15) return mm + '/' + dd;
                    return null;
                } else {
                    return mm + '/' + dd;
                }
            }
        };
    },

    createLine: function (canvasId, labels, datasets, options) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        var self = this;
        var hasDateLabels = labels.length > 0 && /^\d{4}-\d{2}/.test(labels[0]);
        var xTicks = hasDateLabels ? self._adaptiveXTicks(labels) : { color: '#5b6280', font: { size: 10 } };
        var cfg = {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: Object.assign({
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { labels: { color: '#9ca3c0', font: { size: 11 } } },
                    tooltip: {
                        backgroundColor: 'rgba(22,22,40,0.95)',
                        titleColor: '#f0f2ff',
                        bodyColor: '#9ca3c0',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1
                    },
                    zoom: { zoom: self._zoomOpts.zoom, pan: self._zoomOpts.pan, limits: self._zoomOpts.limits }
                },
                scales: {
                    x: {
                        ticks: xTicks,
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    },
                    y: {
                        ticks: { color: '#5b6280', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    }
                }
            }, options || {})
        };
        var chart = new Chart(ctx, cfg);
        this._instances[canvasId] = chart;
        this._setupZoomable(ctx, chart);
    },

    createBar: function (canvasId, labels, datasets, options) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        var cfg = {
            type: 'bar',
            data: { labels: labels, datasets: datasets },
            options: Object.assign({
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#9ca3c0', font: { size: 11 } } },
                    tooltip: {
                        backgroundColor: 'rgba(22,22,40,0.95)',
                        titleColor: '#f0f2ff',
                        bodyColor: '#9ca3c0',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1
                    },
                    annotation: options && options.annotationLine ? {
                        annotations: {
                            line1: {
                                type: 'line',
                                yMin: options.annotationLine,
                                yMax: options.annotationLine,
                                borderColor: '#ff4757',
                                borderWidth: 1,
                                borderDash: [4, 4],
                                label: {
                                    display: true,
                                    content: options.annotationLabel || '',
                                    color: '#ff4757',
                                    font: { size: 10 }
                                }
                            }
                        }
                    } : {}
                },
                scales: {
                    x: {
                        ticks: { color: '#5b6280', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    },
                    y: {
                        ticks: { color: '#5b6280', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    }
                }
            }, options || {})
        };
        this._instances[canvasId] = new Chart(ctx, cfg);
    },

    createDoughnut: function (canvasId, labels, data, colors) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        var cfg = {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors || [
                        '#6366f1', '#00c896', '#ffa502',
                        '#22d3ee', '#a78bfa', '#5b6280'
                    ],
                    borderColor: 'rgba(13,13,26,0.8)',
                    borderWidth: 2,
                    hoverBorderColor: '#f0f2ff',
                    hoverBorderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: '#9ca3c0',
                            font: { size: 11 },
                            padding: 12,
                            usePointStyle: true,
                            pointStyleWidth: 10
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(22,22,40,0.95)',
                        titleColor: '#f0f2ff',
                        bodyColor: '#9ca3c0',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(ctx) {
                                return ctx.label + ': ' + ctx.parsed.toFixed(1) + '%';
                            }
                        }
                    }
                }
            }
        };
        this._instances[canvasId] = new Chart(ctx, cfg);
    },

    createHorizontalBar: function (canvasId, labels, data, options) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        var colors = data.map(function(v) { return v >= 0 ? '#00c896' : '#ff4757'; });
        var cfg = {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors,
                    borderRadius: 4,
                    barThickness: 18
                }]
            },
            options: Object.assign({
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(22,22,40,0.95)',
                        titleColor: '#f0f2ff',
                        bodyColor: '#9ca3c0',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        callbacks: {
                            label: function(ctx) {
                                return '점수: ' + ctx.parsed.x.toFixed(3);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: { color: '#5b6280', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.05)' }
                    },
                    y: {
                        ticks: { color: '#9ca3c0', font: { size: 11 } },
                        grid: { display: false }
                    }
                }
            }, options || {})
        };
        this._instances[canvasId] = new Chart(ctx, cfg);
    },

    createMultiLine: function (canvasId, labels, datasets, options) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;
        var self = this;
        var hasDateLabels = labels.length > 0 && /^\d{4}-\d{2}/.test(labels[0]);
        var xTicks = hasDateLabels ? self._adaptiveXTicks(labels) : { color: '#5b6280', font: { size: 10 } };
        var cfg = {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: Object.assign({
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: { color: '#9ca3c0', font: { size: 11 }, usePointStyle: true, pointStyleWidth: 10 }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(22,22,40,0.95)',
                        titleColor: '#f0f2ff',
                        bodyColor: '#9ca3c0',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1
                    },
                    zoom: { zoom: self._zoomOpts.zoom, pan: self._zoomOpts.pan, limits: self._zoomOpts.limits }
                },
                scales: {
                    x: {
                        ticks: xTicks,
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    },
                    y: {
                        ticks: { color: '#5b6280', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    }
                }
            }, options || {})
        };
        var chart = new Chart(ctx, cfg);
        this._instances[canvasId] = chart;
        this._setupZoomable(ctx, chart);
    },

    /**
     * Equity line + BUY/SELL markers (sparse line datasets — same category x-axis)
     */
    createLineWithTrades: function (canvasId, labels, lineDatasets, buyData, sellData, dotNetRef) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx) return;

        var datasets = lineDatasets.slice();
        var self = this;
        var hasDateLabels = labels.length > 0 && /^\d{4}-\d{2}/.test(labels[0]);
        var xTicks = hasDateLabels ? self._adaptiveXTicks(labels) : { color: '#5b6280', font: { size: 10 } };

        var buyMeta = (buyData && buyData.meta) || [];
        var sellMeta = (sellData && sellData.meta) || [];

        if (buyData && buyData.values && buyData.values.length > 0) {
            var buyRadius = buyData.values.map(function(v) { return v != null ? 7 : 0; });
            datasets.push({
                label: 'BUY',
                data: buyData.values,
                showLine: false,
                pointStyle: 'triangle',
                pointRadius: buyRadius,
                pointHoverRadius: buyRadius.map(function(r) { return r > 0 ? 10 : 0; }),
                backgroundColor: '#22c55e',
                borderColor: '#22c55e',
                order: 0
            });
        }

        if (sellData && sellData.values && sellData.values.length > 0) {
            var sellRadius = sellData.values.map(function(v) { return v != null ? 7 : 0; });
            datasets.push({
                label: 'SELL',
                data: sellData.values,
                showLine: false,
                pointStyle: 'triangle',
                rotation: 180,
                pointRadius: sellRadius,
                pointHoverRadius: sellRadius.map(function(r) { return r > 0 ? 10 : 0; }),
                backgroundColor: '#ef4444',
                borderColor: '#ef4444',
                order: 0
            });
        }

        var cfg = {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest', intersect: true },
                plugins: {
                    legend: { labels: { color: '#9ca3c0', font: { size: 11 }, usePointStyle: true, pointStyleWidth: 10 } },
                    tooltip: {
                        backgroundColor: 'rgba(22,22,40,0.95)',
                        titleColor: '#f0f2ff',
                        bodyColor: '#9ca3c0',
                        borderColor: 'rgba(255,255,255,0.08)',
                        borderWidth: 1,
                        filter: function(item) {
                            return item.raw != null;
                        },
                        callbacks: {
                            title: function(items) {
                                if (!items.length) return '';
                                var item = items[0];
                                var idx = item.dataIndex;
                                var dsLabel = item.dataset.label;
                                var meta = null;
                                if (dsLabel === 'BUY' && buyMeta[idx]) meta = buyMeta[idx];
                                else if (dsLabel === 'SELL' && sellMeta[idx]) meta = sellMeta[idx];
                                if (meta) return meta.date || labels[idx] || '';
                                return labels[idx] || '';
                            },
                            label: function(item) {
                                var idx = item.dataIndex;
                                var dsLabel = item.dataset.label;
                                var meta = null;
                                if (dsLabel === 'BUY' && buyMeta[idx]) meta = buyMeta[idx];
                                else if (dsLabel === 'SELL' && sellMeta[idx]) meta = sellMeta[idx];
                                if (meta) {
                                    var lines = [dsLabel + ': ' + meta.symbol];
                                    lines.push('Price: $' + (meta.price || 0).toFixed(2) + '  Qty: ' + (meta.qty || 0).toFixed(1));
                                    if (meta.pnl !== undefined && meta.pnl !== null && meta.pnl !== 0) {
                                        var sign = meta.pnl >= 0 ? '+' : '';
                                        lines.push('P&L: ' + sign + '$' + meta.pnl.toFixed(2) + ' (' + sign + (meta.pnlPct * 100).toFixed(1) + '%)');
                                    }
                                    if (meta.reason) lines.push('Reason: ' + meta.reason);
                                    if (meta.holdDays) lines.push('Hold: ' + meta.holdDays + 'd');
                                    return lines;
                                }
                                return dsLabel + ': $' + item.parsed.y.toFixed(0);
                            }
                        }
                    },
                    zoom: { zoom: self._zoomOpts.zoom, pan: self._zoomOpts.pan, limits: self._zoomOpts.limits }
                },
                scales: {
                    x: {
                        ticks: xTicks,
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    },
                    y: {
                        ticks: { color: '#5b6280', font: { size: 10 } },
                        grid: { color: 'rgba(255,255,255,0.04)' }
                    }
                },
                onClick: function(evt, elements) {
                    if (!dotNetRef || !elements || !elements.length) return;
                    var el = elements[0];
                    var ds = cfg.data.datasets[el.datasetIndex];
                    if (ds.label !== 'BUY' && ds.label !== 'SELL') return;
                    var idx = el.index;
                    var meta = null;
                    if (ds.label === 'BUY' && buyMeta[idx]) meta = buyMeta[idx];
                    else if (ds.label === 'SELL' && sellMeta[idx]) meta = sellMeta[idx];
                    if (meta && meta.date) {
                        dotNetRef.invokeMethodAsync('OnTradeMarkerClicked', meta.date);
                    }
                }
            }
        };
        var chart = new Chart(ctx, cfg);
        this._instances[canvasId] = chart;
        this._setupZoomable(ctx, chart);
    },

    /** Intraday chart — Pre-market / Regular / After-hours with prev close line */
    createIntraday: function (canvasId, labels, prices, sessions, prevClose) {
        var canvas = document.getElementById(canvasId);
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        if (this._instances[canvasId]) {
            this._instances[canvasId].destroy();
        }

        // Build segment colors: pre=teal, regular=green/red, post=orange
        var segmentColors = [];
        var firstRegularPrice = prevClose || prices[0];
        for (var i = 0; i < sessions.length; i++) {
            if (sessions[i] === 'pre') segmentColors.push('rgba(0,188,212,0.8)');
            else if (sessions[i] === 'post') segmentColors.push('rgba(255,152,0,0.8)');
            else segmentColors.push(prices[i] >= firstRegularPrice ? 'rgba(34,197,94,0.8)' : 'rgba(239,68,68,0.8)');
        }

        // Build fill colors (lighter)
        var fillColors = sessions.map(function(s) {
            if (s === 'pre') return 'rgba(0,188,212,0.05)';
            if (s === 'post') return 'rgba(255,152,0,0.05)';
            return 'rgba(34,197,94,0.05)';
        });

        // Prev close annotation line data
        var prevCloseData = prevClose ? labels.map(function() { return prevClose; }) : null;

        var datasets = [{
            data: prices,
            borderColor: function(ctx2) {
                var i = ctx2.p0DataIndex;
                return segmentColors[i] || 'rgba(34,197,94,0.8)';
            },
            backgroundColor: 'rgba(34,197,94,0.06)',
            fill: true,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            segment: {
                borderColor: function(ctx2) {
                    return segmentColors[ctx2.p0DataIndex] || 'rgba(34,197,94,0.8)';
                }
            }
        }];

        if (prevCloseData) {
            datasets.push({
                data: prevCloseData,
                borderColor: 'rgba(255,255,255,0.25)',
                borderDash: [4, 3],
                borderWidth: 1,
                pointRadius: 0,
                fill: false,
            });
        }

        // Reduce label density
        var step = Math.max(1, Math.floor(labels.length / 8));
        var tickLabels = labels.map(function(l, i) { return i % step === 0 ? l : ''; });

        var chart = new Chart(ctx, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(c) {
                                if (c.datasetIndex === 0) {
                                    var s = sessions[c.dataIndex] || '';
                                    var label = s === 'pre' ? 'Pre' : s === 'post' ? 'After' : 'Regular';
                                    return label + ': $' + c.raw.toFixed(2);
                                }
                                return 'Prev Close: $' + c.raw.toFixed(2);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            callback: function(val, idx) { return tickLabels[idx] || ''; },
                            font: { size: 9 },
                            color: 'rgba(255,255,255,0.4)',
                            maxRotation: 0,
                        },
                        grid: { display: false },
                    },
                    y: {
                        position: 'right',
                        ticks: {
                            font: { size: 9 },
                            color: 'rgba(255,255,255,0.5)',
                            callback: function(v) { return '$' + v.toFixed(1); },
                        },
                        grid: { color: 'rgba(255,255,255,0.06)' },
                    }
                }
            }
        });
        this._instances[canvasId] = chart;
    },

    /** Simple period chart — single color line, no legend, compact axes */
    createPeriodChart: function(canvasId, labels, prices, prevClose) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx || !prices || prices.length < 2) return;

        var first = prevClose || prices[0];
        var last = prices[prices.length - 1];
        var lineColor = last >= first ? 'rgba(34,197,94,0.8)' : 'rgba(239,68,68,0.8)';
        var fillColor = last >= first ? 'rgba(34,197,94,0.06)' : 'rgba(239,68,68,0.06)';

        var datasets = [{
            data: prices,
            borderColor: lineColor,
            backgroundColor: fillColor,
            fill: true,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1
        }];

        // Prev close dashed line
        if (prevClose) {
            datasets.push({
                data: prices.map(function() { return prevClose; }),
                borderColor: 'rgba(255,255,255,0.25)',
                borderDash: [4, 3],
                borderWidth: 1,
                pointRadius: 0,
                fill: false,
            });
        }

        var step = Math.max(1, Math.floor(labels.length / 8));
        var chart = new Chart(ctx, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: function(c) {
                                if (c.datasetIndex === 0) return '$' + c.raw.toFixed(2);
                                return 'Prev: $' + c.raw.toFixed(2);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            callback: function(val, idx) { return idx % step === 0 ? labels[idx] : ''; },
                            font: { size: 9 }, color: 'rgba(255,255,255,0.4)', maxRotation: 0,
                        },
                        grid: { display: false },
                    },
                    y: {
                        position: 'right',
                        ticks: { font: { size: 9 }, color: 'rgba(255,255,255,0.5)',
                                 callback: function(v) { return '$' + v.toFixed(1); } },
                        grid: { color: 'rgba(255,255,255,0.06)' },
                    }
                }
            }
        });
        this._instances[canvasId] = chart;
    },

    /** Mini sparkline — no axes, no legend, just a colored line */
    createSparkline: function(canvasId, prices) {
        this.destroy(canvasId);
        var ctx = document.getElementById(canvasId);
        if (!ctx || !prices || prices.length < 2) return;

        var first = prices[0];
        var last = prices[prices.length - 1];
        var color = last >= first ? 'rgba(34,197,94,0.9)' : 'rgba(239,68,68,0.9)';
        var fill = last >= first ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)';

        var chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: prices.map(function(_, i) { return i; }),
                datasets: [{
                    data: prices,
                    borderColor: color,
                    backgroundColor: fill,
                    fill: true,
                    borderWidth: 1.2,
                    pointRadius: 0,
                    tension: 0.3
                }]
            },
            options: {
                responsive: false,
                maintainAspectRatio: false,
                animation: false,
                plugins: { legend: { display: false }, tooltip: { enabled: false } },
                scales: {
                    x: { display: false },
                    y: { display: false }
                }
            }
        });
        this._instances[canvasId] = chart;
    },

    destroy: function (canvasId) {
        if (this._instances[canvasId]) {
            this._instances[canvasId].destroy();
            delete this._instances[canvasId];
        }
    }
};
