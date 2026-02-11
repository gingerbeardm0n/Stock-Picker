import sys
import os
# Add parent directory to path so we can import config
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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
scan_progress = {'stage': 0, 'message': 'Idle', 'percent': 0}

def background_scanner():
    """Background thread to run full-universe scans periodically"""
    global scan_results, last_scan_time, scanning_in_progress, scan_progress

    while True:
        try:
            now = datetime.now()
            hour = now.hour

            # Run between 4 AM and 4 PM ET (adjust for your timezone)
            if 4 <= hour <= 16:
                if not scanning_in_progress:
                    logger.info("Running scheduled full-universe scan...")
                    scanning_in_progress = True
                    scan_progress = {'stage': 0, 'message': 'Starting scan...', 'percent': 0}

                    def progress_cb(stage, message, pct):
                        global scan_progress
                        scan_progress = {'stage': stage, 'message': message, 'percent': pct}

                    results = scanner.run_full_scan(progress_callback=progress_cb)
                    scan_results = results
                    last_scan_time = datetime.now()
                    scanning_in_progress = False
                    scan_progress = {'stage': 0, 'message': 'Idle', 'percent': 100}

                    logger.info(f"Scan complete: {len(results)} stocks found")

            time.sleep(60)

        except Exception as e:
            logger.error(f"Error in background scanner: {e}")
            scanning_in_progress = False
            scan_progress = {'stage': 0, 'message': f'Error: {str(e)}', 'percent': 0}
            time.sleep(60)

@app.route('/')
def index():
    """Serve the main dashboard"""
    return render_template('index.html')

@app.route('/style.css')
def serve_css():
    """Serve CSS file"""
    from flask import send_from_directory
    return send_from_directory('../frontend', 'style.css')

@app.route('/app.js')
def serve_js():
    """Serve JavaScript file"""
    from flask import send_from_directory
    return send_from_directory('../frontend', 'app.js')

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
    """Manually trigger a full-universe scan"""
    global scan_results, last_scan_time, scanning_in_progress, scan_progress

    if scanning_in_progress:
        return jsonify({'error': 'Scan already in progress'}), 429

    try:
        scanning_in_progress = True
        scan_progress = {'stage': 0, 'message': 'Starting scan...', 'percent': 0}

        def progress_cb(stage, message, pct):
            global scan_progress
            scan_progress = {'stage': stage, 'message': message, 'percent': pct}

        # Check if specific symbols were requested (for individual lookups)
        data = request.get_json(silent=True) or {}
        symbols = data.get('symbols', None)

        if symbols:
            results = scanner.run_scan(symbols)
        else:
            results = scanner.run_full_scan(progress_callback=progress_cb)

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
        scan_progress = {'stage': 0, 'message': f'Error: {str(e)}', 'percent': 0}
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

@app.route('/api/scan/progress', methods=['GET'])
def get_scan_progress():
    """Get current scan progress"""
    return jsonify({
        'scanning': scanning_in_progress,
        'progress': scan_progress
    })

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

        valid_keys = {'min_price', 'max_price', 'min_premarket_volume',
                      'min_premarket_gain_pct', 'min_relative_volume',
                      'min_avg_volume', 'max_avg_volume', 'max_float'}
        filtered = {k: float(v) for k, v in data.items() if k in valid_keys}

        Config.SCANNER_CRITERIA.update(filtered)
        scanner.update_criteria(filtered)

        return jsonify({'success': True, 'criteria': Config.SCANNER_CRITERIA})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan/debug', methods=['POST'])
def debug_scan():
    """Debug scan on 100 hardcoded stocks showing raw calculated values"""
    try:
        from config import Config
        data = request.get_json(silent=True) or {}
        sim_datetime_str = data.get('datetime', None)

        sim_datetime_et = None
        if sim_datetime_str:
            from datetime import datetime
            import pytz
            sim_datetime = datetime.strptime(sim_datetime_str, '%Y-%m-%d %H:%M')
            et = pytz.timezone('US/Eastern')
            sim_datetime_et = et.localize(sim_datetime)

        logger.info("Running debug scan on hardcoded test stocks...")
        results = scanner.run_debug_scan(Config.DEBUG_STOCKS, simulation_time=sim_datetime_et)

        return jsonify({
            'success': True,
            'results': results,
            'count': len(results),
            'passed': sum(1 for r in results if r['passes']),
            'criteria': Config.SCANNER_CRITERIA
        })

    except Exception as e:
        logger.error(f"Error in debug scan: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan/test', methods=['POST'])
def test_scan_historical():
    """Test scan with historical data from a specific date/time"""
    global scan_results, last_scan_time, scanning_in_progress, scan_progress

    if scanning_in_progress:
        return jsonify({'error': 'Scan already in progress'}), 429

    try:
        data = request.get_json()
        sim_datetime_str = data.get('datetime')  # Format: "YYYY-MM-DD HH:MM"

        if not sim_datetime_str:
            return jsonify({'error': 'datetime parameter required (format: YYYY-MM-DD HH:MM)'}), 400

        from datetime import datetime
        import pytz
        sim_datetime = datetime.strptime(sim_datetime_str, '%Y-%m-%d %H:%M')
        et = pytz.timezone('US/Eastern')
        sim_datetime_et = et.localize(sim_datetime)

        scanning_in_progress = True
        scan_progress = {'stage': 0, 'message': f'Starting test scan at {sim_datetime_str}...', 'percent': 0}

        def progress_cb(stage, message, pct):
            global scan_progress
            scan_progress = {'stage': stage, 'message': message, 'percent': pct}

        results = scanner.run_full_scan(progress_callback=progress_cb, simulation_time=sim_datetime_et)
        scan_results = results
        last_scan_time = datetime.now()
        scanning_in_progress = False

        return jsonify({
            'success': True,
            'results': scan_results,
            'count': len(scan_results),
            'simulated_time': sim_datetime_str
        })

    except ValueError as e:
        scanning_in_progress = False
        logger.error(f"ValueError in test scan: {e}", exc_info=True)
        return jsonify({'error': f'Invalid datetime format: {str(e)}'}), 400
    except Exception as e:
        scanning_in_progress = False
        scan_progress = {'stage': 0, 'message': f'Error: {str(e)}', 'percent': 0}
        logger.error(f"Error in test scan: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Start background scanner thread (DISABLED during development)
    # scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    # scanner_thread.start()

    logger.info("Starting Flask server...")
    logger.info("Dashboard will be available at http://localhost:5000")
    logger.info("NOTE: Auto-scan disabled - use Debug/Test buttons manually")
    logger.info("🔥 Hot reload ENABLED - code changes will auto-restart server")

    # Run Flask app with hot reload enabled
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=True)
