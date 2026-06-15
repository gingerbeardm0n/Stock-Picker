"""
Tradier Broker and Data Feed
============================
Concrete BrokerInterface + DataFeedInterface + TradierBarPoller using the
Tradier REST API. No WebSocket dependency — bars are polled once per minute.

Tradier accounts:
    Paper (sandbox): base_url = https://sandbox.tradier.com/v1
    Live:            base_url = https://api.tradier.com/v1

Credentials go in .env.paper / .env.live:
    TRADIER_TOKEN=<token>
    TRADIER_ACCOUNT_ID=<account_id>

Usage:
    from trading.broker.tradier import TradierBroker, TradierDataFeed, TradierBarPoller

    broker = TradierBroker(token, account_id, sandbox=True)
    data   = TradierDataFeed(token, sandbox=True)
    poller = TradierBarPoller(token, sandbox=True, bar_queue=q)

    poller.set_watchlist(symbols)
    thread = threading.Thread(target=poller.start, daemon=True)
    thread.start()
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytz
import requests

from trading.bar_capture import record_bar
from trading.broker.base import (
    BrokerInterface, DataFeedInterface,
    OrderResult, QuoteResult, PositionResult, BarResult,
)

logger = logging.getLogger(__name__)
ET = pytz.timezone('America/New_York')

_SANDBOX_BASE = 'https://sandbox.tradier.com/v1'
_PROD_BASE    = 'https://api.tradier.com/v1'

# Tradier → normalized status mapping
_STATUS_MAP = {
    'open':             'open',
    'partially_filled': 'partially_filled',
    'filled':           'filled',
    'expired':          'expired',
    'canceled':         'cancelled',   # Tradier uses American spelling
    'cancelled':        'cancelled',
    'pending':          'pending',
    'rejected':         'rejected',
}


def _normalize_status(raw: str) -> str:
    return _STATUS_MAP.get(str(raw).lower(), str(raw).lower())


# ── TradierBroker ─────────────────────────────────────────────────────────────

class TradierBroker(BrokerInterface):
    """
    Order execution via Tradier REST API.

    Paper trading note: Tradier sandbox fills limit orders immediately in most
    cases regardless of price level. Stop orders are server-side and fire
    automatically when the bid/ask crosses the stop price.
    """

    def __init__(self, token: str, account_id: str, sandbox: bool = True):
        self._token      = token
        self._account_id = account_id
        self._base       = _SANDBOX_BASE if sandbox else _PROD_BASE
        self._session    = requests.Session()
        self._session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept':        'application/json',
        })
        mode = 'sandbox (paper)' if sandbox else 'LIVE'
        logger.info(f"TradierBroker initialized — {mode}, account={account_id}")

    # ── BrokerInterface ───────────────────────────────────────────────────────

    def place_limit_buy(self, symbol: str, qty: int, limit_price: float) -> OrderResult:
        logger.info(f"LIMIT BUY: {qty} {symbol} @ ${limit_price:.2f}")
        return self._submit_order(
            symbol=symbol, qty=qty, side='buy',
            order_type='limit', price=limit_price,
        )

    def place_stop_sell(self, symbol: str, qty: int, stop_price: float) -> OrderResult:
        logger.info(f"STOP SELL: {qty} {symbol} stop @ ${stop_price:.2f}")
        return self._submit_order(
            symbol=symbol, qty=qty, side='sell',
            order_type='stop', stop=stop_price,
        )

    def place_market_sell(self, symbol: str, qty: int) -> OrderResult:
        logger.info(f"MARKET SELL: {qty} {symbol}")
        return self._submit_order(
            symbol=symbol, qty=qty, side='sell',
            order_type='market',
        )

    def cancel_order(self, order_id: str) -> bool:
        url = f'{self._base}/accounts/{self._account_id}/orders/{order_id}'
        try:
            r = self._session.delete(url, timeout=10)
            r.raise_for_status()
            ok = r.json().get('order', {}).get('status') == 'ok'
            if ok:
                logger.info(f"Cancelled order {order_id}")
            else:
                logger.warning(f"Cancel order {order_id} returned: {r.json()}")
            return ok
        except Exception as e:
            logger.warning(f"Cancel order {order_id} failed: {e}")
            return False

    def get_order(self, order_id: str) -> OrderResult:
        url = f'{self._base}/accounts/{self._account_id}/orders/{order_id}'
        r = self._session.get(url, timeout=10)
        r.raise_for_status()
        o = r.json()['order']
        return OrderResult(
            order_id=str(o['id']),
            status=_normalize_status(o.get('status', 'unknown')),
            filled_qty=int(float(o.get('exec_quantity', 0))),
            filled_price=float(o.get('avg_fill_price', 0.0)),
        )

    def get_account_balance(self) -> float:
        url = f'{self._base}/accounts/{self._account_id}/balances'
        r = self._session.get(url, timeout=10)
        r.raise_for_status()
        balances = r.json()['balances']
        # Best source: total_equity (works for both cash and margin accounts)
        if balances.get('total_equity'):
            return float(balances['total_equity'])
        # Fallback: cash account
        if 'cash' in balances and isinstance(balances['cash'], dict):
            return float(balances['cash'].get('cash_available', 0.0))
        # Fallback: margin account (stock_buying_power, not 'buying_power')
        if 'margin' in balances and isinstance(balances['margin'], dict):
            return float(balances['margin'].get('stock_buying_power', 0.0))
        return float(balances.get('total_cash', 0.0))

    def get_position(self, symbol: str) -> Optional[PositionResult]:
        url = f'{self._base}/accounts/{self._account_id}/positions'
        r = self._session.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()['positions']
        if not data or data == 'null':
            return None
        positions = data.get('position', [])
        if isinstance(positions, dict):
            positions = [positions]    # single position returned as dict, not list
        for pos in positions:
            if pos.get('symbol') == symbol:
                qty = int(float(pos.get('quantity', 0)))
                if qty > 0:
                    cost = float(pos.get('cost_basis', 0.0))
                    avg = cost / qty if qty > 0 else 0.0
                    return PositionResult(symbol=symbol, qty=qty, avg_price=avg)
        return None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str,
        price: float | None = None,
        stop: float | None = None,
    ) -> OrderResult:
        url = f'{self._base}/accounts/{self._account_id}/orders'
        data = {
            'class':    'equity',
            'symbol':   symbol,
            'side':     side,
            'quantity': str(qty),
            'type':     order_type,
            'duration': 'day',
        }
        if price is not None:
            data['price'] = f'{price:.2f}'
        if stop is not None:
            data['stop'] = f'{stop:.2f}'

        try:
            r = self._session.post(url, data=data, timeout=10)
            r.raise_for_status()
        except requests.HTTPError as e:
            logger.error(f"Order placement failed ({symbol} {side} {order_type}): "
                         f"{r.status_code} {r.text}")
            raise

        order_data = r.json().get('order', {})
        order_id = str(order_data.get('id', ''))
        # Tradier returns {'status': 'ok'} on successful submission
        status = 'pending' if order_data.get('status') == 'ok' else 'rejected'
        logger.info(f"Order submitted: id={order_id} status={status}")
        return OrderResult(order_id=order_id, status=status)


# ── TradierDataFeed ───────────────────────────────────────────────────────────

class TradierDataFeed(DataFeedInterface):
    """
    Market data via Tradier REST API.

    get_quotes()         — batched quotes endpoint, handles 4000+ symbols
    get_bars_since_4am() — timesales per symbol, call for 10-50 candidates only
    get_prior_closes()   — extracted from quotes' prevclose field

    Paper trading note: Tradier sandbox provides 15-minute delayed data.
    This is acceptable for strategy validation — the same patterns fire,
    just offset by 15 minutes. Relative timing and sequence are identical.
    """

    QUOTE_BATCH_SIZE = 200   # Symbols per /markets/quotes call

    def __init__(self, token: str, sandbox: bool = True):
        self._base    = _SANDBOX_BASE if sandbox else _PROD_BASE
        self._session = requests.Session()
        self._session.headers.update({
            'Authorization': f'Bearer {token}',
            'Accept':        'application/json',
        })
        logger.info(f"TradierDataFeed initialized: base={self._base} sandbox={sandbox}")

    # ── DataFeedInterface ─────────────────────────────────────────────────────

    def get_quotes(self, symbols: list[str]) -> dict[str, QuoteResult]:
        """Batch quote fetch. Internally batches into groups of QUOTE_BATCH_SIZE."""
        results: dict[str, QuoteResult] = {}
        for i in range(0, len(symbols), self.QUOTE_BATCH_SIZE):
            batch = symbols[i : i + self.QUOTE_BATCH_SIZE]
            results.update(self._fetch_quotes_batch(batch))
        return results

    def get_bars_since_4am(
        self,
        symbols: list[str],
        until_utc: datetime | None = None,
    ) -> dict[str, list[BarResult]]:
        """
        1-min bars from 4:00 AM ET today for each symbol (one HTTP call per symbol).
        Keep symbol list small (10-50 candidates post-filter).
        """
        results: dict[str, list[BarResult]] = {}
        now_et = (until_utc or datetime.now(timezone.utc)).astimezone(ET)
        today  = now_et.date()

        start_et  = ET.localize(datetime(today.year, today.month, today.day, 4, 0))
        start_str = start_et.strftime('%Y-%m-%d %H:%M')
        end_str   = now_et.strftime('%Y-%m-%d %H:%M')

        for symbol in symbols:
            bars = self._fetch_timesales(symbol, start_str, end_str)
            if bars:
                results[symbol] = bars
        return results

    def get_prior_closes(self, symbols: list[str]) -> dict[str, float]:
        """Extract prior close from quote data's prevclose field."""
        quotes = self.get_quotes(symbols)
        return {sym: q.prev_close for sym, q in quotes.items() if q.prev_close > 0}

    # ── Extra methods for TradierBarPoller ────────────────────────────────────

    def get_latest_bar(self, symbol: str, as_of_et: datetime) -> BarResult | None:
        """
        Fetch the most recently completed 1-minute bar for a symbol.
        Used by TradierBarPoller at :05 past each minute.

        Requests a 4-minute window ending at as_of_et, returns last bar.
        """
        start = as_of_et - timedelta(minutes=4)
        bars  = self._fetch_timesales(
            symbol,
            start.strftime('%Y-%m-%d %H:%M'),
            as_of_et.strftime('%Y-%m-%d %H:%M'),
        )
        return bars[-1] if bars else None

    # ── Private helpers ───────────────────────────────────────────────────────

    def _fetch_quotes_batch(self, symbols: list[str]) -> dict[str, QuoteResult]:
        if not symbols:
            return {}
        url    = f'{self._base}/markets/quotes'
        params = {'symbols': ','.join(symbols), 'greeks': 'false'}
        try:
            r = self._session.get(url, params=params, timeout=15)
            r.raise_for_status()
        except Exception as e:
            logger.warning(f"Quote fetch failed for batch of {len(symbols)}: {e}")
            return {}

        data = r.json().get('quotes', {})
        if not data or data == 'null':
            return {}

        raw_quotes = data.get('quote', [])
        if isinstance(raw_quotes, dict):
            raw_quotes = [raw_quotes]

        results = {}
        for q in raw_quotes:
            sym = q.get('symbol', '')
            if not sym:
                continue
            results[sym] = QuoteResult(
                symbol=sym,
                bid=float(q.get('bid', 0) or 0),
                ask=float(q.get('ask', 0) or 0),
                last=float(q.get('last', 0) or 0),
                prev_close=float(q.get('prevclose', 0) or 0),
                volume=float(q.get('volume', 0) or 0),
            )
        return results

    def _fetch_timesales(
        self,
        symbol: str,
        start_str: str,    # 'YYYY-MM-DD HH:MM' ET
        end_str: str,      # 'YYYY-MM-DD HH:MM' ET
    ) -> list[BarResult]:
        """Fetch 1-minute OHLCV bars for a single symbol over a time range."""
        url    = f'{self._base}/markets/timesales'
        params = {
            'symbol':         symbol,
            'interval':       '1min',
            'start':          start_str,
            'end':            end_str,
            'session_filter': 'all',   # include premarket + after-hours
        }
        try:
            r = self._session.get(url, params=params, timeout=10)
            r.raise_for_status()
        except Exception as e:
            logger.debug(f"Timesales fetch failed for {symbol}: {e}")
            return []

        series = r.json().get('series')
        if not series or series == 'null':
            return []

        raw_bars = series.get('data', [])
        if isinstance(raw_bars, dict):
            raw_bars = [raw_bars]

        bars = []
        for b in raw_bars:
            try:
                # Tradier provides 'timestamp' (Unix epoch seconds) and 'time' (string)
                ts = b.get('timestamp')
                if isinstance(ts, (int, float)):
                    bar_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                else:
                    # Fallback: parse ISO string as ET then convert to UTC
                    time_str = str(b.get('time', ''))
                    bar_time_naive = datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%S')
                    bar_time = ET.localize(bar_time_naive).astimezone(timezone.utc)

                bars.append(BarResult(
                    time=bar_time,
                    open=float(b['open']),
                    high=float(b['high']),
                    low=float(b['low']),
                    close=float(b['close']),
                    volume=int(b.get('volume', 0)),
                    vwap=float(b.get('vwap', 0) or 0),
                ))
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"Skipping malformed bar for {symbol}: {e} — {b}")
                continue

        return bars


# ── TradierBarPoller ──────────────────────────────────────────────────────────

class TradierBarPoller:
    """
    Tradier REST equivalent of AlpacaBarStream WebSocket.

    Polls 1-minute bars at :05 past each minute for all watchlist symbols.
    Pushes bar dicts (same format as AlpacaBarStream) to bar_queue.

    Deduplicates by bar timestamp — each completed bar is pushed exactly once
    even if the poller fetches overlapping windows.

    Thread safety: set_watchlist() / add_symbol() / remove_symbol() are safe
    to call from any thread. The poller thread only reads from the watchlist.

    Usage:
        poller = TradierBarPoller(token=token, sandbox=True, bar_queue=q)
        poller.set_watchlist(['AAPL', 'TSLA', ...])
        t = threading.Thread(target=poller.start, daemon=True)
        t.start()

        # Dynamically add symbols as new gap-runners are detected:
        poller.set_watchlist(scanner._gaprun_qualified)
    """

    def __init__(
        self,
        token: str,
        sandbox: bool = True,
        bar_queue: queue.Queue | None = None,
        delay_minutes: int | None = None,
    ):
        """
        delay_minutes: shift the engine clock into the past. The poller only
        delivers bars at least this old, so trade decisions line up with the
        sandbox fill engine (whose quotes run 15 min behind real time) even
        when the DATA comes from the real-time production feed.
        None (default) = legacy behavior: 15 when sandbox feed, else 0.
        """
        self._feed       = TradierDataFeed(token, sandbox=sandbox)
        self._sandbox    = sandbox
        self._delay_min  = (15 if sandbox else 0) if delay_minutes is None else delay_minutes
        self._bar_queue  = bar_queue or queue.Queue(maxsize=10_000)
        self._watchlist: set[str] = set()
        self._lock       = threading.Lock()
        self._stop_event = threading.Event()
        # Per-symbol: UTC time of last bar already pushed (deduplication)
        self._last_pushed: dict[str, datetime] = {}
        logger.info(f"TradierBarPoller initialized ({'sandbox' if sandbox else 'LIVE'}"
                    f"{f', engine delay {self._delay_min}min' if self._delay_min else ''})")

    @property
    def bar_queue(self) -> queue.Queue:
        return self._bar_queue

    def set_watchlist(self, symbols: list[str] | set[str]):
        """Replace watchlist atomically. Safe to call from any thread."""
        with self._lock:
            self._watchlist = set(symbols)
        logger.info(f"TradierBarPoller watchlist: {len(self._watchlist)} symbols")

    def add_symbol(self, symbol: str):
        """Add a single symbol. Safe to call from any thread."""
        with self._lock:
            self._watchlist.add(symbol)

    def remove_symbol(self, symbol: str):
        """Remove a symbol. Safe to call from any thread."""
        with self._lock:
            self._watchlist.discard(symbol)

    def start(self):
        """
        Blocking poll loop. Run in a background daemon thread.

        Sleeps to :05 past each ET minute, then fetches latest bar for
        every watchlist symbol. Exits when stop() is called.
        """
        logger.info("TradierBarPoller started")
        while not self._stop_event.is_set():
            self._sleep_to_next_poll()
            if self._stop_event.is_set():
                break
            self._poll_all()
        logger.info("TradierBarPoller stopped")

    def stop(self):
        """Signal the polling loop to stop."""
        self._stop_event.set()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _sleep_to_next_poll(self):
        """
        Sleep until :05 past the next ET minute.

        Examples:
            9:34:01 ET → sleep 64 seconds → wake at 9:35:05
            9:34:59 ET → sleep 6 seconds  → wake at 9:35:05
        """
        now_et   = datetime.now(pytz.UTC).astimezone(ET)
        next_min = now_et.replace(second=0, microsecond=0) + timedelta(minutes=1)
        target   = next_min.replace(second=5)
        sleep_sec = max(0.0, (target - now_et).total_seconds())

        # Wait in 0.5s increments to react to stop_event quickly
        deadline = time.time() + sleep_sec
        while time.time() < deadline and not self._stop_event.is_set():
            time.sleep(min(0.5, deadline - time.time()))

    def _poll_all(self):
        """
        Fetch the latest completed bar for every watchlist symbol.
        Push bars not yet seen to bar_queue (symbol key added to the dict).
        """
        now_et = datetime.now(pytz.UTC).astimezone(ET)
        # Engine clock shift: deliver bars at least delay_min old so paper
        # decisions match the sandbox fill engine's delayed quotes
        if self._delay_min:
            now_et = now_et - timedelta(minutes=self._delay_min)

        with self._lock:
            symbols = list(self._watchlist)

        if not symbols:
            return

        pushed = 0
        for symbol in symbols:
            try:
                bar = self._feed.get_latest_bar(symbol, as_of_et=now_et)
            except Exception as e:
                logger.warning(f"get_latest_bar({symbol}) failed: {e}")
                continue

            if bar is None:
                continue

            # Deduplicate: only push each bar time once per symbol
            last = self._last_pushed.get(symbol)
            if last is not None and bar.time <= last:
                continue

            self._last_pushed[symbol] = bar.time

            bar_dict = bar.to_bar_dict()
            bar_dict['symbol'] = symbol    # matches AlpacaBarStream dict format

            try:
                self._bar_queue.put_nowait(bar_dict)
                pushed += 1
            except queue.Full:
                logger.warning(f"Bar queue full — dropping bar for {symbol}")

            record_bar(symbol, bar_dict, source='poller')

        logger.info(
            f"TradierBarPoller: pushed {pushed}/{len(symbols)} bars "
            f"at {now_et.strftime('%H:%M:%S')} "
            f"({'delayed' if self._delay_min else 'live'})"
        )
