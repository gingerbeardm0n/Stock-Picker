const API_BASE = 'http://localhost:5000/api';

let scanning = false;
let progressInterval = null;
let gridApi = null;
let scanStartTime = null;

// DOM elements
const scanBtn = document.getElementById('scanBtn');
const refreshBtn = document.getElementById('refreshBtn');
const testScanBtn = document.getElementById('testScanBtn');
const debugScanBtn = document.getElementById('debugScanBtn');
const set925Btn = document.getElementById('set925Btn');
const testDateTime = document.getElementById('testDateTime');
const statusText = document.getElementById('statusText');
const lastScan = document.getElementById('lastScan');
const resultCount = document.getElementById('resultCount');

// Event listeners
scanBtn.addEventListener('click', triggerScan);
refreshBtn.addEventListener('click', fetchResults);
testScanBtn.addEventListener('click', triggerTestScan);
debugScanBtn.addEventListener('click', triggerDebugScan);
set925Btn.addEventListener('click', setTime925);

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initializeGrid();
    fetchCriteria();
    fetchResults();

    document.getElementById('criteriaForm').addEventListener('submit', saveCriteria);

    // Set default test time to 9:25am today (local time)
    const defaultTime = new Date();
    defaultTime.setHours(9, 25, 0, 0);

    // Format as YYYY-MM-DDTHH:MM for datetime-local input (LOCAL time, not UTC)
    const year = defaultTime.getFullYear();
    const month = String(defaultTime.getMonth() + 1).padStart(2, '0');
    const day = String(defaultTime.getDate()).padStart(2, '0');
    const hours = String(defaultTime.getHours()).padStart(2, '0');
    const minutes = String(defaultTime.getMinutes()).padStart(2, '0');

    const formatted = `${year}-${month}-${day}T${hours}:${minutes}`;
    testDateTime.value = formatted;

    // Auto-refresh every 60 seconds
    setInterval(fetchResults, 60000);
});

function initializeGrid() {
    const columnDefs = [
        { field: 'symbol', headerName: 'Symbol', filter: 'agTextColumnFilter', pinned: 'left', width: 100, cellStyle: { fontWeight: 'bold' } },
        { field: 'price', headerName: 'Price', filter: 'agNumberColumnFilter', width: 90, valueFormatter: p => p.value ? '$' + p.value.toFixed(2) : '' },
        {
            field: 'premarket_gain_pct',
            headerName: 'PM Gain %',
            filter: 'agNumberColumnFilter',
            width: 120,
            valueFormatter: p => p.value ? p.value.toFixed(2) + '%' : '0%',
            cellStyle: params => ({
                color: params.value >= 0 ? '#22c55e' : '#ef4444',
                fontWeight: 'bold'
            })
        },
        {
            field: 'premarket_volume',
            headerName: 'PM Volume',
            filter: 'agNumberColumnFilter',
            width: 130,
            valueFormatter: p => formatNumber(p.value)
        },
        {
            field: 'avg_pm_volume',
            headerName: 'Avg PM Vol',
            filter: 'agNumberColumnFilter',
            width: 130,
            valueFormatter: p => formatNumber(p.value)
        },
        {
            field: 'relative_volume',
            headerName: 'Rel Volume',
            filter: 'agNumberColumnFilter',
            width: 120,
            valueFormatter: p => p.value ? p.value.toFixed(2) + 'x' : '0x',
            cellStyle: params => {
                if (params.value >= 5) return { backgroundColor: '#dcfce7', color: '#166534', fontWeight: 'bold' };
                if (params.value >= 2) return { backgroundColor: '#fef9c3', color: '#854d0e' };
                return { color: '#9ca3af' };
            }
        },
        {
            field: 'avg_volume',
            headerName: 'Avg Daily Vol',
            filter: 'agNumberColumnFilter',
            width: 140,
            valueFormatter: p => formatNumber(p.value)
        },
        { field: 'bid', headerName: 'Bid', filter: 'agNumberColumnFilter', width: 90, valueFormatter: p => p.value ? '$' + p.value.toFixed(2) : '' },
        { field: 'ask', headerName: 'Ask', filter: 'agNumberColumnFilter', width: 90, valueFormatter: p => p.value ? '$' + p.value.toFixed(2) : '' },
        { field: 'spread', headerName: 'Spread', filter: 'agNumberColumnFilter', width: 100, valueFormatter: p => p.value ? '$' + p.value.toFixed(4) : '' }
    ];

    const gridOptions = {
        columnDefs: columnDefs,
        rowData: [],
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true,
            floatingFilter: true
        },
        pagination: true,
        paginationPageSize: 50,
        paginationPageSizeSelector: [25, 50, 100, 200],
        domLayout: 'normal'
    };

    const gridDiv = document.getElementById('stockGrid');
    gridApi = agGrid.createGrid(gridDiv, gridOptions);
}

async function fetchCriteria() {
    try {
        const response = await fetch(`${API_BASE}/criteria`);
        const criteria = await response.json();

        document.getElementById('minPrice').value = criteria.min_price;
        document.getElementById('maxPrice').value = criteria.max_price;
        document.getElementById('minPremarketVolume').value = criteria.min_premarket_volume;
        document.getElementById('minPremarketGain').value = criteria.min_premarket_gain_pct;
        document.getElementById('minRelativeVolume').value = criteria.min_relative_volume || 2.0;
    } catch (error) {
        console.error('Error fetching criteria:', error);
    }
}

async function saveCriteria(event) {
    event.preventDefault();

    const criteria = {
        min_price: parseFloat(document.getElementById('minPrice').value),
        max_price: parseFloat(document.getElementById('maxPrice').value),
        min_premarket_volume: parseInt(document.getElementById('minPremarketVolume').value),
        min_premarket_gain_pct: parseFloat(document.getElementById('minPremarketGain').value),
        min_relative_volume: parseFloat(document.getElementById('minRelativeVolume').value)
    };

    try {
        const response = await fetch(`${API_BASE}/criteria`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(criteria)
        });

        const result = await response.json();
        if (result.success) {
            triggerScan();
        }
    } catch (error) {
        console.error('Error saving criteria:', error);
    }
}

function startProgressPolling() {
    const container = document.getElementById('progressContainer');
    container.style.display = 'block';
    scanStartTime = Date.now();

    progressInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/scan/progress`);
            const data = await response.json();

            const elapsed = Math.floor((Date.now() - scanStartTime) / 1000);
            const elapsedText = `${elapsed}s`;

            document.getElementById('progressFill').style.width = data.progress.percent + '%';
            document.getElementById('progressText').textContent = `${data.progress.message} (${elapsedText})`;

            // Warn if taking too long
            if (elapsed > 120 && data.scanning) {
                document.getElementById('progressText').textContent += ' ⚠️ Taking longer than expected...';
            }

            if (!data.scanning) {
                stopProgressPolling();
            }
        } catch (e) {
            console.error('Progress poll error:', e);
        }
    }, 1000);
}

function stopProgressPolling() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    document.getElementById('progressContainer').style.display = 'none';
}

async function triggerScan() {
    if (scanning) return;

    scanning = true;
    scanBtn.disabled = true;
    statusText.textContent = 'Scanning full universe...';
    statusText.classList.add('scanning');

    startProgressPolling();

    try {
        const response = await fetch(`${API_BASE}/scan/now`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        const data = await response.json();

        if (data.success) {
            displayResults(data.results);
            resultCount.textContent = data.count;
            lastScan.textContent = `Last scan: ${new Date().toLocaleTimeString()}`;
            statusText.textContent = 'Ready';
        } else {
            throw new Error(data.error || 'Scan failed');
        }
    } catch (error) {
        console.error('Error triggering scan:', error);
        statusText.textContent = 'Error';
        alert(`Scan error: ${error.message}`);
    } finally {
        scanning = false;
        scanBtn.disabled = false;
        statusText.classList.remove('scanning');
        stopProgressPolling();
    }
}

async function triggerTestScan() {
    if (scanning) return;

    const dateTimeValue = testDateTime.value.trim();
    if (!dateTimeValue) {
        alert('Please select a date and time');
        return;
    }

    // Convert from datetime-local format (YYYY-MM-DDTHH:MM) to API format (YYYY-MM-DD HH:MM)
    const dateTimeStr = dateTimeValue.replace('T', ' ');

    scanning = true;
    testScanBtn.disabled = true;
    scanBtn.disabled = true;
    statusText.textContent = `Testing scan at ${dateTimeStr}...`;
    statusText.classList.add('scanning');

    startProgressPolling();

    try {
        const response = await fetch(`${API_BASE}/scan/test`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ datetime: dateTimeStr })
        });

        // Log raw response for debugging
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            const text = await response.text();
            console.error('Non-JSON response:', text);
            throw new Error(`Server returned ${response.status}: ${text.substring(0, 200)}`);
        }

        const data = await response.json();

        if (data.success) {
            displayResults(data.results);
            resultCount.textContent = data.count;
            lastScan.textContent = `Test scan: ${data.simulated_time}`;
            statusText.textContent = 'Ready';
        } else {
            throw new Error(data.error || 'Test scan failed');
        }
    } catch (error) {
        console.error('Error triggering test scan:', error);
        statusText.textContent = 'Error';
        alert(`Test scan error: ${error.message}`);
    } finally {
        scanning = false;
        testScanBtn.disabled = false;
        scanBtn.disabled = false;
        statusText.classList.remove('scanning');
        stopProgressPolling();
    }
}

function setTime925() {
    // Set time to 9:25 AM today (local timezone)
    const today = new Date();
    today.setHours(9, 25, 0, 0);

    // Format for datetime-local input (YYYY-MM-DDTHH:MM) in LOCAL time
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    const hours = String(today.getHours()).padStart(2, '0');
    const minutes = String(today.getMinutes()).padStart(2, '0');

    const formatted = `${year}-${month}-${day}T${hours}:${minutes}`;
    testDateTime.value = formatted;
}

async function triggerDebugScan() {
    if (scanning) return;

    // Get datetime from the test input if user wants historical debug
    const dateTimeValue = testDateTime.value.trim();
    const dateTimeStr = dateTimeValue ? dateTimeValue.replace('T', ' ') : null;

    scanning = true;
    debugScanBtn.disabled = true;
    scanBtn.disabled = true;
    statusText.textContent = 'Running debug scan...';
    statusText.classList.add('scanning');

    try {
        const body = dateTimeStr ? JSON.stringify({ datetime: dateTimeStr }) : '{}';
        const response = await fetch(`${API_BASE}/scan/debug`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: body
        });

        const data = await response.json();

        if (data.success) {
            displayDebugResults(data.results, data.criteria);
            document.getElementById('debugPassed').textContent = data.passed;
            document.getElementById('debugFailed').textContent = data.count - data.passed;
            document.getElementById('debugSection').style.display = 'block';

            // Scroll to debug section
            document.getElementById('debugSection').scrollIntoView({ behavior: 'smooth', block: 'start' });

            statusText.textContent = 'Debug scan complete';
        } else {
            throw new Error(data.error || 'Debug scan failed');
        }
    } catch (error) {
        console.error('Error triggering debug scan:', error);
        statusText.textContent = 'Error';
        alert(`Debug scan error: ${error.message}`);
    } finally {
        scanning = false;
        debugScanBtn.disabled = false;
        scanBtn.disabled = false;
        statusText.classList.remove('scanning');
    }
}

function displayDebugResults(results, criteria) {
    const tbody = document.getElementById('debugTableBody');

    if (!results || results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="no-results">No debug data available</td></tr>';
        return;
    }

    tbody.innerHTML = results.map(stock => {
        const rowClass = stock.passes ? 'passed' : 'failed';

        // Format values with null handling
        const price = stock.price !== null ? `$${stock.price.toFixed(3)}` : '<span class="value-null">N/A</span>';
        const pmVolume = stock.pm_volume !== null ? formatNumber(stock.pm_volume) : '<span class="value-null">N/A</span>';
        const pmGain = stock.pm_gain_pct !== null ? stock.pm_gain_pct.toFixed(2) + '%' : '<span class="value-null">N/A</span>';
        const relVolume = stock.relative_volume !== null ? stock.relative_volume.toFixed(2) + 'x' : '<span class="value-null">N/A</span>';
        const avgVolume = stock.avg_volume !== null ? formatNumber(stock.avg_volume) : '<span class="value-null">N/A</span>';

        // Color coding for PM gain
        let pmGainClass = '';
        if (stock.pm_gain_pct !== null) {
            pmGainClass = stock.pm_gain_pct >= 0 ? 'positive' : 'negative';
        }

        // Color coding for relative volume
        let relVolumeClass = 'low';
        if (stock.relative_volume !== null) {
            if (stock.relative_volume >= 5) relVolumeClass = 'high';
            else if (stock.relative_volume >= 2) relVolumeClass = 'medium';
        }

        const statusText = stock.passes ? 'PASSED ✓' : stock.failed_at;
        const statusClass = stock.passes ? 'passed' : 'failed';

        return `
            <tr class="${rowClass}">
                <td class="symbol">${stock.symbol}</td>
                <td class="price">${price}</td>
                <td class="pm-gain ${pmGainClass}">${pmGain}</td>
                <td class="pm-volume">${pmVolume}</td>
                <td class="avg-volume">${avgVolume}</td>
                <td class="rel-volume ${relVolumeClass}">${relVolume}</td>
                <td class="status ${statusClass}">${statusText}</td>
            </tr>
        `;
    }).join('');
}

async function fetchResults() {
    try {
        const response = await fetch(`${API_BASE}/scan`);
        const data = await response.json();

        displayResults(data.results);
        resultCount.textContent = data.count;

        if (data.last_scan) {
            const scanTime = new Date(data.last_scan);
            lastScan.textContent = `Last scan: ${scanTime.toLocaleTimeString()}`;
        }

        if (data.scanning) {
            statusText.textContent = 'Scanning...';
            statusText.classList.add('scanning');
        } else {
            statusText.textContent = 'Ready';
            statusText.classList.remove('scanning');
        }
    } catch (error) {
        console.error('Error fetching results:', error);
    }
}

function displayResults(results) {
    if (!results || results.length === 0) {
        if (gridApi) {
            gridApi.setGridOption('rowData', []);
        }
        return;
    }

    if (gridApi) {
        gridApi.setGridOption('rowData', results);
    }
}

function createStockCard(stock) {
    const gainClass = stock.premarket_gain_pct >= 0 ? '' : 'negative';
    const gainSign = stock.premarket_gain_pct >= 0 ? '+' : '';

    return `
        <div class="stock-card">
            <div class="stock-header">
                <div class="stock-symbol">${stock.symbol}</div>
                <div class="stock-gain ${gainClass}">
                    ${gainSign}${stock.premarket_gain_pct}%
                </div>
            </div>

            <div class="stock-price">$${stock.price.toFixed(2)}</div>

            <div class="stock-metrics">
                <div class="metric">
                    <div class="metric-label">PM Volume</div>
                    <div class="metric-value">${formatNumber(stock.premarket_volume)}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Rel. Volume</div>
                    <div class="metric-value">${stock.relative_volume}x</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Avg Volume</div>
                    <div class="metric-value">${formatNumber(stock.avg_volume)}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">News</div>
                    <div class="metric-value">${stock.news_count} items</div>
                </div>
            </div>

            ${stock.has_news ?
                `<div class="news-badge has-news">📰 Catalyst Detected</div>` :
                `<div class="news-badge">No Recent News</div>`
            }

            ${stock.bid && stock.ask ? `
                <div class="spread-info">
                    <span>Bid: $${stock.bid.toFixed(2)}</span>
                    <span>Ask: $${stock.ask.toFixed(2)}</span>
                    <span>Spread: $${stock.spread.toFixed(4)}</span>
                </div>
            ` : ''}
        </div>
    `;
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}
