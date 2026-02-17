// Stock Scanner Frontend - Database-First Architecture
// Supports Live Mode (latest DB data) and Backtest Mode (historical dates)

let gridApi = null;
let currentMode = 'live'; // 'live' or 'backtest'

// AG Grid column definitions
const columnDefs = [
    {
        headerName: 'Symbol',
        field: 'symbol',
        sortable: true,
        filter: true,
        cellStyle: { fontWeight: 'bold', fontSize: '16px' },
        width: 120
    },
    {
        headerName: 'Price',
        field: 'price',
        sortable: true,
        valueFormatter: params => `$${params.value?.toFixed(2) || '0.00'}`,
        width: 100
    },
    {
        headerName: 'Rel Vol',
        field: 'relative_volume',
        sortable: true,
        valueFormatter: params => `${params.value?.toFixed(1) || '0.0'}x`,
        cellStyle: params => {
            if (params.value >= 5) return { backgroundColor: '#c6f6d5', color: '#22543d' };
            if (params.value >= 3) return { backgroundColor: '#fef3c7', color: '#78350f' };
            return {};
        },
        width: 110
    },
    {
        headerName: 'Morning Vol',
        field: 'morning_volume',
        sortable: true,
        valueFormatter: params => params.value?.toLocaleString() || '0',
        width: 140
    },
    {
        headerName: 'Avg Vol (20d)',
        field: 'avg_volume',
        sortable: true,
        valueFormatter: params => params.value?.toLocaleString() || '0',
        width: 150
    },
    {
        headerName: 'Catalyst',
        field: 'has_catalyst',
        sortable: true,
        width: 100,
        valueFormatter: params => {
            if (params.value === null || params.value === undefined) return '—';
            return params.value ? `✅ ${params.data.news_count}` : '❌';
        },
        cellStyle: params => {
            if (params.value === true) return { color: '#22543d', fontWeight: 'bold' };
            if (params.value === false) return { color: '#999' };
            return {};
        }
    },
    {
        headerName: 'Top Headline',
        field: 'news',
        flex: 1,
        minWidth: 300,
        valueFormatter: params => {
            if (!params.value || params.value.length === 0) return '—';
            return params.value[0].headline;
        },
        cellStyle: { fontSize: '12px', color: '#444' },
        tooltipValueGetter: params => {
            if (!params.value || params.value.length === 0) return '';
            return params.value.map((a, i) => `${i+1}. ${a.headline}`).join('\n');
        }
    }
];

// Grid options
const gridOptions = {
    columnDefs: columnDefs,
    defaultColDef: {
        resizable: true,
        sortable: true
    },
    rowData: [],
    animateRows: true,
    pagination: true,
    paginationPageSize: 50,
    domLayout: 'normal',
    onRowClicked: params => openNewsModal(params.data)
};

function openNewsModal(stock) {
    document.getElementById('modalSymbol').textContent =
        `${stock.symbol}  —  $${stock.price?.toFixed(2)}`;

    const articles = stock.news || [];
    const container = document.getElementById('modalArticles');

    if (articles.length === 0) {
        container.innerHTML = '<p class="no-news">No news found for this stock in the past 48 hours.</p>';
    } else {
        container.innerHTML = articles.map(a => {
            const date = a.created_at ? new Date(a.created_at).toLocaleString() : '';
            const summary = a.summary?.trim() || '';
            const tag = a.is_specific
                ? `<span class="article-tag specific">Direct</span>`
                : `<span class="article-tag roundup">Roundup (${a.symbol_count} stocks)</span>`;
            return `
                <div class="article ${a.is_specific ? '' : 'article-roundup'}">
                    <div class="article-meta">${tag} &nbsp;${a.source?.toUpperCase() || 'NEWS'} &nbsp;·&nbsp; ${date}</div>
                    <div class="article-headline">${a.headline}</div>
                    ${summary ? `<div class="article-summary">${summary}</div>` : ''}
                    ${a.url ? `<a class="article-link" href="${a.url}" target="_blank">Read full article →</a>` : ''}
                </div>`;
        }).join('');
    }

    document.getElementById('newsModal').style.display = 'flex';
}

function closeNewsModal() {
    document.getElementById('newsModal').style.display = 'none';
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Initialize AG Grid
    const gridDiv = document.getElementById('stockGrid');
    gridApi = agGrid.createGrid(gridDiv, gridOptions);

    // Close modal when clicking overlay background
    document.getElementById('newsModal').addEventListener('click', e => {
        if (e.target.id === 'newsModal') closeNewsModal();
    });

    // Set up event listeners
    setupEventListeners();

    // Load criteria
    loadCriteria();

    // Set default backtest date to latest trading day
    setDefaultBacktestDate();
});

function setupEventListeners() {
    // Mode toggle buttons
    document.getElementById('liveMode').addEventListener('click', () => {
        switchMode('live');
    });

    document.getElementById('backtestMode').addEventListener('click', () => {
        switchMode('backtest');
    });

    // Main scan button
    document.getElementById('scanBtn').addEventListener('click', () => {
        runScan();
    });

    // Criteria form
    document.getElementById('criteriaForm').addEventListener('submit', (e) => {
        e.preventDefault();
        saveCriteria();
    });
}

function switchMode(mode) {
    currentMode = mode;

    // Update UI
    const liveBtn = document.getElementById('liveMode');
    const backtestBtn = document.getElementById('backtestMode');
    const datePicker = document.getElementById('backtestDatePicker');
    const scanBtn = document.getElementById('scanBtn');

    if (mode === 'live') {
        liveBtn.classList.add('active');
        backtestBtn.classList.remove('active');
        datePicker.style.display = 'none';
        scanBtn.textContent = 'Scan Now';
        updateStatus('Live mode - scanning latest database data');
    } else {
        liveBtn.classList.remove('active');
        backtestBtn.classList.add('active');
        datePicker.style.display = 'flex';
        scanBtn.textContent = 'Backtest Date';
        updateStatus('Backtest mode - select a date to scan');
    }
}

function setDefaultBacktestDate() {
    // Set to 3 days ago (likely to have data)
    const date = new Date();
    date.setDate(date.getDate() - 3);
    const dateStr = date.toISOString().split('T')[0];
    document.getElementById('backtestDate').value = dateStr;
}

async function runScan() {
    const scanBtn = document.getElementById('scanBtn');
    const originalText = scanBtn.textContent;

    try {
        scanBtn.disabled = true;
        scanBtn.textContent = 'Scanning...';
        updateStatus('Scanning database...', 'loading');

        // Prepare request body
        const requestBody = {};

        if (currentMode === 'backtest') {
            const dateInput = document.getElementById('backtestDate');
            if (!dateInput.value) {
                alert('Please select a date for backtesting');
                return;
            }
            requestBody.date = dateInput.value;
        }

        // Call database scan endpoint
        const response = await fetch('/api/scan/database', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        const data = await response.json();

        if (data.success) {
            // Update grid with results
            gridApi.setGridOption('rowData', data.results);

            // Update UI
            document.getElementById('resultCount').textContent = data.count;

            const modeStr = data.mode === 'Live' ? 'Latest data' : `Historical: ${data.scan_date}`;
            updateStatus(`✅ Found ${data.count} stocks (${modeStr})`, 'success');

            // Update last scan time
            const now = new Date().toLocaleTimeString();
            document.getElementById('lastScan').textContent = `Last scan: ${now}`;
        } else {
            throw new Error(data.error || 'Scan failed');
        }

    } catch (error) {
        console.error('Scan error:', error);
        updateStatus(`❌ Error: ${error.message}`, 'error');
        alert(`Scan failed: ${error.message}`);
    } finally {
        scanBtn.disabled = false;
        scanBtn.textContent = originalText;
    }
}

async function loadCriteria() {
    try {
        const response = await fetch('/api/criteria');
        const criteria = await response.json();

        // Populate form fields
        document.getElementById('minPrice').value = criteria.min_price || 1;
        document.getElementById('maxPrice').value = criteria.max_price || 10;
        document.getElementById('minPremarketVolume').value = criteria.min_premarket_volume || 100000;
        document.getElementById('minPremarketGain').value = criteria.min_premarket_gain_pct || 10;
        document.getElementById('minRelativeVolume').value = criteria.min_relative_volume || 2;

    } catch (error) {
        console.error('Error loading criteria:', error);
    }
}

async function saveCriteria() {
    try {
        const criteria = {
            min_price: parseFloat(document.getElementById('minPrice').value),
            max_price: parseFloat(document.getElementById('maxPrice').value),
            min_premarket_volume: parseInt(document.getElementById('minPremarketVolume').value),
            min_premarket_gain_pct: parseFloat(document.getElementById('minPremarketGain').value),
            min_relative_volume: parseFloat(document.getElementById('minRelativeVolume').value)
        };

        const response = await fetch('/api/criteria', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(criteria)
        });

        const data = await response.json();

        if (data.success) {
            updateStatus('✅ Criteria updated', 'success');
            // Auto-run scan after updating criteria
            setTimeout(() => runScan(), 500);
        } else {
            throw new Error(data.error || 'Failed to update criteria');
        }

    } catch (error) {
        console.error('Error saving criteria:', error);
        alert(`Failed to update criteria: ${error.message}`);
    }
}

function updateStatus(message, type = '') {
    const statusEl = document.getElementById('statusText');
    statusEl.textContent = message;

    // Remove old classes
    statusEl.className = '';

    // Add type-specific class
    if (type) {
        statusEl.classList.add(`status-${type}`);
    }
}
