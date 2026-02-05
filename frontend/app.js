const API_BASE = 'http://localhost:5000/api';

let scanning = false;

// DOM elements
const scanBtn = document.getElementById('scanBtn');
const refreshBtn = document.getElementById('refreshBtn');
const statusText = document.getElementById('statusText');
const lastScan = document.getElementById('lastScan');
const resultCount = document.getElementById('resultCount');
const resultsContainer = document.getElementById('resultsContainer');

// Event listeners
scanBtn.addEventListener('click', triggerScan);
refreshBtn.addEventListener('click', fetchResults);

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    fetchCriteria();
    fetchResults();

    // Auto-refresh every 60 seconds
    setInterval(fetchResults, 60000);
});

async function fetchCriteria() {
    try {
        const response = await fetch(`${API_BASE}/criteria`);
        const criteria = await response.json();

        document.getElementById('priceRange').textContent =
            `$${criteria.min_price} - $${criteria.max_price}`;
        document.getElementById('minVolume').textContent =
            criteria.min_premarket_volume.toLocaleString();
        document.getElementById('minGain').textContent =
            `${criteria.min_premarket_gain_pct}%`;
        document.getElementById('minRelVol').textContent =
            `${criteria.min_relative_volume}x`;
    } catch (error) {
        console.error('Error fetching criteria:', error);
    }
}

async function triggerScan() {
    if (scanning) return;

    scanning = true;
    scanBtn.disabled = true;
    statusText.textContent = 'Scanning...';
    statusText.classList.add('scanning');

    resultsContainer.innerHTML = '<div class="loading"><span class="spinner"></span>Scanning stocks...</div>';

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
        resultsContainer.innerHTML = `<div class="no-results"><p>Error: ${error.message}</p></div>`;
    } finally {
        scanning = false;
        scanBtn.disabled = false;
        statusText.classList.remove('scanning');
    }
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
        resultsContainer.innerHTML = '<div class="no-results"><p>No stocks found matching criteria</p></div>';
        return;
    }

    resultsContainer.innerHTML = results.map(stock => createStockCard(stock)).join('');
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
