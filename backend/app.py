from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from scanner import MomentumScanner
import logging
import threading
import time
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__,
            static_folder='../frontend',
            template_folder='../frontend')
CORS(app)

# Global scanner instance
scanner = MomentumScanner()
scan_results = []
last_scan_time = None
scanning_in_progress = False

def background_scanner():
    """Background thread to run scans periodically"""
    global scan_results, last_scan_time, scanning_in_progress

    while True:
        try:
            # Check if market hours (or pre-market)
            now = datetime.now()
            hour = now.hour

            # Run between 4 AM and 4 PM ET (adjust for your timezone)
            if 4 <= hour <= 16:
                if not scanning_in_progress:
                    logger.info("Running scheduled scan...")
                    scanning_in_progress = True

                    # For testing, scan a subset of symbols
                    # In production, you'd scan all active stocks
                    test_symbols = ['AAPL', 'TSLA', 'AMD', 'NVDA', 'PLTR', 'SOFI',
                                   'NIO', 'LCID', 'RIVN', 'F', 'GME', 'AMC']

                    results = scanner.run_scan(test_symbols)
                    scan_results = results
                    last_scan_time = datetime.now()
                    scanning_in_progress = False

                    logger.info(f"Scan complete: {len(results)} stocks found")

            # Wait before next scan (60 seconds)
            time.sleep(60)

        except Exception as e:
            logger.error(f"Error in background scanner: {e}")
            scanning_in_progress = False
            time.sleep(60)

@app.route('/')
def index():
    """Serve the main dashboard"""
    return render_template('index.html')

@app.route('/api/scan', methods=['GET'])
def get_scan_results():
    """Get current scan results"""
    return jsonify({
        'results': scan_results,
        'last_scan': last_scan_time.isoformat() if last_scan_time else None,
        'scanning': scanning_in_progress,
        'count': len(scan_results)
    })

@app.route('/api/scan/now', methods=['POST'])
def trigger_scan():
    """Manually trigger a scan"""
    global scan_results, last_scan_time, scanning_in_progress

    if scanning_in_progress:
        return jsonify({'error': 'Scan already in progress'}), 429

    try:
        # Get optional symbol list from request
        data = request.get_json() or {}
        symbols = data.get('symbols', None)

        scanning_in_progress = True

        if symbols:
            results = scanner.run_scan(symbols)
        else:
            # Default test symbols
            test_symbols = ['AAPL', 'TSLA', 'AMD', 'NVDA', 'PLTR', 'SOFI',
                           'NIO', 'LCID', 'RIVN', 'F', 'GME', 'AMC', 'SQQQ',
                           'TQQQ', 'SPY', 'QQQ']
            results = scanner.run_scan(test_symbols)

        scan_results = results
        last_scan_time = datetime.now()
        scanning_in_progress = False

        return jsonify({
            'success': True,
            'results': scan_results,
            'count': len(scan_results)
        })

    except Exception as e:
        scanning_in_progress = False
        logger.error(f"Error triggering scan: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/stock/<symbol>', methods=['GET'])
def get_stock_detail(symbol):
    """Get detailed info for a specific stock"""
    try:
        result = scanner.scan_stock(symbol.upper())
        if result:
            return jsonify(result)
        else:
            return jsonify({'error': 'Stock not found or does not meet criteria'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/criteria', methods=['GET'])
def get_criteria():
    """Get current scanner criteria"""
    from config import Config
    return jsonify(Config.SCANNER_CRITERIA)

@app.route('/api/criteria', methods=['POST'])
def update_criteria():
    """Update scanner criteria"""
    try:
        data = request.get_json()
        from config import Config
        Config.SCANNER_CRITERIA.update(data)
        return jsonify({'success': True, 'criteria': Config.SCANNER_CRITERIA})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Start background scanner thread
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()

    logger.info("Starting Flask server...")
    logger.info("Dashboard will be available at http://localhost:5000")

    # Run Flask app
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
